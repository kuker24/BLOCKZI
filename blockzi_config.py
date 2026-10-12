"""Centralized configuration for Blockzi bot and co-pilot."""
import os
import tempfile
from pathlib import Path

# Repository root directory
REPO_ROOT = Path(__file__).resolve().parent

# Logging
DEFAULT_LOG_FILE = REPO_ROOT / "autobot" / "autobot.log"
LOG_FILE = Path(os.environ.get("BLOCKZI_LOG_FILE", str(DEFAULT_LOG_FILE))).resolve()
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# Temporary screen directory (for screenshots/frames)
DEFAULT_SCREEN_DIR = Path(tempfile.gettempdir()) / "blockzi"
SCREEN_DIR = Path(os.environ.get("BLOCKZI_SCREEN_DIR", str(DEFAULT_SCREEN_DIR))).resolve()
SCREEN_DIR.mkdir(parents=True, exist_ok=True)

# Server networking & security
HOST = os.environ.get("BLOCKZI_HOST", "127.0.0.1")
PORT = int(os.environ.get("BLOCKZI_PORT", "5000"))
TOKEN = os.environ.get("BLOCKZI_TOKEN", "").strip()

# Solver configuration
SOLVER_MAX_MS = int(os.environ.get("BLOCKZI_SOLVER_MAX_MS", "200"))
EVAL_MODE = os.environ.get("BLOCKZI_EVAL", "v1").lower()
