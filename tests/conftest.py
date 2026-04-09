"""Install NVDA module stubs before any source module is imported.

NVDA's Python environment provides modules (appModuleHandler, logHandler,
UIAHandler, speech, wx, api) that are not available in a plain Python install.
We create lightweight stubs and register them in sys.modules so that
`import discord` (our AppModule package) can be resolved in tests.
"""
import sys
import os
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Add appModules/ to sys.path so `import discord` resolves our package.
# ---------------------------------------------------------------------------
_APPMODULES_DIR = os.path.join(os.path.dirname(__file__), '..', 'appModules')
if _APPMODULES_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_APPMODULES_DIR))


def _stub(name):
    """Create an empty module stub and register it in sys.modules."""
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _install_stubs():
    # appModuleHandler — base class for all NVDA AppModules
    m = _stub('appModuleHandler')

    class _BaseAppModule:
        processID: int = 9999

        def __init__(self, *args, **kwargs):
            pass

        def terminate(self):
            pass

    m.AppModule = _BaseAppModule

    # logHandler
    m = _stub('logHandler')
    m.log = MagicMock()

    # UIAHandler
    m = _stub('UIAHandler')
    m.handler = MagicMock()

    # speech
    m = _stub('speech')
    m.speak = MagicMock()
    m.Spri = MagicMock()
    m.Spri.NOW = 'NOW'

    # wx — only CallLater / CallAfter are used
    m = _stub('wx')
    m.CallLater = MagicMock(return_value=MagicMock())
    m.CallAfter = MagicMock()

    # api — NVDA object focus API
    m = _stub('api')
    m.getForegroundObject = MagicMock(return_value=None)

    # NVDAObjects (imported at module level in original; unused after cleanup
    # but kept in case of import-time side effects from other addons)
    _stub('NVDAObjects')
    _stub('NVDAObjects.IAccessible')


_install_stubs()

# ---------------------------------------------------------------------------
# Now it is safe to import from our package.
# ---------------------------------------------------------------------------
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture()
def app_module():
    """Return a live AppModule instance with Win32 and wx calls stubbed out."""
    with patch('ctypes.windll') as mock_windll, \
         patch('wx.CallLater', return_value=MagicMock()) as _mock_timer, \
         patch('wx.CallAfter') as _mock_after:
        mock_windll.user32.SetWinEventHook.return_value = 0xDEAD
        mock_windll.user32.UnhookWinEvent.return_value = True

        # Import here so stubs are in place
        from discord import AppModule
        instance = AppModule()
        yield instance

        # Clean up so terminate() doesn't explode on real ctypes calls
        instance._terminated = True
        instance._hook = None
        instance._pollTimer = None
