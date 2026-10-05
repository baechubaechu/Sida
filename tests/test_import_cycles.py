"""The modules split out of the old harness.py import cleanly, each on its own."""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from tests.conftest import ROOT


@pytest.mark.parametrize("module", ["config", "providers", "runtime", "worker", "conductor_context"])
def test_module_imports_on_its_own(module):
    # A circular import only shows when the module is the first one loaded.
    done = subprocess.run(
        [sys.executable, "-c", f"import sida.{module}"], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr


def test_there_is_one_place_to_import_each_name_from():
    # These modules used to be one file, harness.py. Bringing it back as a module that
    # re-exports them would give every function two import paths, and a test patch applied
    # to one path would not reach code that uses the other.
    assert importlib.util.find_spec("sida.harness") is None
