import os
from pathlib import Path

# Base data directory (can be overridden by OPENFLUX_HOME env var)
OPENFLUX_HOME = os.getenv("OPENFLUX_HOME", os.path.expanduser("~/.openflux"))
BASE_DIR = Path(OPENFLUX_HOME)

# Standard directories
BIN_DIR = BASE_DIR / "bin"
BIN_PATH = BIN_DIR / "openflux"
KEYS_DIR = BASE_DIR / "keys"
LOGS_DIR = BASE_DIR / "logs"
RUN_DIR = BASE_DIR / "run"
USERS_FILE = BASE_DIR / "users.json"

# GitHub Repo
GITHUB_REPO = "p1neappleXpress/OpenFlux"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# Supported Transports
SUPPORTED_TRANSPORTS = [
    "telemost",
    "yandex",
    "vyandex",
    "boards",
    "mailru",
    "cupsonline",
    "avito",
    "oneme",
    "direct",
    "script",
]

# Cryptography
MIN_SECRET_CHARS = 16
DEFAULT_SECRET_BYTES = 32

def ensure_directories():
    """Ensure all required directories exist with secure permissions."""
    for d in [BASE_DIR, BIN_DIR, KEYS_DIR, LOGS_DIR, RUN_DIR]:
        d.mkdir(parents=True, exist_ok=True)
        # Apply secure permissions (0700) to keys and run directories
        if d in [KEYS_DIR, RUN_DIR]:
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass
