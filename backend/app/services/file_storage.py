"""
Handles writing uploaded files to disk *encrypted*, and reading them back.
This is a genuine implementation of TRD §7.1's "encrypted at rest" requirement
— not a TODO. It uses Fernet (AES-128-CBC + HMAC) from the `cryptography`
package, which is appropriate for a project this size; a larger deployment
would likely move this to a KMS-backed key and object storage (S3/GCS) rather
than local disk, but the encrypt/decrypt boundary here is written so that
swap only touches this one file.
"""
import os
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

from app.core.config import get_settings

settings = get_settings()

_KEY_FILE = Path(settings.DATA_DIR) / ".file_encryption_key"


def _get_fernet() -> Fernet:
    key = settings.FILE_ENCRYPTION_KEY.strip()
    if not key:
        # Dev convenience: generate once and persist, so restarts can still
        # decrypt previously-uploaded files. A real deployment should set
        # FILE_ENCRYPTION_KEY explicitly (e.g. from a secrets manager) instead
        # of relying on this file.
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _KEY_FILE.exists():
            key = _KEY_FILE.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            _KEY_FILE.write_text(key)
    return Fernet(key.encode())


def save_encrypted(raw_bytes: bytes, original_filename: str) -> tuple[str, int]:
    """
    Encrypts raw_bytes and writes them to UPLOADS_DIR under a random name
    (never the original filename, to avoid leaking anything through the path).
    Returns (storage_path, plaintext_size_bytes).
    """
    uploads_dir = Path(settings.UPLOADS_DIR)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(original_filename).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}.enc"
    storage_path = uploads_dir / stored_name

    fernet = _get_fernet()
    encrypted = fernet.encrypt(raw_bytes)
    storage_path.write_bytes(encrypted)

    return str(storage_path), len(raw_bytes)


def read_decrypted(storage_path: str) -> bytes:
    fernet = _get_fernet()
    encrypted = Path(storage_path).read_bytes()
    return fernet.decrypt(encrypted)


def delete_file(storage_path: str) -> None:
    try:
        os.remove(storage_path)
    except FileNotFoundError:
        pass
