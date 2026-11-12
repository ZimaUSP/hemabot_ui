"""Runs the frontend unit tests (tests/js) with Node's built-in test runner."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_frontend_unit_tests_pass() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    test_files = sorted(str(path) for path in (REPO / "tests" / "js").glob("*.test.mjs"))
    assert test_files, "no frontend tests found"
    result = subprocess.run(
        [node, "--test", *test_files],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
