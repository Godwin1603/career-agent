"""
Central model registry.

Importing this module guarantees that every SQLAlchemy model is registered on
Base.metadata before Alembic autogenerate or SQLAlchemy schema operations run.

Usage:
  import src.core.model_registry  # noqa: F401  (in migrations/env.py)

Rules:
  - Import every models.py file here.
  - Never import business logic from here.
  - This file must remain free of side effects beyond model registration.
"""

# Core
# Domain models
import src.applications.models  # noqa: F401
import src.core.task_log  # noqa: F401
import src.jobs.models  # noqa: F401
import src.notifications.models  # noqa: F401
import src.portals.models  # noqa: F401
import src.resumes.models  # noqa: F401
