"""NVDA AppModule announcing new Discord messages from structural UIA snapshots."""

from __future__ import annotations

import contextlib
import hashlib
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import addonHandler
import appModuleHandler
import core
import ui
import UIAHandler
from logHandler import log
from scriptHandler import script

addonHandler.initTranslation()
# initTranslation binds these into this module's globals at run time.
_: Callable[[str], str]
ngettext: Callable[[str, str, int], str]

# UI Automation constants from UIAutomationClient.h.
_UIA_ControlTypePropertyId = 30003
_UIA_NamePropertyId = 30005
_UIA_AutomationIdPropertyId = 30011
_UIA_IsOffscreenPropertyId = 30022
_UIA_ValueValuePropertyId = 30045
_UIA_AriaRolePropertyId = 30101
_UIA_DocumentControlTypeId = 50030
_UIA_ListControlTypeId = 50008
_UIA_ListItemControlTypeId = 50007
_UIA_TreeScope_Descendants = 4
_UIA_PropertyConditionFlags_IgnoreCase = 1

# Discord labels the parts of a message with stable automation IDs of the form
# "message-<part>-<message id>". They are identifiers rather than presentation
# text, so they hold across locales and across Discord's own restyling.
_AUTHOR_ID_PREFIX = "message-username-"
# The body a user typed, and the embeds and attachments hanging off it. Both are
# message content; only the timestamp region sits outside them.
_CONTENT_ID_PREFIXES = ("message-content-", "message-accessories-")
_TIMESTAMP_ID_PREFIX = "message-timestamp-"
# Each message list item is "chat-messages-<channel id>-<message id>". Message
# IDs are Discord snowflakes: the creation time in milliseconds since the start
# of 2015, shifted left 22 bits. A message Discord re-renders keeps its ID.
_MESSAGE_ITEM_ID = re.compile(r"chat-messages-(\d+)-(\d+)")
_DISCORD_EPOCH_MS = 1_420_070_400_000
_SNOWFLAKE_TIME_SHIFT = 22
# A message whose ID dates it further back than this is never announced as new,
# whatever scrolled into view: history reached by scrolling, by a jump link, or
# after the add-on forgot the channel.
_NEW_MESSAGE_MAX_AGE_SECONDS = 60
# Every poll re-checks messages dated this close to the newest one seen. Discord
# can insert a message just above the newest one, and a message the user is
# still sending carries a client-made ID that may run ahead of Discord's clock.
_RECHECK_WINDOW_SECONDS = 30

_POLL_INTERVAL_MS = 500
# A failed discovery searches the whole Discord window. Retrying that twice a
# second on a page with no message list stalls NVDA, so each consecutive failure
# doubles the wait, from one poll interval up to this cap. The first retry is
# still immediate, because a channel that is still rendering resolves quickly.
_DISCOVERY_RETRY_MAX_SECONDS = 4.0
_DISCORD_HOSTS = frozenset({"discord.com", "ptb.discord.com", "canary.discord.com"})


MessageIdentity = tuple[str | int, ...]
# (identity, fingerprint, spoken text, author of the run the message belongs to)
_Attributed = tuple["MessageIdentity | None", str, str, str]


def _messageId(identity: MessageIdentity | None) -> int | None:
	"""Return the Discord message ID an identity carries, if it carries one."""
	if identity is not None and identity[0] == "message" and isinstance(identity[1], int):
		return identity[1]
	return None


def _snowflakeAt(unix_seconds: float) -> int:
	"""Return the smallest Discord ID a message created at this time could have."""
	return max(0, int(unix_seconds * 1000) - _DISCORD_EPOCH_MS) << _SNOWFLAKE_TIME_SHIFT


_RECHECK_WINDOW_IDS = (_RECHECK_WINDOW_SECONDS * 1000) << _SNOWFLAKE_TIME_SHIFT


@dataclass(frozen=True)
class MessageEntry:
	"""One visible Discord message and its stable identity."""

	identity: MessageIdentity
	text: str
	# Author of the grouped run this message belongs to, so a message read on a
	# later poll can continue the run from exactly where it sits.
	author: str = field(default="", compare=False)


@dataclass(frozen=True)
class ChannelSnapshot:
	"""Bounded ordered view of messages in one Discord channel."""

	channel_id: str
	messages: tuple[MessageEntry, ...]


@dataclass
class _ChannelMarks:
	"""Discord message IDs already seen in one channel, kept apart from snapshots.

	Snapshots are evicted with the channels they describe; these outlive them,
	so a channel the user comes back to still knows what it has presented.
	"""

	high_water: int
	seen: dict[int, None] = field(default_factory=dict)


@dataclass(frozen=True)
class _RawMessage:
	"""One message list item as read, before authors are carried across a run."""

	identity: MessageIdentity | None
	author: str
	text: str
	composed: bool


