"""Install NVDA module stubs before any source module is imported.

NVDA's Python environment provides modules (appModuleHandler, logHandler,
UIAHandler, ui, core, and api) that are not available in a plain Python install.
We create lightweight stubs and register them in sys.modules so that
`import discord` (our AppModule package) can be resolved in tests.
"""

import os
import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Add appModules/ to sys.path so `import discord` resolves our package.
# ---------------------------------------------------------------------------
_APPMODULES_DIR = os.path.join(os.path.dirname(__file__), "..", "appModules")
if _APPMODULES_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_APPMODULES_DIR))


def _stub(name):
    """Create an empty module stub and register it in sys.modules."""
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _install_stubs():
    # appModuleHandler — base class for all NVDA AppModules
    m = _stub("appModuleHandler")

    class _BaseAppModule:
        processID: int = 9999

        def __init__(self, *args, **kwargs):
            pass

        def terminate(self):
            pass

    m.AppModule = _BaseAppModule

    # logHandler
    m = _stub("logHandler")
    m.log = MagicMock()

    # UIAHandler
    m = _stub("UIAHandler")
    m.handler = MagicMock()

    # ui — user-facing messages reach both speech and braille in NVDA.
    m = _stub("ui")
    m.message = MagicMock()

    # core — callLater is the NVDA-idiomatic thread-safe timer
    m = _stub("core")
    m.callLater = MagicMock(return_value=MagicMock())

    # api — NVDA object focus API
    m = _stub("api")
    m.getForegroundObject = MagicMock(return_value=None)


_install_stubs()

# ---------------------------------------------------------------------------
# Now it is safe to import from our package.
# ---------------------------------------------------------------------------
from unittest.mock import patch

import pytest


@pytest.fixture()
def app_module():
    """Return a live AppModule instance with timer calls stubbed out."""
    with patch("core.callLater", return_value=MagicMock()):
        # Import here so stubs are in place
        from discord import AppModule

        sys.modules["api"].getForegroundObject.reset_mock()
        sys.modules["api"].getForegroundObject.return_value = None
        sys.modules["UIAHandler"].handler.clientObject = None
        instance = AppModule()
        sys.modules["ui"].message.reset_mock()
        sys.modules["ui"].message.side_effect = None
        sys.modules["logHandler"].log.reset_mock()
        yield instance

        # Clean up without scheduling another poll.
        instance._terminated = True
        instance._pollTimer = None
