"""Root conftest.py — path setup for all tests."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# Shared library
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

# Service roots (unique package names: market_data_svc, storage_svc)
sys.path.insert(0, str(PROJECT_ROOT / "services" / "market-data"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "storage"))
