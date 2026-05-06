from pathlib import Path
import runpy

TARGET = Path(__file__).resolve().parents[1] / "packages" / "toolchain" / "scripts" / "check_workspace_layout.py"

globals().update(runpy.run_path(str(TARGET)))
