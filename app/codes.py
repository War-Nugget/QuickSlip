"""Code generation utilities."""

import secrets
import uuid
from pathlib import Path

from . import config


def generate_code() -> str:
    """Cryptographically random short code, ambiguous chars excluded."""
    return "".join(secrets.choice(config.CODE_ALPHABET) for _ in range(config.CODE_LENGTH))
