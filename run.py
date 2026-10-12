"""Entry point used by the Nuitka build (see build.ps1)."""

import sys

from idlerig.cli import main

if __name__ == "__main__":
    sys.exit(main())
