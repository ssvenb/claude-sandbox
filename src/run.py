#!/usr/bin/env python3
"""Entry point of run.sh: the host side lives in src/host (see its __init__.py)."""
import sys

from host.main import main

sys.exit(main())
