class CareerAgentException(Exception):
    """Base exception for all custom career-agent errors."""

    pass


class ConfigurationError(CareerAgentException):
    """Raised when application configuration is missing or invalid."""

    pass


class InfrastructureError(CareerAgentException):
    """Raised when a core infrastructure dependency fails (e.g., Redis, DB)."""

    pass
