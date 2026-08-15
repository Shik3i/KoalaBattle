from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_documentation_and_setup_references_are_current() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_docs.py")],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
