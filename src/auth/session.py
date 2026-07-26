"""
SessionManager — manages browser session state on disk.

Sessions are stored as marker files alongside the Playwright persistent
profile directories that BrowserManager creates in Phase 8.  This lets
the authentication layer check whether a profile already holds valid
cookies before deciding to re-authenticate.

Session state is intentionally minimal: we only track whether the
profile directory exists and contains a non-empty "session.json"
marker file.  The actual cookies / storage are maintained by Chromium.

IMPORTANT: Session files MUST NEVER be logged.  Only profile_id and
           the boolean outcome are surfaced in logs.
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SESSION_FILENAME = "session.json"


class SessionError(Exception):
    """Raised when a session operation fails in an unrecoverable way."""


class SessionManager:
    """
    Manages session lifecycle for browser profiles.

    Works alongside the :class:`~src.workers.playwright.browser.BrowserManager`
    profile directories.  Each profile gets a small ``session.json`` marker
    that records non-sensitive metadata (e.g. creation timestamp, portal name).
    The sensitive browser state (cookies, localStorage) lives inside the
    Chromium profile and is managed by Playwright.

    Args:
        profiles_dir: Root directory for browser profiles.  Must match the
            ``user_data_dir`` passed to :class:`BrowserManager`.
    """

    def __init__(self, profiles_dir: str = ".browser_profiles") -> None:
        self._root = Path(profiles_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _session_path(self, profile_id: str) -> Path:
        return self._root / profile_id / _SESSION_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save_session(
        self,
        profile_id: str,
        portal: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Persist a session marker for *profile_id*.

        Writes a small JSON file with non-sensitive metadata.
        Session contents (cookies) are NOT written here.

        Args:
            profile_id: Browser profile identifier.
            portal: Human-readable portal name (optional).
            metadata: Arbitrary non-sensitive key/value pairs (optional).
        """
        import time

        path = self._session_path(profile_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload: dict = {
            "profile_id": profile_id,
            "created_at": time.time(),
        }
        if portal:
            payload["portal"] = portal
        if metadata:
            payload.update(metadata)

        path.write_text(json.dumps(payload), encoding="utf-8")
        logger.info("Session saved (profile_id=%r)", profile_id)

    async def load_session(self, profile_id: str) -> Optional[dict]:
        """
        Load the session marker for *profile_id*.

        Returns the parsed metadata dict, or ``None`` when no session exists.
        Session contents (cookies) live in the Playwright profile and are
        loaded automatically by the browser.

        NEVER log the returned dict — it may contain portal names that could
        be used to infer authentication state.
        """
        path = self._session_path(profile_id)
        if not path.exists():
            logger.debug("No session found (profile_id=%r)", profile_id)
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info("Session loaded (profile_id=%r)", profile_id)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Session file corrupt or unreadable (profile_id=%r): %s",
                profile_id,
                type(exc).__name__,
            )
            return None

    async def validate_session(self, profile_id: str) -> bool:
        """
        Return ``True`` when a non-empty session marker exists.

        This is a lightweight disk check only.  It does NOT make network
        requests or open a browser.

        A ``False`` return value indicates the caller must re-authenticate.
        """
        path = self._session_path(profile_id)
        if not path.exists():
            logger.debug(
                "Session validation failed — file absent (profile_id=%r)", profile_id
            )
            return False

        try:
            content = path.read_text(encoding="utf-8").strip()
            valid = bool(content)
        except OSError:
            valid = False

        logger.info(
            "Session validation result (profile_id=%r, valid=%s)", profile_id, valid
        )
        return valid

    async def invalidate_session(self, profile_id: str) -> None:
        """
        Delete the session marker for *profile_id*.

        The underlying Playwright profile directory is left intact so that
        the browser can still be launched; only the session marker file is
        removed.  This forces re-authentication on the next run.
        """
        path = self._session_path(profile_id)
        if path.exists():
            try:
                path.unlink()
                logger.info("Session invalidated (profile_id=%r)", profile_id)
            except OSError as exc:
                logger.warning(
                    "Failed to delete session file (profile_id=%r): %s",
                    profile_id,
                    type(exc).__name__,
                )
        else:
            logger.debug(
                "Session invalidation skipped — file absent (profile_id=%r)", profile_id
            )