@dataclass(frozen=True)
class _CachedItem:
	"""A parsed message list item and the list item Name it was parsed under.

	The Name is a change detector only and is never announced: Chromium builds
	it from every descendant, so it changes whenever an edit, a late embed, or a
	header Discord adds after a deletion changes what the item would read as.
	"""

	name: str
	message: _RawMessage


@dataclass
class _ArticleScan:
	"""Mutable accumulator for one bounded walk of a message article subtree."""

	author: str = ""
	parts: list[str] = field(default_factory=list)
	budget: int = 400


class AppModule(appModuleHandler.AppModule):
	"""Poll Discord's active channel and present new messages once."""

	# Translators: The category of this add-on's commands in the Input Gestures dialog.
	scriptCategory = _("Discord Messages Reader")

	MAX_SNAPSHOT_MESSAGES = 100
	MAX_CHANNEL_SNAPSHOTS = 8
	MAX_BURST_MESSAGES = 10
	MAX_MESSAGE_CHARS = 500
	MAX_ANNOUNCEMENT_CHARS = 1000
	MAX_ARTICLE_DEPTH = 12
	MAX_ARTICLE_SIBLINGS = 30
	MAX_CACHED_ITEMS = 300
	MAX_SEEN_PER_CHANNEL = 1000
	MAX_MARKED_CHANNELS = 64

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
		self._lastPollError: str | None = None
		self._discoveryRetryAt = 0.0
		self._discoveryFailures = 0
		self._propertyReadFailures = 0
		# Message list items already read, keyed by UIA runtime ID. None marks a
		# child that is not a message. Reading one article costs dozens of
		# cross-process calls, so each list item is read once while it is unchanged.
		self._itemCache: dict[MessageIdentity, _CachedItem | None] = {}
		self._channelMarks: dict[str, _ChannelMarks] = {}
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
		try:
			self._uiaRead()
		except Exception as e:
			# Rescheduling must survive any failure. Without the finally, one escaped
			# exception stops the timer for good and the add-on goes silent until
			# NVDA restarts, with nothing to tell the user it has stopped.
			kind = type(e).__name__
			if kind != self._lastPollError:
				self._lastPollError = kind
				log.warning(f"DiscordMessages: poll failed ({kind})")
		else:
			self._lastPollError = None
		finally:
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
		# Sleep mode only gates scripts and focus events, so a timer must honour
		# it itself, or Discord would keep talking while NVDA sleeps there.
		if not is_foreground or not self._announceEnabled or self.sleepMode:
			self._markBaselineRequired()
			return

		snapshot = self._getSnapshotViaUIA(foreground)
		if snapshot is None:
			self._markBaselineRequired()
			return
		self._processSnapshot(snapshot)

	def _getSnapshotViaUIA(
		self,
		foreground: Any,
		history: int | None = None,
	) -> ChannelSnapshot | None:
		"""Return active channel URL and ordered list items below its main landmark.

		Polling reads incrementally: it walks back from the newest list item and
		stops at the newest message it already knows, reusing that channel's
		stored snapshot for everything above. `history` instead reads only that
		many newest messages, plus whatever lies between them and their run's
		author, and bypasses the discovery retry delay because the user asked.
		"""
		try:
			# NVDA sets the handler to None when UIA is not initialised.
			uia = getattr(UIAHandler.handler, "clientObject", None)
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
				if history is None and time.monotonic() < self._discoveryRetryAt:
					return None
				root = uia.ElementFromHandle(window_handle)
				if not root:
					return self._discoveryFailed("no-uia-root")
				document_condition = uia.CreatePropertyCondition(
					_UIA_ControlTypePropertyId,
					_UIA_DocumentControlTypeId,
				)
				# Discord's own document comes first in tree order, so FindFirst
				# usually finds it at a quarter of the cost of collecting them all.
				document = root.FindFirst(_UIA_TreeScope_Descendants, document_condition)
				if not document:
					return self._discoveryFailed("no-documents")
				value = self._getElementProperty(document, _UIA_ValueValuePropertyId, "CurrentValue")
				channel_id = self._channelIdentity(value)
				if channel_id is None and not self._isDiscordPage(value):
					documents = root.FindAll(_UIA_TreeScope_Descendants, document_condition)
					if not documents:
						return self._discoveryFailed("no-documents")
					document, channel_id = self._findChannelDocument(documents)
				self._channelRoot = root if document is not None else None
				self._channelDocument = document
				self._channelDocumentWindowHandle = window_handle if document is not None else None
				if document is None:
					return self._discoveryFailed("no-channel-document")
			if channel_id is None:
				# Discord's own document on a page without a channel, such as Friends
				# or settings. It stays cached, so no window search runs until the
				# user opens a channel and its Value changes.
				self._noteDiscoveryState("no-channel-document")
				return None

			message_list = self._getMessageList(uia, root, history is not None)
			if message_list is None:
				self._noteDiscoveryState("no-message-list")
				return None
			snapshot = self._readSnapshot(uia.RawViewWalker, message_list, channel_id, history)
			self._discoveryFailures = 0
			if snapshot is None:
				# The list holds another channel's messages: the user switched
				# channel between reading the URL and walking the list.
				self._noteDiscoveryState("foreign-channel")
				return None
			self._noteDiscoveryState("ok")
			return snapshot
		except Exception as e:
			self._invalidateChannelDocument()
			self._delayDiscovery()
			self._noteSnapshotFailure(type(e).__name__)
			return None

	def _readSnapshot(
		self,
		walker: Any,
		message_list: Any,
		channel_id: str,
		history: int | None,
	) -> ChannelSnapshot | None:
		"""Read the window, or only what changed since the stored snapshot.

		Returns None when the list holds another channel's messages.
		"""
		if history is not None:
			raw, _stopped = self._walkMessages(walker, message_list, want=history)
			return self._composeSnapshot(channel_id, raw)
		marks = self._channelMarks.get(channel_id)
		floor = self._recheckFloor(marks) if marks is not None else None
		# Full reads during polling only ever diff or baseline, so history below
		# the floor is recorded by identity and not read.
		parse_above = floor if floor is not None else _snowflakeAt(time.time() - _NEW_MESSAGE_MAX_AGE_SECONDS)
		previous = self._incrementalBase(channel_id)
		if previous is None:
			raw, _stopped = self._walkMessages(walker, message_list, parse_above=parse_above)
			return self._composeSnapshot(channel_id, raw)
		tail = previous.messages[-1].identity

		def is_known(identity: MessageIdentity | None) -> bool:
			if floor is None:
				return identity == tail
			message_id = _messageId(identity)
			return message_id is not None and message_id <= floor

		raw, stopped = self._walkMessages(walker, message_list, stop=is_known)
		known = [entry.identity for entry in previous.messages]
		if stopped is None:
			# Nothing old enough to stop at was reached, so the whole window was read.
			return self._composeSnapshot(channel_id, raw)
		if stopped not in known or any(entry.identity is None for entry in raw):
			# The walk stopped at a message the stored snapshot does not hold, such
			# as one scrolled back into view, so there is nothing to extend. Text
			# fingerprints count occurrences across the whole window, so they
			# cannot be appended to a stored one either. Read it all.
			raw, _stopped = self._walkMessages(walker, message_list, parse_above=parse_above)
			return self._composeSnapshot(channel_id, raw)
		# Everything after the stop point was just read again, so stored entries
		# there that were not seen have gone: deleted, or a pending message
		# Discord replaced. Their run continues from the stop point itself.
		kept = previous.messages[: known.index(stopped) + 1]
		if not kept[-1].text and raw and not raw[0].author:
			# A grouped message continues a run whose stop point is history
			# recorded by identity alone, so its author is unknown. A full read
			# reaches back to it. A quiet poll, or one whose first new message
			# opens its own run, needs no author and stays cheap.
			raw, _stopped = self._walkMessages(walker, message_list, parse_above=parse_above)
			return self._composeSnapshot(channel_id, raw)
		added =self._identifyMessages(self._attributeGroupedMessages(raw, kept[-1].author))
		return self._checkedSnapshot(channel_id, (*kept, *added)[-self.MAX_SNAPSHOT_MESSAGES :])

	def _composeSnapshot(self, channel_id: str, raw: list[_RawMessage]) -> ChannelSnapshot | None:
		return self._checkedSnapshot(channel_id, self._identifyMessages(self._attributeGroupedMessages(raw)))

	@staticmethod
	def _checkedSnapshot(channel_id: str, messages: tuple[MessageEntry, ...]) -> ChannelSnapshot | None:
		"""Return the snapshot, or None if any message belongs to another channel."""
		channel = channel_id.rsplit("/", 1)[-1]
		for message in messages:
			if message.identity[0] == "message" and message.identity[2] != channel:
				return None
		return ChannelSnapshot(channel_id, messages)

	def _recheckFloor(self, marks: _ChannelMarks) -> int:
		"""Return the message ID at or below which nothing can be new."""
		return max(
			marks.high_water - _RECHECK_WINDOW_IDS,
			_snowflakeAt(time.time() - _NEW_MESSAGE_MAX_AGE_SECONDS),
		)

	def _incrementalBase(self, channel_id: str) -> ChannelSnapshot | None:
		"""Return the stored snapshot a poll may extend, or None to read in full.

		A baseline always reads the whole window, so a stored snapshot only seeds
		polls that will be diffed against it. The walk must be able to recognise
		where known messages begin without reading text: by Discord message ID,
		or else by the tail's runtime ID.
		"""
		if self._needsBaseline or self._currentChannelId != channel_id:
			return None
		previous = self._channelSnapshots.get(channel_id)
		if previous is None or not previous.messages:
			return None
		if channel_id not in self._channelMarks and previous.messages[-1].identity[0] != "runtime":
			return None
		return previous

	def _delayDiscovery(self) -> None:
		delay = min(_POLL_INTERVAL_MS / 1000 * 2**self._discoveryFailures, _DISCOVERY_RETRY_MAX_SECONDS)
		self._discoveryFailures += 1
		self._discoveryRetryAt = time.monotonic() + delay

	def _noteDiscoveryState(self, state: str) -> None:
		"""Log structural discovery state only when it changes.

		Polling runs twice a second, so unchanged states must stay silent. The
		state name is a fixed label; no Discord content is ever logged.
		"""
		if state != self._lastDiscoveryState:
			self._lastDiscoveryState = state
			log.debug("DiscordMessages: discovery %s", state)

	def _noteSnapshotFailure(self, kind: str) -> None:
		"""Warn once per distinct failure rather than twice a second forever.

		Shares the discovery-state gate, so a failure that clears and returns is
		reported again instead of being suppressed for the session.
		"""
		state = f"error-{kind}"
		if state != self._lastDiscoveryState:
			self._lastDiscoveryState = state
			log.warning(f"DiscordMessages: snapshot read failed ({kind})")

	def _discoveryFailed(self, state: str) -> ChannelSnapshot | None:
		"""Record why a window search found nothing, delay the next one, and yield no snapshot."""
		self._delayDiscovery()
		self._noteDiscoveryState(state)
		return None

	def _invalidateChannelDocument(self) -> None:
		self._channelRoot = None
		self._channelDocument = None
		self._messageList = None
		self._channelDocumentWindowHandle = None
		self._itemCache.clear()
		self._markBaselineRequired()

	def _getCachedChannelDocument(self) -> tuple[Any | None, str | None]:
		"""Return a live cached document, invalidating detached or non-Discord nodes.

		Discord's document on a page without a channel stays cached with no
		channel identity: Discord is a single-page app, so the same document
		reports the channel URL once the user opens one.
		"""
		if self._channelDocument is None:
			return None, None
		try:
			value = self._channelDocument.GetCurrentPropertyValue(_UIA_ValueValuePropertyId)
		except Exception:
			self._invalidateChannelDocument()
			return None, None
		channel_id = self._channelIdentity(value)
		if channel_id is not None or self._isDiscordPage(value):
			return self._channelDocument, channel_id
		self._invalidateChannelDocument()
		return None, None

	def _findChannelDocument(self, documents: Any) -> tuple[Any | None, str | None]:
		"""Return the channel document, else Discord's document with no channel."""
		discord_page = None
		for index in range(documents.Length):
			document = documents.GetElement(index)
			value = self._getElementProperty(document, _UIA_ValueValuePropertyId, "CurrentValue")
			channel_id = self._channelIdentity(value)
			if channel_id is not None:
				return document, channel_id
			if discord_page is None and self._isDiscordPage(value):
				discord_page = document
		return discord_page, None

	def _getMessageList(self, uia: Any, root: Any, bypass_delay: bool = False) -> Any | None:
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

		if not bypass_delay and time.monotonic() < self._discoveryRetryAt:
			return None
		condition = uia.CreatePropertyCondition(
			_UIA_ControlTypePropertyId,
			_UIA_ListControlTypeId,
		)
		# The first list inside Discord's main landmark. A landmark role is an
		# ARIA identifier, not presentation text, so it holds across locales.
		main = root.FindFirst(
			_UIA_TreeScope_Descendants,
			uia.CreatePropertyConditionEx(_UIA_AriaRolePropertyId, "main", _UIA_PropertyConditionFlags_IgnoreCase),
		)
		message_list = main.FindFirst(_UIA_TreeScope_Descendants, condition) if main else None
		if message_list:
			self._messageList = message_list
			return message_list
		self._delayDiscovery()
		return None

	def _walkMessages(
		self,
		walker: Any,
		message_list: Any,
		stop: Callable[[MessageIdentity | None], bool] | None = None,
		want: int | None = None,
		parse_above: int | None = None,
	) -> tuple[list[_RawMessage], MessageIdentity | None]:
		"""Read message list items newest first, returning them in document order.

		The walk ends at the first item `stop` accepts, a message already known,
		without reading it, and returns that item's identity. With `want`, the
		walk ends once that many messages are read and the oldest of them names
		its author, since that author is all attribution needs from further up.

		With `parse_above`, a message whose ID is at or below it is recorded by
		identity alone when the message just below it opens its own run, so no
		message read here needs its author. Reading an article costs several
		milliseconds, and only recent messages can ever be announced, so a
		baseline need not read history it will never present.
		"""
		child = walker.GetLastChildElement(message_list)
		collected: list[_RawMessage] = []
		need_author = True
		iterations = 0
		while (
			child
			and iterations < self.MAX_SNAPSHOT_MESSAGES * 4
			and len(collected) < self.MAX_SNAPSHOT_MESSAGES
		):
			iterations += 1
			identity = self._itemIdentity(child)
			if stop is not None and stop(identity):
				collected.reverse()
				return collected, identity
			message_id = _messageId(identity)
			if parse_above is not None and not need_author and message_id is not None and message_id <= parse_above:
				raw: _RawMessage | None = _RawMessage(identity, "", "", False)
			else:
				raw = self._readListItem(walker, child, identity)
			if raw is not None:
				collected.append(raw)
				if raw.text:
					need_author = not raw.author
				if want is not None and len(collected) >= want and raw.author:
					break
			child = walker.GetPreviousSiblingElement(child)
		collected.reverse()
		return collected, None

	def _readListItem(
		self,
		walker: Any,
		element: Any,
		identity: MessageIdentity | None,
	) -> _RawMessage | None:
		"""Return one list item as a message, or None for anything else.

		A cached message is reused only while the list item Name is unchanged.
		Nothing is cached from a read that lost a property, nor from an item that
		read as empty, because Discord can insert a list item before filling in
		its content: either would hide the message for as long as it stayed cached.
		"""
		failures = self._propertyReadFailures
		cached = self._itemCache.get(identity) if identity is not None else None
		if cached is None and identity in self._itemCache:
			return None
		name = ""
		if identity is not None:
			value = self._getElementProperty(element, _UIA_NamePropertyId, "CurrentName")
			name = value if isinstance(value, str) else ""
		if cached is not None and name and name == cached.name:
			return cached.message

		control_type = self._getElementProperty(
			element,
			_UIA_ControlTypePropertyId,
			"CurrentControlType",
		)
		if control_type != _UIA_ListItemControlTypeId:
			if identity is not None and self._propertyReadFailures == failures:
				self._cacheItem(identity, None)
			return None
		parts = self._messageParts(walker, element)
		if not parts.text:
			return None
		raw = _RawMessage(identity, parts.author, parts.text, parts.composed)
		if identity is not None and name and self._propertyReadFailures == failures:
			self._cacheItem(identity, _CachedItem(name, raw))
		return raw

	def _cacheItem(self, identity: MessageIdentity, item: _CachedItem | None) -> None:
		self._itemCache.pop(identity, None)
		self._itemCache[identity] = item
		while len(self._itemCache) > self.MAX_CACHED_ITEMS:
			del self._itemCache[next(iter(self._itemCache))]

	def _attributeGroupedMessages(
		self,
		entries: list[_RawMessage],
		initial_author: str = "",
	) -> list[_Attributed]:
		"""Name each message, carrying an author across a grouped run.

		Discord omits the header on consecutive messages from one author, so those
		articles carry no author element at all. The author is whoever last posted,
		which is exactly what Discord shows visually. A run whose first author sits
		above the snapshot window stays unattributed rather than guessing.

		An author found on a message always updates the run, even when that message
		fell back to a raw Name. Dropping it there would leave the *next* grouped
		message wearing the previous speaker's name, which is far worse than saying
		nothing. Fallback text is never prefixed, because Discord's own summary
		already opens with the author.

		Returns (identity, fingerprint, spoken, run author) per message. The
		fingerprint omits the author prefix so that identity stays stable when the
		message that opened a run scrolls out of the snapshot window.

		`initial_author` continues a run from messages read on an earlier poll.
		"""
		attributed: list[_Attributed] = []
		current_author = initial_author
		for entry in entries:
			if entry.author:
				current_author = entry.author
			spoken = entry.text
			if entry.composed and current_author:
				spoken = f"{current_author}, {entry.text}"
			attributed.append((entry.identity, entry.text, spoken, current_author))
		return attributed

	def _messageParts(self, walker: Any, element: Any) -> _RawMessage:
		"""Return the author and spoken text for one message list item.

		Neither the list item Name nor the article Name is usable directly: both
		concatenate every descendant, so they carry the hover toolbar, reaction
		labels, embed chrome ("Remove all embeds", "Play", "Open Link") and a
		duplicated absolute timestamp. Composing from the article's own labelled
		parts drops all of that without inspecting any presentation text.

		A message with no labelled parts - an image, sticker or file post - still
		reports its author, so the grouped run that follows is attributed correctly.
		"""
		article = self._articleElement(walker, element)
		author = ""
		if article is not None:
			author, parts = self._articleParts(walker, article)
			if parts:
				return _RawMessage(None, author, ", ".join(parts), True)
			fallback = self._getElementProperty(article, _UIA_NamePropertyId, "CurrentName")
			if isinstance(fallback, str) and fallback:
				return _RawMessage(None, author, fallback, False)
		text = self._getElementProperty(element, _UIA_NamePropertyId, "CurrentName")
		if isinstance(text, str) and text:
			return _RawMessage(None, author, text, False)
		return _RawMessage(None, author, self._lastNamedChild(walker, element), False)

	def _articleElement(self, walker: Any, element: Any) -> Any | None:
		"""Return the article child Discord builds for one message list item."""
		child = walker.GetFirstChildElement(element)
		for _ in range(self.MAX_ARTICLE_SIBLINGS):
			if not child:
				break
			role = self._getElementProperty(child, _UIA_AriaRolePropertyId, "CurrentAriaRole")
			if isinstance(role, str) and role.casefold() == "article":
				return child
			child = walker.GetNextSiblingElement(child)
		return None

	def _articleParts(self, walker: Any, article: Any) -> tuple[str, list[str]]:
		"""Walk one article subtree, returning its author and its spoken fragments.

		Three structural rules do all the work, none of them reading presentation
		text. The timestamp subtree is skipped by automation ID. The long-form date
		Discord duplicates for tooltips is marked offscreen, so it is skipped as
		hidden. Everything spoken comes from `description` elements, which is what
		separates content from chrome: the embed title, channel and body text each
		carry one, while "Remove all embeds", "Play", "Image" and "Open Link" are
		bare buttons and images that carry none.
		"""
		scan = _ArticleScan()
		self._scanArticle(walker, article, scan, 0)
		return scan.author, scan.parts

	def _scanArticle(
		self,
		walker: Any,
		element: Any,
		scan: _ArticleScan,
		depth: int,
		in_content: bool = False,
	) -> None:
		if not element or depth > self.MAX_ARTICLE_DEPTH or scan.budget <= 0:
			return
		scan.budget -= 1

		automation_id = self._getElementProperty(
			element,
			_UIA_AutomationIdPropertyId,
			"CurrentAutomationId",
		)
		if isinstance(automation_id, str):
			if automation_id.startswith(_TIMESTAMP_ID_PREFIX):
				return
			if automation_id.startswith(_AUTHOR_ID_PREFIX):
				if not scan.author:
					scan.author = self._firstNamedDescendant(walker, element)
				return
			if automation_id.startswith(_CONTENT_ID_PREFIXES):
				in_content = True

		role = self._getElementProperty(element, _UIA_AriaRolePropertyId, "CurrentAriaRole")
		if isinstance(role, str) and role.casefold() == "description":
			# Hidden text is skipped only outside Discord's labelled content regions.
			# Inside them, offscreen means nothing useful: Chromium marks an entire
			# message tree offscreen whenever the window is not the visible one, so
			# trusting it there drops real content. Outside them it means what we
			# want, because the only thing there is the visually hidden long-form
			# date Discord duplicates for tooltips.
			if not in_content and self._isOffscreen(element):
				return
			name = self._getElementProperty(element, _UIA_NamePropertyId, "CurrentName")
			if isinstance(name, str) and name.strip():
				scan.parts.append(name.strip())
			return

		child = walker.GetFirstChildElement(element)
		for _ in range(self.MAX_ARTICLE_SIBLINGS):
			if not child:
				return
			self._scanArticle(walker, child, scan, depth + 1, in_content)
			child = walker.GetNextSiblingElement(child)

	def _isOffscreen(self, element: Any) -> bool:
		return (
			self._getElementProperty(
				element,
				_UIA_IsOffscreenPropertyId,
				"CurrentIsOffscreen",
			)
			is True
		)

	def _firstNamedDescendant(self, walker: Any, element: Any, depth: int = 0) -> str:
		"""Return the first non-empty Name at or below an element."""
		if not element or depth > self.MAX_ARTICLE_DEPTH:
			return ""
		name = self._getElementProperty(element, _UIA_NamePropertyId, "CurrentName")
		if isinstance(name, str) and name.strip():
			return name.strip()
		child = walker.GetFirstChildElement(element)
		for _ in range(self.MAX_ARTICLE_SIBLINGS):
			if not child:
				break
			found = self._firstNamedDescendant(walker, child, depth + 1)
			if found:
				return found
			child = walker.GetNextSiblingElement(child)
		return ""

	def _lastNamedChild(self, walker: Any, element: Any) -> str:
		child = walker.GetLastChildElement(element)
		for _ in range(self.MAX_ARTICLE_SIBLINGS):
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
		if parsed.scheme.lower() != "https" or host not in _DISCORD_HOSTS:
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
	def _isDiscordPage(value: Any) -> bool:
		"""Return whether a document Value is any page of the Discord app."""
		if not isinstance(value, str):
			return False
		try:
			parsed = urlsplit(value)
		except ValueError:
			return False
		return parsed.scheme.lower() == "https" and parsed.netloc.lower() in _DISCORD_HOSTS

	def _getElementProperty(self, element: Any, property_id: int, fallback_attribute: str) -> Any:
		try:
			return element.GetCurrentPropertyValue(property_id)
		except Exception:
			# A detached element raises COMError from the property getter itself,
			# which would abort the whole snapshot and turn the next poll into a
			# silent baseline. The failure is counted instead, so a read that
			# lost a property is never cached as if it were complete.
			try:
				return getattr(element, fallback_attribute)
			except Exception:
				self._propertyReadFailures += 1
				return ""

	def _itemIdentity(self, element: Any) -> MessageIdentity | None:
		"""Return a list item's Discord message ID, else its UIA runtime ID.

		The message ID survives Discord re-rendering the item, which gives it a
		new runtime ID. The channel ID rides along so a list caught mid-switch
		cannot pass one channel's messages off as another's. Dividers and other
		non-message children have no message ID and fall back to their runtime ID.
		"""
		automation_id = self._getElementProperty(element, _UIA_AutomationIdPropertyId, "CurrentAutomationId")
		if isinstance(automation_id, str):
			match = _MESSAGE_ITEM_ID.fullmatch(automation_id)
			if match:
				return ("message", int(match.group(2)), match.group(1))
		return self._runtimeIdentity(element)

	@staticmethod
	def _runtimeIdentity(element: Any) -> MessageIdentity | None:
		try:
			runtime_id = tuple(int(part) for part in element.GetRuntimeId())
		except Exception:
			return None
		return ("runtime", *runtime_id) if runtime_id else None

	def _identifyMessages(
		self,
		raw_entries: Sequence[tuple[MessageIdentity | None, str, str] | _Attributed],
	) -> tuple[MessageEntry, ...]:
		"""Prefer UIA runtime IDs; use conservative occurrence IDs when unavailable.

		Exact duplicate replacements at the bounded-window edge are indistinguishable
		without runtime IDs. Reusing their occurrence IDs avoids replaying old content.

		Entries arrive as (identity, fingerprint, spoken[, run author]). The
		fingerprint carries no author prefix, so identity does not change when the
		message that opened a grouped run scrolls out of the window and its
		continuations lose the prefix.
		"""
		occurrences: dict[str, int] = {}
		messages: list[MessageEntry] = []
		for runtime_id, fingerprint, spoken, *run_author in raw_entries:
			text = self._sanitizeText(spoken)
			if not text and _messageId(runtime_id) is None:
				# An empty message ID entry is history recorded by identity alone.
				continue
			if runtime_id is None:
				stable = self._sanitizeText(fingerprint) or text
				digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()
				occurrence = occurrences.get(digest, 0)
				occurrences[digest] = occurrence + 1
				identity: MessageIdentity = ("text", digest, occurrence)
			else:
				identity = runtime_id
			messages.append(MessageEntry(identity, text, run_author[0] if run_author else ""))
		return tuple(messages)

	def _markBaselineRequired(self) -> None:
		self._needsBaseline = True

	def _processSnapshot(self, snapshot: ChannelSnapshot) -> None:
		"""Store snapshot and announce only messages new to the active channel."""
		channel_id = snapshot.channel_id
		previous = self._channelSnapshots.get(channel_id)
		is_baseline = self._needsBaseline or self._currentChannelId != channel_id or previous is None
		added: tuple[MessageEntry, ...] | None = None
		if not is_baseline and previous is not None:
			marks = self._channelMarks.get(channel_id)
			if marks is not None and any(_messageId(message.identity) for message in snapshot.messages):
				added = self._newMessages(previous.messages, marks, snapshot.messages)
			else:
				added = self._orderedAdditions(previous.messages, snapshot.messages)
		self._recordMarks(channel_id, snapshot.messages)
		self._rememberSnapshot(snapshot)
		self._currentChannelId = channel_id
		self._needsBaseline = False
		if is_baseline:
			log.debug(
				"DiscordMessages: baseline channel=%s messages=%d",
				self._identityForLog(channel_id),
				len(snapshot.messages),
			)
			return
		if added is None:
			log.debug(
				"DiscordMessages: recovery baseline channel=%s messages=%d",
				self._identityForLog(channel_id),
				len(snapshot.messages),
			)
			return
		if not added:
			return
		log.debug(
			"DiscordMessages: snapshot channel=%s messages=%d added=%d",
			self._identityForLog(channel_id),
			len(snapshot.messages),
			len(added),
		)
		self._presentMessages(added)

	def _newMessages(
		self,
		previous: tuple[MessageEntry, ...],
		marks: _ChannelMarks,
		current: tuple[MessageEntry, ...],
	) -> tuple[MessageEntry, ...]:
		"""Return messages never seen before that are too recent to be history.

		Message IDs carry their creation time, so a message the user scrolls back
		to, opens by a jump link, or that Discord loads late is recognised as old
		without needing to have seen it. Only messages above the recheck floor
		are candidates, and of those only ones never seen.

		A message Discord is still sending carries a client-made ID, then is
		replaced by a new list item with the real ID. The replacement is
		recognised as a seen message that vanished while an unseen one with the
		same text appeared, and is not announced a second time.
		"""
		floor = self._recheckFloor(marks)
		present = {message.identity for message in current}
		vanished = Counter(
			message.text
			for message in previous
			if (_messageId(message.identity) or 0) > floor and message.identity not in present
		)
		added: list[MessageEntry] = []
		for message in current:
			message_id = _messageId(message.identity)
			if message_id is None or message_id <= floor or message_id in marks.seen:
				continue
			if vanished[message.text]:
				vanished[message.text] -= 1
				continue
			added.append(message)
		return tuple(added)

	def _recordMarks(self, channel_id: str, messages: tuple[MessageEntry, ...]) -> None:
		"""Remember every message ID in the snapshot as seen in its channel."""
		message_ids = [message_id for message in messages if (message_id := _messageId(message.identity))]
		if not message_ids:
			return
		marks = self._channelMarks.pop(channel_id, None) or _ChannelMarks(max(message_ids))
		marks.high_water = max(marks.high_water, *message_ids)
		for message_id in message_ids:
			marks.seen.pop(message_id, None)
			marks.seen[message_id] = None
		while len(marks.seen) > self.MAX_SEEN_PER_CHANNEL:
			del marks.seen[next(iter(marks.seen))]
		self._channelMarks[channel_id] = marks
		while len(self._channelMarks) > self.MAX_MARKED_CHANNELS:
			del self._channelMarks[next(iter(self._channelMarks))]

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
		# Re-sanitizing is deliberate. _identifyMessages already does it for the
		# polling path, but this is the single output gate: nothing reaches speech
		# without passing a length bound and a control-character filter here.
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
			# Translators: Spoken after a burst of messages, counting those left out.
			suffix = ngettext("{count} more message", "{count} more messages", hidden).format(count=hidden)
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
		snapshot = self._getSnapshotViaUIA(foreground, history=n)
		if snapshot is None or not snapshot.messages:
			# Translators: Spoken when a history command finds no messages in the channel.
			self._messageUser(_("No messages found"))
			return
		index = len(snapshot.messages) - n
		if index < 0:
			# Translators: Spoken when the channel has fewer messages than the history command asked for.
			self._messageUser(_("Message {number} is not available").format(number=n))
			return
		text = self._sanitizeText(snapshot.messages[index].text)
		if text:
			self._messageUser(text)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=1),
		gesture="kb:alt+1",
		speakOnDemand=True,
	)
	def script_readMessage1(self, gesture: Any) -> None:
		self._readNthLastMessage(1)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=2),
		gesture="kb:alt+2",
		speakOnDemand=True,
	)
	def script_readMessage2(self, gesture: Any) -> None:
		self._readNthLastMessage(2)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=3),
		gesture="kb:alt+3",
		speakOnDemand=True,
	)
	def script_readMessage3(self, gesture: Any) -> None:
		self._readNthLastMessage(3)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=4),
		gesture="kb:alt+4",
		speakOnDemand=True,
	)
	def script_readMessage4(self, gesture: Any) -> None:
		self._readNthLastMessage(4)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=5),
		gesture="kb:alt+5",
		speakOnDemand=True,
	)
	def script_readMessage5(self, gesture: Any) -> None:
		self._readNthLastMessage(5)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=6),
		gesture="kb:alt+6",
		speakOnDemand=True,
	)
	def script_readMessage6(self, gesture: Any) -> None:
		self._readNthLastMessage(6)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=7),
		gesture="kb:alt+7",
		speakOnDemand=True,
	)
	def script_readMessage7(self, gesture: Any) -> None:
		self._readNthLastMessage(7)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=8),
		gesture="kb:alt+8",
		speakOnDemand=True,
	)
	def script_readMessage8(self, gesture: Any) -> None:
		self._readNthLastMessage(8)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=9),
		gesture="kb:alt+9",
		speakOnDemand=True,
	)
	def script_readMessage9(self, gesture: Any) -> None:
		self._readNthLastMessage(9)

	@script(
		# Translators: Input help for the command that reads one of the newest Discord messages.
		description=_("Reads message {number} counting back from the newest").format(number=10),
		gesture="kb:alt+0",
		speakOnDemand=True,
	)
	def script_readMessage10(self, gesture: Any) -> None:
		self._readNthLastMessage(10)

	@script(
		# Translators: Input help for the command that turns automatic announcements on or off.
		description=_("Turns automatic announcement of incoming Discord messages on or off"),
		gesture="kb:NVDA+alt+shift+d",
		speakOnDemand=True,
	)
	def script_toggleAnnounce(self, gesture: Any) -> None:
		self._announceEnabled = not self._announceEnabled
		self._markBaselineRequired()
		if self._announceEnabled:
			# Translators: Spoken when automatic announcements are turned on.
			self._messageUser(_("Discord announcements on"))
		else:
			# Translators: Spoken when automatic announcements are turned off.
			self._messageUser(_("Discord announcements off"))
		log.info(f"DiscordMessages: announcements toggled {'on' if self._announceEnabled else 'off'}")
