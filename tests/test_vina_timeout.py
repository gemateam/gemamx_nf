from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

from run_vina import run_with_timeout  # noqa: E402


def test_timeout_terminates_process_group():
    with pytest.raises(subprocess.TimeoutExpired):
        run_with_timeout(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.1,
        )
