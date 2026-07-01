"""Application exception hierarchy.

Validation and domain errors intentionally inherit from ``ValueError`` to keep
legacy callers compatible while giving newer integrations stable error types.
"""


class ApplicationError(Exception):
    """Base class for expected application failures."""


class ValidationError(ApplicationError, ValueError):
    """Input failed application-level validation."""


class AuthenticationError(ApplicationError):
    """Authentication could not be completed."""


class AuthorizationError(ApplicationError):
    """The authenticated user is not permitted to perform an operation."""


class InventoryError(ValidationError):
    """Inventory state prevents an operation."""


class SalesError(ValidationError):
    """A sale or return operation is invalid."""


class TransferError(ValidationError):
    """A stock transfer operation is invalid."""


class ProcurementError(ValidationError):
    """A procurement operation is invalid."""


class StoreError(ValidationError):
    """A store operation is invalid."""


class DocumentError(ValidationError):
    """A document cannot be generated from the requested record."""


class ConfigurationError(ApplicationError, ValueError):
    """Application configuration is malformed."""
