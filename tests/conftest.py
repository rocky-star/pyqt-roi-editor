"""Shared configuration for the headless test suite.

The suite runs with the offscreen platform plugin and shares one
`QApplication`, created by the `qapp` fixture.

pytest-qt is deliberately not used: its plugin hooks call camelCase Qt
methods such as ``QApplication.processEvents()``, which PySide6 hides
once the ``__feature__`` import is active, so its hooks fail before any
test runs.
"""

import os

import pytest
from PySide6.QtWidgets import QApplication

from __feature__ import snake_case, true_property


def pytest_configure() -> None:
    """Select the offscreen platform before any window is created."""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='session')
def qapp():
    """Return the one application every test shares."""
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    yield application
    application.process_events()
