#!/usr/bin/env python3
"""Release an aggregate (numbers only) from the sealed root into the released directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from recall_guard.release import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
