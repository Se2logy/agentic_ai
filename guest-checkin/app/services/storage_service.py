"""Async file storage service for guest ID document uploads."""

import logging
from pathlib import Path

import aiofiles
import aiofiles.os

from app.config import settings

logger = logging.getLogger(__name__)

# Constraints for ID document uploads
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".pdf"}


class StorageServiceError(Exception):
    """Base exception for storage service errors."""


class FileTooLargeError(StorageServiceError):
    """Raised when an uploaded file exceeds the size limit."""


class InvalidExtensionError(StorageServiceError):
    """Raised when an uploaded file has a disallowed extension."""


class StorageService:
    """Async file storage for ID document uploads.

    Files are stored under ``UPLOAD_DIR/<subfolder>/<filename>``.
    The upload directory and subfolders are created on demand.
    """

    def __init__(self) -> None:
        self.upload_dir = Path(settings.UPLOAD_DIR)

    async def save_file(
        self, file_data: bytes, filename: str, subfolder: str = "ids"
    ) -> str:
        """Save file data to disk and return the full path.

        Args:
            file_data: Raw file bytes.
            filename: Original filename (used for extension validation).
            subfolder: Subdirectory under UPLOAD_DIR (default: "ids").

        Returns:
            The full filesystem path of the saved file.

        Raises:
            FileTooLargeError: If file_data exceeds 10 MB.
            InvalidExtensionError: If filename extension is not allowed.
        """
        self._validate_extension(filename)
        self._validate_size(file_data)

        dest_dir = self.upload_dir / subfolder
        await self._ensure_dir(dest_dir)

        dest_path = dest_dir / filename

        async with aiofiles.open(str(dest_path), "wb") as f:
            await f.write(file_data)

        logger.info("Saved file %s (%d bytes)", dest_path, len(file_data))
        return str(dest_path)

    async def get_file(self, path: str) -> bytes:
        """Read and return file contents from disk.

        Args:
            path: Full filesystem path to the file.

        Returns:
            The raw file bytes.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        async with aiofiles.open(path, "rb") as f:
            data = await f.read()
        return data

    # ── Validation helpers ────────────────────────────────────────

    @staticmethod
    def _validate_extension(filename: str) -> None:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise InvalidExtensionError(
                f"File extension '{ext}' is not allowed. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

    @staticmethod
    def _validate_size(file_data: bytes) -> None:
        if len(file_data) > MAX_FILE_SIZE_BYTES:
            raise FileTooLargeError(
                f"File size {len(file_data)} bytes exceeds the "
                f"maximum allowed size of {MAX_FILE_SIZE_BYTES} bytes."
            )

    # ── Directory helpers ─────────────────────────────────────────

    @staticmethod
    async def _ensure_dir(directory: Path) -> None:
        """Create directory (and parents) if it doesn't exist."""
        if not directory.exists():
            await aiofiles.os.makedirs(str(directory), exist_ok=True)


# Singleton instance
storage_service = StorageService()
