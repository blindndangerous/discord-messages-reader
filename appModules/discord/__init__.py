"""NVDA AppModule for Discord — announces incoming chat messages.

Primary mechanism: periodic UIA polling of the message list.
Discord is a Chromium/Electron app. NVDA's browse mode (virtual buffer) reads
messages via UIA. IAccessible WinEvent hooks are unreliable because Chrome's
renderer stops publishing IAccessible events when the message list is not active.
UIA, however, always exposes the full message list regardless of focus.

We poll the UIA tree every 500 ms. When the last message in the list differs
from the last announced message, we announce it via NVDA speech.

The WinEvent hook is kept as a fast-path trigger: when it fires (e.g. from
the message list being active), it triggers an immediate UIA read instead of
waiting for the next poll cycle.
"""
import ctypes
import ctypes.wintypes
import re
import time
import wx
import appModuleHandler
from logHandler import log
import UIAHandler
import speech

EVENT_OBJECT_NAMECHANGE = 0x800C
WINEVENT_OUTOFCONTEXT   = 0x0000

_WinEventProcType = ctypes.WINFUNCTYPE(
    None,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.HWND,
    ctypes.wintypes.LONG,
    ctypes.wintypes.LONG,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
)

_STATUS_SUFFIXES = (', Online', ', Offline', ', Idle', ', Do Not Disturb', ', Streaming')

# UIA property/type constants (from UIAutomationClient.h)
_UIA_NamePropertyId        = 30005
_UIA_ControlTypePropertyId = 30003
_UIA_ListControlTypeId     = 50008
_UIA_TreeScope_Descendants = 4

# How often to poll the UIA tree for new messages (milliseconds)
_POLL_INTERVAL_MS = 500

# Pre-compiled: matches standalone timestamp strings like "9:04 AM" or "9:04"
_TIMESTAMP_RE = re.compile(r'^\d{1,2}:\d{2}\s*(AM|PM)?$', re.IGNORECASE)


