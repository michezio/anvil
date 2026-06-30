"""Entry point for running anvil as a module: python -m anvil"""

import sys
from .anvil import main

if __name__ == "__main__":
    sys.exit(main())
