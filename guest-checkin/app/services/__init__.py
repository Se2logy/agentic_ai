"""Application services — email, payment, storage, secure links."""

from app.services.email_service import EmailService, email_service
from app.services.link_service import LinkService, link_service
from app.services.payment_service import (
    MockPayment,
    PaymentGateway,
    PaymentResult,
    payment_service,
)
from app.services.storage_service import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    FileTooLargeError,
    InvalidExtensionError,
    StorageService,
    StorageServiceError,
    storage_service,
)

__all__ = [
    # Email
    "EmailService",
    "email_service",
    # Payment
    "PaymentGateway",
    "PaymentResult",
    "MockPayment",
    "payment_service",
    # Storage
    "StorageService",
    "StorageServiceError",
    "FileTooLargeError",
    "InvalidExtensionError",
    "ALLOWED_EXTENSIONS",
    "MAX_FILE_SIZE_BYTES",
    "storage_service",
    # Links
    "LinkService",
    "link_service",
]
