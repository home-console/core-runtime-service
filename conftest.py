from __future__ import annotations

import sys
from pathlib import Path


ROOT = str(Path(__file__).resolve().parent)
if ROOT not in sys.path:
    # Make in-repo packages like `sdk` and `plugins` importable in any pytest invocation.
    sys.path.insert(0, ROOT)

