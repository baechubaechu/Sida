"""Stand-in for $EDITOR in tests: appends argv[1] to the file argv[2]."""

import sys
from pathlib import Path

append = sys.argv[1]
path = Path(sys.argv[2])
if append:
    with path.open("a", encoding="utf-8") as f:
        f.write(append)
