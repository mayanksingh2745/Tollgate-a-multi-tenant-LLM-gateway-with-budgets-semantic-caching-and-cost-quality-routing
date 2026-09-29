import sys
from pathlib import Path

# Ensure packages/core/src is in sys.path if running outside installed package
core_path = Path(__file__).resolve().parents[3] / "packages" / "core" / "src"
if core_path.exists() and str(core_path) not in sys.path:
    sys.path.insert(0, str(core_path))

from tollgate_core.config import Settings, settings

__all__ = ["Settings", "settings"]
