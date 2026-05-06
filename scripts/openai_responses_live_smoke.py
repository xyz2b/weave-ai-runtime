from pathlib import Path
import runpy

TARGET = Path(__file__).resolve().parents[1] / "packages" / "toolchain" / "scripts" / "openai_responses_live_smoke.py"

globals().update(runpy.run_path(str(TARGET)))