class AppModule(appModuleHandler.AppModule):
    disableBrowseModeByDefault = True
    scriptCategory = "Discord Messages Reader"

    _lastText: str = ""
    _announceEnabled: bool = True
    _lastHookTime: float = 0.0   # time of last IAccessible nameChange — for valueChange suppression
    _lastUiaRead: float = 0.0    # time of last completed UIA read — for WinEvent debounce
    _discordHwnd: int = 0        # hwnd learned from first WinEvent; used for UIA root lookup
    _pollTimer = None
    _terminated: bool = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        log.info("DiscordMessages: loaded (PID %d)" % self.processID)

        # IAccessible WinEvent hook — fast-path trigger when IAccessible is active.
        # Must hold a reference to _hookProc or the GC will free the ctypes callback.
        self._hookProc = _WinEventProcType(self._winEventCallback)
        self._hook = ctypes.windll.user32.SetWinEventHook(
            EVENT_OBJECT_NAMECHANGE,
            EVENT_OBJECT_NAMECHANGE,
            None,
            self._hookProc,
            self.processID,
            0,
            WINEVENT_OUTOFCONTEXT,
        )
        if self._hook:
            log.info("DiscordMessages: WinEvent hook registered")
        else:
            log.warning("DiscordMessages: WinEvent hook FAILED")

        # Start UIA polling — primary mechanism
        self._schedulePoll()

    def terminate(self):
        self._terminated = True
        if self._pollTimer is not None:
            try:
                self._pollTimer.Stop()
            except Exception:
                pass
            self._pollTimer = None
        if getattr(self, '_hook', None):
            ctypes.windll.user32.UnhookWinEvent(self._hook)
            self._hook = None
        super().terminate()

    # ------------------------------------------------------------------ #
    # IAccessible WinEvent hook — fast-path trigger                       #
    # ------------------------------------------------------------------ #

    def _winEventCallback(self, hHook, event, hwnd, idObject, idChild, thread, time_ms):
        if not self._discordHwnd:
            self._discordHwnd = hwnd
        self._lastHookTime = time.time()
        # Debounce: skip if a UIA read ran within the last poll interval.
        # This prevents stacking up tree walks during rapid navigation.
        if time.time() - self._lastUiaRead < _POLL_INTERVAL_MS / 1000.0:
            return
        wx.CallAfter(self._uiaRead)

    # ------------------------------------------------------------------ #
    # UIA polling — primary message detection                             #
    # ------------------------------------------------------------------ #

    def _schedulePoll(self):
        if not self._terminated:
            self._pollTimer = wx.CallLater(_POLL_INTERVAL_MS, self._pollTick)

    def _pollTick(self):
        self._pollTimer = None
        if not self._terminated:
            self._uiaRead()
            self._schedulePoll()

    def _uiaRead(self):
        """Read the latest message from Discord's UIA tree; announce if new."""
        if not self._announceEnabled:
            return
        import api
        try:
            fg = api.getForegroundObject()
            if not fg or fg.appModule is not self:
                return
        except Exception:
            return
        try:
            name = self._getLatestMessageViaUIA()
            self._lastUiaRead = time.time()
            if name:
                log.debug("DiscordMessages: UIA read: %r" % name[:120])
                self._filterAndAnnounce(name)
        except Exception as e:
            log.warning("DiscordMessages: uiaRead error: %s" % e)

    def _getLatestMessageViaUIA(self):
        """Walk Discord's UIA tree and return the text of the latest message."""
        try:
            uia = UIAHandler.handler.clientObject
            if not uia:
                return None

            hwnd = self._discordHwnd
            if not hwnd:
                import api
                fg = api.getForegroundObject()
                if fg and fg.appModule is self:
                    hwnd = fg.windowHandle
                    self._discordHwnd = hwnd
            if not hwnd:
                return None

            root = uia.ElementFromHandle(hwnd)
            if not root:
                return None

            # Find all List controls then pick the one named "Messages in …".
            # Discord's sidebar also has a "Direct Messages" list — we skip it.
            condition = uia.CreatePropertyCondition(
                _UIA_ControlTypePropertyId, _UIA_ListControlTypeId
            )
            lists = root.FindAll(_UIA_TreeScope_Descendants, condition)
            if not lists or lists.Length == 0:
                return None

            msgList = None
            for i in range(lists.Length):
                elem = lists.GetElement(i)
                n = elem.GetCurrentPropertyValue(_UIA_NamePropertyId) or ""
                if "messages in" in n.lower():
                    msgList = elem
                    break

            if not msgList:
                return None

            walker = uia.RawViewWalker

            # Walk backward from the last child; message containers often have
            # an empty aggregate name — content lives in grandchildren.
            child = walker.GetLastChildElement(msgList)
            for _ in range(10):
                if not child:
                    break
                name = child.GetCurrentPropertyValue(_UIA_NamePropertyId) or ""
                if name:
                    return name
                grandchild = walker.GetLastChildElement(child)
                while grandchild:
                    gname = grandchild.GetCurrentPropertyValue(_UIA_NamePropertyId) or ""
                    if gname:
                        return gname
                    grandchild = walker.GetPreviousSiblingElement(grandchild)
                child = walker.GetPreviousSiblingElement(child)

            return None

        except Exception as e:
            log.warning("DiscordMessages: getLatestMessage error: %s" % e)
            return None

    # ------------------------------------------------------------------ #
    # Filtering and announcement                                          #
    # ------------------------------------------------------------------ #

    def _filterAndAnnounce(self, name):
        lower = name.lower()

        if any(name.endswith(s) for s in _STATUS_SUFFIXES):
            return
        if 'is typing' in lower or 'are typing' in lower:
            return

        if ' , ' in name:
            # IAccessible format: "username , body , HH:MM AM"
            parts = name.split(' , ')
            if ':' not in parts[-1]:
                return
            body = ' , '.join(parts[1:-1]).strip() if len(parts) >= 3 else ""
            if not body:
                return
            self._scheduleAnnounce(name)
            return

        # Plain-text UIA — skip timestamps and very short UI labels
        if len(name) < 3 or _TIMESTAMP_RE.match(name.strip()):
            return
        self._scheduleAnnounce(name)

    def _scheduleAnnounce(self, text):
        if text == self._lastText:
            return
        self._lastText = text
        if not self._announceEnabled:
            return
        log.debug("DiscordMessages: announcing %r" % text[:80])
        self._doAnnounce(text)

    def _doAnnounce(self, text):
        # IAccessible format → "username: body"
        if ' , ' in text:
            parts = text.split(' , ')
            formatted = (
                "%s: %s" % (parts[0], ' , '.join(parts[1:-1]))
                if len(parts) >= 3
                else parts[0]
            )
        else:
            formatted = text
        log.debug("DiscordMessages: SPEAKING %r" % formatted[:120])
        speech.speak([formatted], priority=speech.Spri.NOW)

    # ------------------------------------------------------------------ #
    # History reading — Alt+1 through Alt+0                              #
    # ------------------------------------------------------------------ #

    def _isValidMessage(self, name):
        """Return True if *name* looks like a real chat message."""
        lower = name.lower()
        if any(name.endswith(s) for s in _STATUS_SUFFIXES):
            return False
        if 'is typing' in lower or 'are typing' in lower:
            return False
        if ' , ' in name:
            parts = name.split(' , ')
            if ':' not in parts[-1]:
                return False
            body = ' , '.join(parts[1:-1]).strip() if len(parts) >= 3 else ""
            return bool(body)
        return len(name) >= 3 and not _TIMESTAMP_RE.match(name.strip())

    def _getMessagesViaUIA(self, count=10):
        """Walk the UIA tree and return up to *count* recent messages (oldest first)."""
        try:
            uia = UIAHandler.handler.clientObject
            if not uia:
                return []

            hwnd = self._discordHwnd
            if not hwnd:
                import api
                fg = api.getForegroundObject()
                if fg and fg.appModule is self:
                    hwnd = fg.windowHandle
                    self._discordHwnd = hwnd
            if not hwnd:
                return []

            root = uia.ElementFromHandle(hwnd)
            if not root:
                return []

            condition = uia.CreatePropertyCondition(
                _UIA_ControlTypePropertyId, _UIA_ListControlTypeId
            )
            lists = root.FindAll(_UIA_TreeScope_Descendants, condition)
            if not lists or lists.Length == 0:
                return []

            msgList = None
            for i in range(lists.Length):
                elem = lists.GetElement(i)
                n = elem.GetCurrentPropertyValue(_UIA_NamePropertyId) or ""
                if "messages in" in n.lower():
                    msgList = elem
                    break
            if not msgList:
                return []

            walker = uia.RawViewWalker
            candidates = []
            child = walker.GetLastChildElement(msgList)
            # Over-collect to account for non-message items (date separators, etc.)
            limit = count * 4
            iterations = 0
            while child and iterations < limit:
                iterations += 1
                name = child.GetCurrentPropertyValue(_UIA_NamePropertyId) or ""
                if name:
                    candidates.append(name)
                else:
                    grandchild = walker.GetLastChildElement(child)
                    while grandchild:
                        gname = grandchild.GetCurrentPropertyValue(_UIA_NamePropertyId) or ""
                        if gname:
                            candidates.append(gname)
                            break
                        grandchild = walker.GetPreviousSiblingElement(grandchild)
                child = walker.GetPreviousSiblingElement(child)

            messages = [m for m in candidates if self._isValidMessage(m)]
            messages = messages[:count]
            messages.reverse()  # oldest first
            return messages

        except Exception as e:
            log.warning("DiscordMessages: getMessages error: %s" % e)
            return []

    def _readNthLastMessage(self, n):
        """Speak the Nth-last message (1 = most recent, 10 = oldest of last ten)."""
        import api
        try:
            fg = api.getForegroundObject()
            if not fg or fg.appModule is not self:
                return
        except Exception:
            return
        messages = self._getMessagesViaUIA(count=10)
        if not messages:
            speech.speak(["No messages found"], priority=speech.Spri.NOW)
            return
        # messages is oldest-first; n=1 → most recent → index -1
        idx = len(messages) - n
        if idx < 0:
            speech.speak(["Message %d not available" % n], priority=speech.Spri.NOW)
            return
        self._doAnnounce(messages[idx])

    def script_readMessage1(self, gesture):
        """Read the most recent message."""
        self._readNthLastMessage(1)

    def script_readMessage2(self, gesture):
        """Read the 2nd most recent message."""
        self._readNthLastMessage(2)

    def script_readMessage3(self, gesture):
        """Read the 3rd most recent message."""
        self._readNthLastMessage(3)

    def script_readMessage4(self, gesture):
        """Read the 4th most recent message."""
        self._readNthLastMessage(4)

    def script_readMessage5(self, gesture):
        """Read the 5th most recent message."""
        self._readNthLastMessage(5)

    def script_readMessage6(self, gesture):
        """Read the 6th most recent message."""
        self._readNthLastMessage(6)

    def script_readMessage7(self, gesture):
        """Read the 7th most recent message."""
        self._readNthLastMessage(7)

    def script_readMessage8(self, gesture):
        """Read the 8th most recent message."""
        self._readNthLastMessage(8)

    def script_readMessage9(self, gesture):
        """Read the 9th most recent message."""
        self._readNthLastMessage(9)

    def script_readMessage10(self, gesture):
        """Read the 10th most recent message."""
        self._readNthLastMessage(10)

    def script_toggleAnnounce(self, gesture):
        """Toggle automatic announcement of incoming messages on or off."""
        self._announceEnabled = not self._announceEnabled
        state = "on" if self._announceEnabled else "off"
        speech.speak(["Discord announcements %s" % state], priority=speech.Spri.NOW)
        log.info("DiscordMessages: announcements toggled %s" % state)

    __gestures = {
        "kb:NVDA+shift+d": "toggleAnnounce",
        "kb:alt+1": "readMessage1",
        "kb:alt+2": "readMessage2",
        "kb:alt+3": "readMessage3",
        "kb:alt+4": "readMessage4",
        "kb:alt+5": "readMessage5",
        "kb:alt+6": "readMessage6",
        "kb:alt+7": "readMessage7",
        "kb:alt+8": "readMessage8",
        "kb:alt+9": "readMessage9",
        "kb:alt+0": "readMessage10",
    }

    # ------------------------------------------------------------------ #
    # NVDA event handlers                                                 #
    # ------------------------------------------------------------------ #

    def event_valueChange(self, obj, nextHandler):
        """Suppress Discord's edit-field clearing from cancelling our announcement."""
        if time.time() - self._lastHookTime < 2.0:
            return
        nextHandler()

    def event_UIA_liveRegionChange(self, obj, nextHandler):
        """UIA live region — fires if Discord publishes UIA live updates."""
        name = obj.name or ""
        if name and name != "(empty message)":
            lower = name.lower()
            if 'is typing' not in lower and 'are typing' not in lower:
                self._filterAndAnnounce(name)
        nextHandler()

    def event_liveRegionChange(self, obj, nextHandler):
        """IAccessible live region change — fallback."""
        name = obj.name or ""
        if name and name != "(empty message)":
            lower = name.lower()
            if 'is typing' not in lower and 'are typing' not in lower:
                self._filterAndAnnounce(name)
        nextHandler()

    def event_alert(self, obj, nextHandler):
        text = (obj.name or "") or (obj.value or "")
        if text:
            self._filterAndAnnounce(text)
        nextHandler()
