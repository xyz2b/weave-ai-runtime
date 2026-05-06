from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True

for src_root in reversed(sorted(PROJECT_ROOT.glob("packages/**/src"))):
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
