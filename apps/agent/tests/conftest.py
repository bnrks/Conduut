"""Shared pytest fixtures and Windows temp-dir isolation for the agent suite."""

import asyncio
import logging
import os
import tempfile

import pytest

from src.agent.schemas import AgentDeps

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


@pytest.fixture
def make_agent_deps():
    """Factory fixture: returns a callable that builds an AgentDeps with sensible defaults.

    Each call produces a fresh AgentDeps (and a fresh asyncio.Queue) so tests
    that call it multiple times stay isolated.  Override any field via kwargs.
    """

    def _make(**overrides):
        params: dict = {
            "user_id": "user_1",
            "conversation_id": "conv_1",
            "event_queue": asyncio.Queue(),
        }
        params.update(overrides)
        return AgentDeps(**params)

    return _make


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
