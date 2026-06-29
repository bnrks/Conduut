"""Shared pytest fixtures and Windows temp-dir isolation for the agent suite."""

import logging
import os
import tempfile

import pytest

# Isolate pytest's temp root from the shared system ``pytest-of-<user>`` dir.
# On Windows that shared dir can get permission-locked by a leaked file handle
# from a crashed/earlier run, after which ``tmp_path`` setup fails with
# PermissionError (WinError 5) for EVERY later run. A project-dedicated temp root
# (still outside the repo, so _find_repo_root tests stay isolated) avoids that
# shared-state corruption. Set before pytest first computes the temp root.
os.environ.setdefault(
    "PYTEST_DEBUG_TEMPROOT", os.path.join(tempfile.gettempdir(), "conduut-pytest")
)
# pytest does not create the temp root's parent; ensure it exists.
os.makedirs(os.environ["PYTEST_DEBUG_TEMPROOT"], exist_ok=True)


@pytest.fixture(autouse=True)
def _close_logging_file_handlers():
    """Close file handlers that ``configure_logging(force=True)`` installs.

    The logging tests attach a ``RotatingFileHandler`` to a ``tmp_path`` file and
    only flush it; leaving it open keeps the file locked on Windows, so pytest's
    ``tmp_path`` cleanup fails with ``PermissionError`` (WinError 5) and corrupts
    the shared temp root for later runs. Closing handlers after each test releases
    the file so cleanup succeeds.
    """
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.FileHandler):
            handler.close()
            root.removeHandler(handler)
