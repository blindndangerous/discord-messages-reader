"""NVDA AppModule announcing new Discord messages from structural UIA snapshots."""

from __future__ import annotations

import contextlib
import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import appModuleHandler
import core
import ui
import UIAHandler
from logHandler import log

# UI Automation constants from UIAutomationClient.h.
_UIA_ControlTypePropertyId = 30003
_UIA_NamePropertyId = 30005
_UIA_ValueValuePropertyId = 30045
_UIA_AriaRolePropertyId = 30101
_UIA_DocumentControlTypeId = 50030
_UIA_ListControlTypeId = 50008
_UIA_ListItemControlTypeId = 50007
_UIA_TreeScope_Descendants = 4

_POLL_INTERVAL_MS = 500


MessageIdentity = tuple[str | int, ...]


@dataclass(frozen=True)
class MessageEntry:
	"""One visible Discord message and its stable identity."""

	identity: MessageIdentity
	text: str


@dataclass(frozen=True)
class ChannelSnapshot:
	"""Bounded ordered view of messages in one Discord channel."""

	channel_id: str
	messages: tuple[MessageEntry, ...]


class AppModule(appModuleHandler.AppModule):
	"""Poll Discord's active channel and present new messages once."""

	scriptCategory = "Discord Messages Reader"

	MAX_SNAPSHOT_MESSAGES = 100
	MAX_CHANNEL_SNAPSHOTS = 8
	MAX_BURST_MESSAGES = 10
	MAX_MESSAGE_CHARS = 500
	MAX_ANNOUNCEMENT_CHARS = 1000

	def __init__(self, *args: Any, **kwargs: Any) -> None:
		super().__init__(*args, **kwargs)
		self._announceEnabled = True
		self._terminated = False
		self._pollTimer: Any = None
		self._channelSnapshots: dict[str, ChannelSnapshot] = {}
		self._currentChannelId: str | None = None
		self._uiaClient: Any = None
		self._channelRoot: Any = None
		self._channelDocument: Any = None
		self._messageList: Any = None
		self._channelDocumentWindowHandle: Any = None
		self._needsBaseline = True
		self._lastDiscoveryState: str | None = None
		log.info(f"DiscordMessages: loaded (PID {self.processID})")
		self._schedulePoll()

	def terminate(self) -> None:
		if self._terminated:
			return
		self._terminated = True
		if self._pollTimer is not None:
			with contextlib.suppress(Exception):
				self._pollTimer.Stop()
			self._pollTimer = None
		super().terminate()

	def _schedulePoll(self) -> None:
		"""Schedule one poll on NVDA's core queue."""
		if not self._terminated:
			self._pollTimer = core.callLater(_POLL_INTERVAL_MS, self._pollTick)

	def _pollTick(self) -> None:
		self._pollTimer = None
		if self._terminated:
			return
		self._uiaRead()
		self._schedulePoll()

	def _uiaRead(self) -> None:
		"""Read and process one foreground structural snapshot."""
		if self._terminated:
			return
		import api

		try:
			foreground = api.getForegroundObject()
			is_foreground = bool(foreground and foreground.appModule is self)
		except Exception:
			is_foreground = False
			foreground = None
		if not is_foreground or not self._announceEnabled:
			self._markBaselineRequired()
			return

		snapshot = self._getSnapshotViaUIA(foreground)
		if snapshot is None:
			self._markBaselineRequired()
			return
		self._processSnapshot(snapshot)

	def _getSnapshotViaUIA(self, foreground: Any) -> ChannelSnapshot | None:
		"""Return active channel URL and ordered list items below its main landmark."""
		try:
			uia = UIAHandler.handler.clientObject
			if not uia:
				self._uiaClient = None
				self._invalidateChannelDocument()
				return None
			window_handle = foreground.windowHandle
			if uia is not self._uiaClient:
				self._uiaClient = uia
				self._invalidateChannelDocument()
			if (
				self._channelRoot is not None
				and window_handle != self._channelDocumentWindowHandle
			):
				self._invalidateChannelDocument()

			document, channel_id = self._getCachedChannelDocument()
			root = self._channelRoot
			if document is None or root is None:
				root = uia.ElementFromHandle(window_handle)
				if not root:
					return self._discoveryFailed("no-uia-root")
				document_condition = uia.CreatePropertyCondition(
					_UIA_ControlTypePropertyId,
					_UIA_DocumentControlTypeId,
				)
				documents = root.FindAll(_UIA_TreeScope_Descendants, document_condition)
				if not documents:
					return self._discoveryFailed("no-documents")
				document, channel_id = self._findChannelDocument(documents)
				self._channelRoot = root if document is not None else None
				self._channelDocument = document
				self._channelDocumentWindowHandle = window_handle if document is not None else None
			if document is None or channel_id is None:
				return self._discoveryFailed("no-channel-document")

			message_list = self._getMessageList(uia, root)
			if message_list is None:
				return self._discoveryFailed("no-message-list")
			raw_entries = self._readMessageEntries(uia.RawViewWalker, message_list)
			self._noteDiscoveryState("ok")
			return ChannelSnapshot(channel_id, self._identifyMessages(raw_entries))
		except Exception as e:
			self._invalidateChannelDocument()
			log.warning(f"DiscordMessages: snapshot read failed ({type(e).__name__})")
			return None

	def _noteDiscoveryState(self, state: str) -> None:
		"""Log structural discovery state only when it changes.

		Polling runs twice a second, so unchanged states must stay silent. The
		state name is a fixed label; no Discord content is ever logged.
		"""
		if state != self._lastDiscoveryState:
			self._lastDiscoveryState = state
			log.debug("DiscordMessages: discovery %s", state)

	def _discoveryFailed(self, state: str) -> ChannelSnapshot | None:
		"""Record why a structural snapshot was unavailable and yield no snapshot."""
		self._noteDiscoveryState(state)
		return None

	def _invalidateChannelDocument(self) -> None:
		self._channelRoot = None
		self._channelDocument = None
		self._messageList = None
		self._channelDocumentWindowHandle = None
		self._markBaselineRequired()

	def _getCachedChannelDocument(self) -> tuple[Any | None, str | None]:
		"""Return a live cached document, invalidating detached or non-channel nodes."""
		if self._channelDocument is None:
			return None, None
		try:
			value = self._channelDocument.GetCurrentPropertyValue(_UIA_ValueValuePropertyId)
		except Exception:
			self._invalidateChannelDocument()
			return None, None
		channel_id = self._channelIdentity(value)
		if channel_id is not None:
			return self._channelDocument, channel_id
		self._invalidateChannelDocument()
		return None, None

	def _findChannelDocument(self, documents: Any) -> tuple[Any | None, str | None]:
		for index in range(documents.Length):
			document = documents.GetElement(index)
			value = self._getElementProperty(document, _UIA_ValueValuePropertyId, "CurrentValue")
			channel_id = self._channelIdentity(value)
			if channel_id is not None:
				return document, channel_id
		return None, None

	def _getMessageList(self, uia: Any, root: Any) -> Any | None:
		"""Return Discord's message list using its locale-independent main landmark."""
		if self._messageList is not None:
			control_type = self._getElementProperty(
				self._messageList,
				_UIA_ControlTypePropertyId,
				"CurrentControlType",
			)
			if control_type == _UIA_ListControlTypeId:
				return self._messageList
			self._messageList = None

		condition = uia.CreatePropertyCondition(
			_UIA_ControlTypePropertyId,
			_UIA_ListControlTypeId,
		)
		lists = root.FindAll(_UIA_TreeScope_Descendants, condition)
		if not lists:
			return None
		walker = uia.RawViewWalker
		for index in range(lists.Length):
			candidate = lists.GetElement(index)
			if self._hasAriaAncestor(walker, candidate, "main"):
				self._messageList = candidate
				return candidate
		return None

	def _hasAriaAncestor(
		self,
		walker: Any,
		element: Any,
		role: str,
		*,
		max_depth: int = 12,
	) -> bool:
		ancestor = walker.GetParentElement(element)
		for _ in range(max_depth):
			if not ancestor:
				return False
			ancestor_role = self._getElementProperty(
				ancestor,
				_UIA_AriaRolePropertyId,
				"CurrentAriaRole",
			)
			if isinstance(ancestor_role, str) and ancestor_role.casefold() == role:
				return True
			ancestor = walker.GetParentElement(ancestor)
		return False

	def _readMessageEntries(
		self,
		walker: Any,
		message_list: Any,
	) -> list[tuple[MessageIdentity | None, str]]:
		"""Read recent message list items in document order with bounded walking."""
		child = walker.GetLastChildElement(message_list)
		reversed_entries: list[tuple[MessageIdentity | None, str]] = []
		iterations = 0
		while (
			child
			and iterations < self.MAX_SNAPSHOT_MESSAGES * 4
			and len(reversed_entries) < self.MAX_SNAPSHOT_MESSAGES
		):
			iterations += 1
			control_type = self._getElementProperty(
				child,
				_UIA_ControlTypePropertyId,
				"CurrentControlType",
			)
			if control_type == _UIA_ListItemControlTypeId:
				text = self._articleText(walker, child)
				if not text:
					text = self._getElementProperty(child, _UIA_NamePropertyId, "CurrentName")
				if not isinstance(text, str) or not text:
					text = self._lastNamedChild(walker, child)
				if text:
					reversed_entries.append((self._runtimeIdentity(child), text))
			child = walker.GetPreviousSiblingElement(child)
		reversed_entries.reverse()
		return reversed_entries

	def _articleText(self, walker: Any, element: Any) -> str:
		"""Return Discord's own accessible summary for one message list item.

		The list item Name concatenates the header, a duplicated absolute
		timestamp, the body, every reaction shortcode with its "Click to react"
		label, and the hover toolbar. The article child carries the summary
		Discord builds for screen readers instead, and it still names the author
		on grouped messages where the list item Name omits it.
		"""
		child = walker.GetFirstChildElement(element)
		for _ in range(10):
			if not child:
				break
			role = self._getElementProperty(child, _UIA_AriaRolePropertyId, "CurrentAriaRole")
			if isinstance(role, str) and role.casefold() == "article":
				text = self._getElementProperty(child, _UIA_NamePropertyId, "CurrentName")
				return text if isinstance(text, str) else ""
			child = walker.GetNextSiblingElement(child)
		return ""

	def _lastNamedChild(self, walker: Any, element: Any) -> str:
		child = walker.GetLastChildElement(element)
		for _ in range(20):
			if not child:
				break
			text = self._getElementProperty(child, _UIA_NamePropertyId, "CurrentName")
			if isinstance(text, str) and text:
				return text
			child = walker.GetPreviousSiblingElement(child)
		return ""

	@staticmethod
	def _channelIdentity(value: Any) -> str | None:
		if not isinstance(value, str):
			return None
		try:
			parsed = urlsplit(value)
		except ValueError:
			return None
		host = parsed.netloc.lower()
		if parsed.scheme.lower() != "https" or host not in {
			"discord.com",
			"ptb.discord.com",
			"canary.discord.com",
		}:
			return None
		path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
		path_parts = path.split("/")
		# Discord appends a message id to the channel URL when a message is
		# focused or deep-linked. It is not part of channel identity: including
		# it would make every new message look like a channel change.
		if (
			len(path_parts) not in {4, 5}
			or path_parts[:2] != ["", "channels"]
			or (path_parts[2] != "@me" and not path_parts[2].isdigit())
			or not path_parts[3].isdigit()
			or (len(path_parts) == 5 and not path_parts[4].isdigit())
		):
			return None
		return f"https://{host}/channels/{path_parts[2]}/{path_parts[3]}"

	@staticmethod
	def _getElementProperty(element: Any, property_id: int, fallback_attribute: str) -> Any:
		try:
			return element.GetCurrentPropertyValue(property_id)
		except Exception:
			return getattr(element, fallback_attribute, "")

	@staticmethod
	def _runtimeIdentity(element: Any) -> MessageIdentity | None:
		try:
			runtime_id = tuple(int(part) for part in element.GetRuntimeId())
		except Exception:
			return None
		return ("runtime", *runtime_id) if runtime_id else None

	def _identifyMessages(
		self,
		raw_entries: list[tuple[MessageIdentity | None, str]],
	) -> tuple[MessageEntry, ...]:
		"""Prefer UIA runtime IDs; use conservative occurrence IDs when unavailable.

		Exact duplicate replacements at the bounded-window edge are indistinguishable
		without runtime IDs. Reusing their occurrence IDs avoids replaying old content.
		"""
		occurrences: dict[str, int] = {}
		messages: list[MessageEntry] = []
		for runtime_id, text in raw_entries:
			text = self._sanitizeText(text)
			if not text:
				continue
			if runtime_id is None:
				digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
				occurrence = occurrences.get(digest, 0)
				occurrences[digest] = occurrence + 1
				identity: MessageIdentity = ("text", digest, occurrence)
			else:
				identity = runtime_id
			messages.append(MessageEntry(identity, text))
		return tuple(messages)

	def _markBaselineRequired(self) -> None:
		self._needsBaseline = True

	def _processSnapshot(self, snapshot: ChannelSnapshot) -> None:
		"""Store snapshot and announce only ordered additions to active channel."""
		previous = self._channelSnapshots.get(snapshot.channel_id)
		is_baseline = self._needsBaseline or self._currentChannelId != snapshot.channel_id or previous is None
		self._rememberSnapshot(snapshot)
		self._currentChannelId = snapshot.channel_id
		self._needsBaseline = False
		if is_baseline or previous is None:
			log.debug(
				"DiscordMessages: baseline channel=%s messages=%d",
				self._identityForLog(snapshot.channel_id),
				len(snapshot.messages),
			)
			return

		added = self._orderedAdditions(previous.messages, snapshot.messages)
		if added is None:
			log.debug(
				"DiscordMessages: recovery baseline channel=%s messages=%d",
				self._identityForLog(snapshot.channel_id),
				len(snapshot.messages),
			)
			return
		if not added:
			return
		log.debug(
			"DiscordMessages: snapshot channel=%s messages=%d added=%d",
			self._identityForLog(snapshot.channel_id),
			len(snapshot.messages),
			len(added),
		)
		self._presentMessages(added)

	def _orderedAdditions(
		self,
		previous: tuple[MessageEntry, ...],
		current: tuple[MessageEntry, ...],
	) -> tuple[MessageEntry, ...] | None:
		"""Return only the suffix after the previously known tail.

		No known tail means ordering cannot be recovered safely, so the current
		snapshot becomes a silent baseline. Exact fallback duplicates that cannot be
		distinguished remain stable and silent until a known ordered suffix appears.
		"""
		if not previous and not current:
			return ()
		if not previous or not current:
			return None

		known_tail = previous[-1].identity
		matching_indices = [
			index for index, message in enumerate(current) if message.identity == known_tail
		]
		if len(matching_indices) != 1:
			return None
		return current[matching_indices[0] + 1 :]

	def _rememberSnapshot(self, snapshot: ChannelSnapshot) -> None:
		if snapshot.channel_id in self._channelSnapshots:
			del self._channelSnapshots[snapshot.channel_id]
		self._channelSnapshots[snapshot.channel_id] = snapshot
		while len(self._channelSnapshots) > self.MAX_CHANNEL_SNAPSHOTS:
			oldest_channel = next(iter(self._channelSnapshots))
			del self._channelSnapshots[oldest_channel]

	def _presentMessages(self, messages: tuple[MessageEntry, ...]) -> None:
		texts = [self._sanitizeText(message.text) for message in messages]
		texts = [text for text in texts if text]
		if not texts:
			return
		included: list[str] = []
		for text in texts[: self.MAX_BURST_MESSAGES]:
			candidate = "\n".join((*included, text))
			if len(candidate) > self.MAX_ANNOUNCEMENT_CHARS:
				break
			included.append(text)
		if not included:
			return

		hidden = len(texts) - len(included)
		output = "\n".join(included)
		if hidden:
			noun = "message" if hidden == 1 else "messages"
			suffix = f"{hidden} more {noun}"
			available = self.MAX_ANNOUNCEMENT_CHARS - len(suffix) - 1
			output = f"{output[:available]}\n{suffix}"
		self._messageUser(output)

	@staticmethod
	def _messageUser(text: str) -> None:
		try:
			ui.message(text)
		except Exception as e:
			log.warning(f"DiscordMessages: user output failed ({type(e).__name__})")

	def _sanitizeText(self, text: str) -> str:
		filtered: list[str] = []
		for character in text:
			codepoint = ord(character)
			is_bidi_formatting = (
				character in {"\u061c", "\u200e", "\u200f"}
				or 0x202A <= codepoint <= 0x202E
				or 0x2066 <= codepoint <= 0x2069
			)
			if is_bidi_formatting:
				continue
			if unicodedata.category(character) == "Cc":
				if character.isspace():
					filtered.append(" ")
				continue
			filtered.append(character)
		text = " ".join("".join(filtered).split())
		if len(text) > self.MAX_MESSAGE_CHARS:
			return text[: self.MAX_MESSAGE_CHARS - 1] + "…"
		return text

	@staticmethod
	def _identityForLog(value: str) -> str:
		return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]

	def _readNthLastMessage(self, n: int) -> None:
		"""Present Nth-last structural message (1 = most recent)."""
		import api

		try:
			foreground = api.getForegroundObject()
			if not foreground or foreground.appModule is not self:
				return
		except Exception:
			return
		snapshot = self._getSnapshotViaUIA(foreground)
		if snapshot is None or not snapshot.messages:
			self._messageUser("No messages found")
			return
		index = len(snapshot.messages) - n
		if index < 0:
			self._messageUser(f"Message {n} not available")
			return
		text = self._sanitizeText(snapshot.messages[index].text)
		if text:
			self._messageUser(text)

	def script_readMessage1(self, gesture: Any) -> None:
		"""Read the most recent message."""
		self._readNthLastMessage(1)

	def script_readMessage2(self, gesture: Any) -> None:
		"""Read the 2nd most recent message."""
		self._readNthLastMessage(2)

	def script_readMessage3(self, gesture: Any) -> None:
		"""Read the 3rd most recent message."""
		self._readNthLastMessage(3)

	def script_readMessage4(self, gesture: Any) -> None:
		"""Read the 4th most recent message."""
		self._readNthLastMessage(4)

	def script_readMessage5(self, gesture: Any) -> None:
		"""Read the 5th most recent message."""
		self._readNthLastMessage(5)

	def script_readMessage6(self, gesture: Any) -> None:
		"""Read the 6th most recent message."""
		self._readNthLastMessage(6)

	def script_readMessage7(self, gesture: Any) -> None:
		"""Read the 7th most recent message."""
		self._readNthLastMessage(7)

	def script_readMessage8(self, gesture: Any) -> None:
		"""Read the 8th most recent message."""
		self._readNthLastMessage(8)

	def script_readMessage9(self, gesture: Any) -> None:
		"""Read the 9th most recent message."""
		self._readNthLastMessage(9)

	def script_readMessage10(self, gesture: Any) -> None:
		"""Read the 10th most recent message."""
		self._readNthLastMessage(10)

	def script_toggleAnnounce(self, gesture: Any) -> None:
		"""Toggle automatic incoming message announcements."""
		self._announceEnabled = not self._announceEnabled
		self._markBaselineRequired()
		state = "on" if self._announceEnabled else "off"
		self._messageUser(f"Discord announcements {state}")
		log.info(f"DiscordMessages: announcements toggled {state}")

	__gestures = {  # noqa: RUF012 - NVDA reads this class attribute by convention.
		"kb:NVDA+alt+shift+d": "toggleAnnounce",
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
