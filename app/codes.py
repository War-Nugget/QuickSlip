"""Code generation utilities."""

import secrets
import uuid
from pathlib import Path

from . import config


def generate_code() -> str:
    """Cryptographically random short code, ambiguous chars excluded."""
    return "".join(secrets.choice(config.CODE_ALPHABET) for _ in range(config.CODE_LENGTH))

def normalize_code(code: str) -> str:
    """Be forgiving about how users type codes (case, spaces, dashes)."""
    return code.strip().lower().replace(" ", "").replace("-", "")


def new_file_path() -> Path:
    """Random on-disk path for an uploaded file (never derived from user input)."""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return config.UPLOAD_DIR / uuid.uuid4().hex


def safe_filename(name: str) -> str:
    """Sanitize the original filename for the download header."""
    name = Path(name or "file").name  # strip any path components
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in "._- ")
    return cleaned[:120] or "file"