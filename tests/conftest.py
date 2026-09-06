"""Make the repo root importable so tests can ``import agent`` and ``import mikhail_letal``."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
