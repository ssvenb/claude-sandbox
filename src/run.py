#!/usr/bin/env python3
"""Entry point of run.sh: the host side lives in src/orchestrator (see its __init__.py)."""
import sys

from orchestrator.main import main

sys.exit(main())
