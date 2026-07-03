"""Main config for QuickSlip. Values can be overridden with env vars."""
import os
from pathlib import Path

# How long a file lives, in seconds (15 minutes)
FILE_TTL_SECONDS = int(os.getenv("QUICKSLIP_TTL", 15 * 60))

# Max upload size in bytes (default 100 MB)
MAX_FILE_SIZE = int(os.getenv("QUICKSLIP_MAX_SIZE", 100 * 1024 * 1024))

# Code settings: 6 chars, ambiguous characters removed (no 0/O, 1/l/I)
CODE_LENGTH = int(os.getenv("QUICKSLIP_CODE_LENGTH", 6))
CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"

# Where uploaded files are kept while they're alive
UPLOAD_DIR = Path(os.getenv("QUICKSLIP_UPLOAD_DIR", "/tmp/quickslip_uploads"))

# Redis connection (falls back to in-memory store if unreachable)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Rate limiting: max wrong-code guesses per IP per window
RATE_LIMIT_ATTEMPTS = int(os.getenv("QUICKSLIP_RATE_ATTEMPTS", 10))
RATE_LIMIT_WINDOW = int(os.getenv("QUICKSLIP_RATE_WINDOW", 60))  # seconds

# Delete file after first successful download?
DELETE_AFTER_DOWNLOAD = os.getenv("QUICKSLIP_ONE_TIME", "true").lower() == "true"
