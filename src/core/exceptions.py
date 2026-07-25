class CareerAgentException(Exception):
    """Base exception for all custom career-agent errors."""

    pass


class ConfigurationError(CareerAgentException):
    """Raised when application configuration is missing or invalid."""

    pass


class InfrastructureError(CareerAgentException):
    """Raised when a core infrastructure dependency fails (e.g., Redis, DB)."""

    pass


class EntityNotFound(CareerAgentException):
    """Raised when a required entity does not exist in the database."""

    def __init__(self, entity_type: str, entity_id: object) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(f"{entity_type} with id={entity_id!r} not found.")


class RepositoryError(CareerAgentException):
    """Raised when an unexpected database error occurs in a repository."""

    pass
