"""Root conftest.py — path setup for all tests."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# Shared library
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

# Service roots (each has a unique package name to avoid import collisions)
sys.path.insert(0, str(PROJECT_ROOT / "services" / "market-data"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "storage"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "alpha-engine"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "risk-gateway"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "execution"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "post-trade"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "backtest"))
