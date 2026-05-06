import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOTS = tuple(sorted(ROOT.glob("packages/**/src")))
for src_root in reversed(SRC_ROOTS):
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))


@pytest.fixture(autouse=True)
def _clear_bundled_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep Python tests hermetic unless they opt in with local env setup.
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
