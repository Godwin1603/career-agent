"""
Repository for the resumes domain.

Provides persistence operations for Resume and ApplicationResume.
No business logic. Session is injected by the caller.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, select

from src.core.enums import ResumeLabel
from src.core.exceptions import EntityNotFound
from src.core.repository import BaseRepository
from src.resumes.models import ApplicationResume, Resume


class ResumeRepository(BaseRepository[Resume]):
    """Persistence operations for resume version records."""

    model = Resume

    async def get_base_resume(self) -> Resume | None:
        """
        Return the most recently created base resume, or None if none exists.
        There is typically one canonical base resume at a time.
        """
        stmt = (
            select(Resume)
            .where(Resume.label == ResumeLabel.base)
            .order_by(Resume.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_tailored_for_job(self, job_id: uuid.UUID) -> Resume | None:
        """
        Return the tailored resume for the given job, or None if not yet generated.
        Used by the Resume Manager cache check before generating a new version.
        """
        stmt = (
            select(Resume)
            .where(
                and_(
                    Resume.label == ResumeLabel.tailored,
                    Resume.job_id == job_id,
                )
            )
            .order_by(Resume.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_by_content_hash(self, content_hash: str) -> Resume | None:
        """
        Return a resume matching the given SHA-256 content hash, or None.
        Used to detect whether the base resume has changed since a tailored
        version was generated.
        """
        stmt = select(Resume).where(Resume.content_hash == content_hash).limit(1)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_by_label(self, label: ResumeLabel) -> list[Resume]:
        """Return all resumes with the given label, newest-first."""
        stmt = (
            select(Resume)
            .where(Resume.label == label)
            .order_by(Resume.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_tailored_for_job(self, job_id: uuid.UUID) -> list[Resume]:
        """Return all tailored resumes for the given job, newest-first."""
        stmt = (
            select(Resume)
            .where(
                and_(
                    Resume.label == ResumeLabel.tailored,
                    Resume.job_id == job_id,
                )
            )
            .order_by(Resume.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class ApplicationResumeRepository(BaseRepository[ApplicationResume]):
    """
    Persistence operations for the application_resumes join table.

    Note: ApplicationResume has a composite primary key
    (application_id, resume_id). get_by_id() from BaseRepository is not
    applicable; use get_by_application_and_resume() instead.
    """

    model = ApplicationResume

    async def get_by_application_and_resume(
        self,
        application_id: uuid.UUID,
        resume_id: uuid.UUID,
    ) -> ApplicationResume | None:
        """Return the join record for the given (application, resume) pair."""
        stmt = select(ApplicationResume).where(
            and_(
                ApplicationResume.application_id == application_id,
                ApplicationResume.resume_id == resume_id,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_for_application(
        self, application_id: uuid.UUID
    ) -> ApplicationResume | None:
        """
        Return the single resume link for an application, or None.
        Each application uses exactly one resume version.
        """
        stmt = select(ApplicationResume).where(
            ApplicationResume.application_id == application_id
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_resume_for_application(
        self, application_id: uuid.UUID
    ) -> Resume | None:
        """
        Return the Resume entity used for the given application.
        Performs a join to avoid a second round-trip.
        """
        stmt = (
            select(Resume)
            .join(
                ApplicationResume,
                ApplicationResume.resume_id == Resume.id,
            )
            .where(ApplicationResume.application_id == application_id)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def exists_for_application(self, application_id: uuid.UUID) -> bool:
        """Return True if a resume has already been linked to this application."""
        return await self.exists(ApplicationResume.application_id == application_id)

    async def get_by_composite_pk(
        self,
        application_id: uuid.UUID,
        resume_id: uuid.UUID,
    ) -> ApplicationResume:
        """
        Return the join record for a given composite PK.
        Raises EntityNotFound if not found.
        """
        result = await self._session.get(
            ApplicationResume,
            {"application_id": application_id, "resume_id": resume_id},
        )
        if result is None:
            raise EntityNotFound(
                ApplicationResume.__name__,
                f"application_id={application_id}, resume_id={resume_id}",
            )
        return result
