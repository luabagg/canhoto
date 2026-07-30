"""Allow ``python -m canhoto`` to dispatch to the CLI."""

from __future__ import annotations

import sys

from canhoto.cli import main

if __name__ == "__main__":
    sys.exit(main())
