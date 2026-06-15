#!/usr/bin/env python3
"""Entry point shim — delegates to the analysis_guard package."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from analysis_guard.cli import main  # noqa: E402

sys.exit(main())
