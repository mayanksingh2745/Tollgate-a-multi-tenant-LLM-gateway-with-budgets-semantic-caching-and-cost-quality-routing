import sys
from pathlib import Path

root = Path(__file__).resolve().parent
for p in [root, root / "apps", root / "packages" / "core" / "src", root / "apps" / "gateway"]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import uvicorn
from gateway.src.main import app

if __name__ == "__main__":
    print("[Tollgate Gateway] Starting backend API on http://localhost:8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
