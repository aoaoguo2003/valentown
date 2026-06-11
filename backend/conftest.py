import sys
from pathlib import Path

# Ensure the backend package modules are importable when running pytest from
# either the repository root or the backend directory.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
