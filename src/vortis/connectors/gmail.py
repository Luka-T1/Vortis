"""Gmail connector — bulk email sync via the Gmail REST API.

Uses OAuth 2.0 tokens stored locally (see :mod:`vortis.connectors.oauth`).
All network calls are isolated in module-level functions (``_gmail_api_*``)
to make them trivially mockable in tests.
"""

from __future__ import annotations

import base64
import email.utils
import logging
import random
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Dict, Iterator, List, Optional, Tuple

import httpx

from vortis.connectors._stubs import BaseConnector, Document, SyncStatus
from vortis.connectors.google_auth import (
    GoogleAuthError,
)
from vortis.connectors.google_auth import (
    call_with_refresh as _call_with_refresh,
)
from vortis.connectors.oauth import (
    GOOGLE_ALL_SCOPES,
    build_google_auth_url,
    delete_tokens,
    load_tokens,
    refresh_google_token,
    resolve_google_credentials,
    save_tokens,
)
from vortis.core.config import DEFAULT_CONFIG_DIR
from vortis.core.registry import ConnectorRegistry
from vortis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)


_GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "gmail.json")

GmailAuthError = GoogleAuthError


def _is_rate_limited(response: httpx.Response) -> bool:
    """Distinguish Google's transient quotas from permission and daily limits."""
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    details = error.get("errors", []) if isinstance(error, dict) else []
    return isinstance(details, list) and any(
        isinstance(item, dict)
        and item.get("reason") in {"rateLimitExceeded", "userRateLimitExceeded"}
        for item in details
    )


def _gmail_get(url: str, token: str, params: Dict[str, str]) -> httpx.Response:
    """Retry idempotent Gmail reads with a bounded exponential quota backoff."""
    for attempt in range(6):
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30.0,
        )
        if not _is_rate_limited(response):
            return response
        if attempt == 5:
            raise httpx.HTTPStatusError(
                f"Gmail rate limited after 6 attempts (HTTP {response.status_code})",
                request=response.request,
                response=response,
            )
        delay = min(60.0, 2.0 ** (attempt + 1) + random.random())
        logger.info("Gmail rate limited; retrying in %.1fs", delay)
        time.sleep(delay)
    raise AssertionError("unreachable retry loop")


def _gmail_api_list_messages(
    token: str,
    *,
    page_token: Optional[str] = None,
    query: str = "",
) -> Dict[str, Any]:
    """Call the Gmail ``messages.list`` endpoint.

    Parameters
    ----------
    token:
        OAuth access token.
    page_token:
        Pagination token from a previous response's ``nextPageToken``.
    query:
        Gmail search query string (e.g. ``"is:unread"``).

    Returns
    -------
    dict
        Raw API response containing ``messages`` list and optional
        ``nextPageToken``.
    """
    params: Dict[str, str] = {}
    if page_token:
        params["pageToken"] = page_token
    if query:
        params["q"] = query

    resp = _gmail_get(f"{_GMAIL_API_BASE}/messages", token, params)
    resp.raise_for_status()
    return resp.json()


def _gmail_api_trash_message(token: str, msg_id: str) -> None:
    """Move a Gmail message to Trash via the ``messages.trash`` endpoint."""
    resp = httpx.post(
        f"{_GMAIL_API_BASE}/messages/{msg_id}/trash",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    resp.raise_for_status()


def _gmail_api_modify_message(
    token: str,
    msg_id: str,
    *,
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
) -> None:
    """Modify labels on a Gmail message via the ``messages.modify`` endpoint."""
    body: Dict[str, Any] = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels
    resp = httpx.post(
        f"{_GMAIL_API_BASE}/messages/{msg_id}/modify",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=30.0,
    )
    resp.raise_for_status()


def _gmail_api_get_message(token: str, msg_id: str) -> Dict[str, Any]:
    """Fetch a single Gmail message by ID (``full`` format).

    Parameters
    ----------
    token:
        OAuth access token.
    msg_id:
        Gmail message ID string.

    Returns
    -------
    dict
        Raw API response for the message resource.
    """
    resp = _gmail_get(f"{_GMAIL_API_BASE}/messages/{msg_id}", token, {"format": "full"})
    resp.raise_for_status()
    return resp.json()


def _extract_header(headers: List[Dict[str, str]], name: str) -> str:
    """Return the value of the first header matching *name* (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


class _HTMLTextExtractor(HTMLParser):
    """Strip HTML tags and return readable text using stdlib only.

    Skips <script>, <style>, and <head> contents entirely so CSS rules and
    JS payloads don't pollute the text. Inserts a newline at each block-level
    tag boundary so the downstream chunker still has paragraph-ish breaks
    to split on; without this, a single <div>-wrapped marketing email
    becomes one giant unsplittable chunk.
    """

    _SKIP_TAGS = {"script", "style", "head", "title", "meta", "link"}
    _BLOCK_TAGS = {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "tr",
        "td",
        "table",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "hr",
        "article",
        "section",
        "header",
        "footer",
        "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS and self._skip_depth == 0:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n[ \t]*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text. Malformed input returns best-effort output."""
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(html)
        extractor.close()
    except Exception:  # noqa: BLE001
        pass
    return extractor.get_text()


def _decode_body(payload: Dict[str, Any]) -> str:
    """Decode the message body from a Gmail payload dict.

    Multipart messages prefer text/plain. When only text/html is available
    (common for marketing emails), the HTML is stripped to plain text so
    downstream chunkers and embeddings don't ingest raw markup.
    """
    mime_type: str = payload.get("mimeType", "")

    if mime_type.startswith("multipart/"):
        parts: List[Dict[str, Any]] = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType", "").startswith("text/plain"):
                return _decode_body(part)
        for part in parts:
            if part.get("mimeType", "").startswith("text/html"):
                return _decode_body(part)
        if parts:
            return _decode_body(parts[0])
        return ""

    body_data: str = payload.get("body", {}).get("data", "")
    if not body_data:
        return ""

    padded = body_data + "=" * (-len(body_data) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""

    if mime_type.startswith("text/html"):
        return _html_to_text(decoded)
    return decoded


def _parse_date(date_str: str) -> datetime:
    """Parse an RFC 2822 email date string into a :class:`~datetime.datetime`.

    Falls back to :func:`datetime.now` if the string is unparseable.
    """
    if not date_str:
        return datetime.now()
    try:
        return email.utils.parsedate_to_datetime(date_str)
    except Exception:  # noqa: BLE001
        return datetime.now()


def _normalize_addresses(raw: str) -> List[str]:
    """Extract lowercase email addresses from a comma-separated header value.

    Uses :func:`email.utils.getaddresses` so multi-recipient ``To``/``Cc``
    headers are handled correctly. Addresses that fail to parse are dropped.
    """
    if not raw:
        return []
    return [addr.lower() for _, addr in email.utils.getaddresses([raw]) if addr]


_PRIMARY_LABELS = ("SENT", "DRAFT", "SPAM", "TRASH", "INBOX")


def _select_channel(label_ids: List[str]) -> Optional[str]:
    """Pick the most specific Gmail system folder this message lives in."""
    label_set = set(label_ids)
    for label in _PRIMARY_LABELS:
        if label in label_set:
            return label
    return None


@ConnectorRegistry.register("gmail")
class GmailConnector(BaseConnector):
    """Connector that syncs emails from Gmail via the REST API.

    Authentication is handled through Google OAuth 2.0.  Tokens are stored
    locally in a JSON credentials file.

    Parameters
    ----------
    credentials_path:
        Path to the JSON file where OAuth tokens are stored.  Defaults to
        ``~/.vortis/connectors/gmail.json``.
    """

    connector_id = "gmail"
    display_name = "Gmail"
    auth_type = "oauth"

    def __init__(self, credentials_path: str = "") -> None:
        self._credentials_path = resolve_google_credentials(
            credentials_path or _DEFAULT_CREDENTIALS_PATH
        )
        self._items_synced: int = 0
        self._items_total: int = 0
        self._last_sync: Optional[datetime] = None
        self._last_cursor: Optional[str] = None


    def is_connected(self) -> bool:
        """Return ``True`` if a credentials file with a valid access token exists.

        The previous "any non-empty dict counts" check returned True for
        files containing only client_id/client_secret (no actual OAuth
        token), which made `vortis connect gmail` short-circuit with
        "already connected" before any OAuth flow ran.
        """
        tokens = load_tokens(self._credentials_path)
        if tokens is None:
            return False
        return bool(tokens.get("access_token") or tokens.get("token"))

    def disconnect(self) -> None:
        """Delete the stored credentials file."""
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        """Return a Google OAuth consent URL for the shared Google scopes."""
        return build_google_auth_url(
            client_id="",
            scopes=GOOGLE_ALL_SCOPES,
        )

    def handle_callback(self, code: str) -> None:
        """Handle the OAuth callback by persisting the authorization code.

        In a full implementation this would exchange the code for tokens.
        For now the code is saved directly as the token value.
        """
        save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        query_extra: str = "",
    ) -> Iterator[Document]:
        """Yield :class:`Document` objects for Gmail messages.

        Paginates through the messages.list API and fetches each message's
        full payload to extract headers and body.

        Parameters
        ----------
        since:
            When provided, only messages received after this timestamp are
            returned.  Translated to a Gmail ``after:<epoch>`` search query.
        cursor:
            ``nextPageToken`` from a previous sync to resume pagination.
        query_extra:
            Additional Gmail search operators appended to the base query,
            e.g. ``"is:unread"`` to restrict to unread messages only.
        """
        tokens = load_tokens(self._credentials_path)
        if not tokens or not (tokens.get("token") or tokens.get("access_token")):
            return

        query_parts: List[str] = []
        if since is not None:
            query_parts.append(f"after:{int(since.timestamp())}")
        if query_extra:
            query_parts.append(query_extra)
        query = " ".join(query_parts)

        page_token: Optional[str] = cursor
        synced = 0

        while True:
            list_resp = _call_with_refresh(
                _gmail_api_list_messages,
                self._credentials_path,
                page_token=page_token,
                query=query,
            )
            messages: List[Dict[str, Any]] = list_resp.get("messages", [])

            for msg_stub in messages:
                msg_id: str = msg_stub.get("id", "")
                if not msg_id:
                    continue

                msg = _call_with_refresh(
                    _gmail_api_get_message,
                    self._credentials_path,
                    msg_id,
                )
                payload: Dict[str, Any] = msg.get("payload", {})
                headers: List[Dict[str, str]] = payload.get("headers", [])

                from_header = _extract_header(headers, "From")
                to_header = _extract_header(headers, "To")
                cc_header = _extract_header(headers, "Cc")
                subject = _extract_header(headers, "Subject")
                date_str = _extract_header(headers, "Date")
                rfc_message_id = _extract_header(headers, "Message-ID")

                body = _decode_body(payload)
                timestamp = _parse_date(date_str)

                participants_raw: List[str] = [
                    h for h in (from_header, to_header, cc_header) if h
                ]
                participants: List[str] = []
                for header in (from_header, to_header, cc_header):
                    participants.extend(_normalize_addresses(header))

                label_ids: List[str] = msg.get("labelIds", [])
                channel = _select_channel(label_ids)
                thread_id: Optional[str] = msg.get("threadId")

                doc = Document(
                    doc_id=f"gmail:{msg_id}",
                    source="gmail",
                    source_id=msg_id,
                    doc_type="email",
                    content=body,
                    title=subject,
                    author=from_header,
                    participants=participants,
                    participants_raw=participants_raw,
                    timestamp=timestamp,
                    thread_id=thread_id,
                    channel=channel,
                    url=f"https://mail.google.com/mail/u/0/#all/{msg_id}",
                    metadata={
                        "message_id": msg_id,
                        "rfc_message_id": rfc_message_id,
                        "labels": label_ids,
                        "snippet": msg.get("snippet", ""),
                        "history_id": msg.get("historyId", ""),
                        "size_estimate": msg.get("sizeEstimate", 0),
                    },
                )
                synced += 1
                yield doc

            next_page: Optional[str] = list_resp.get("nextPageToken")
            if not next_page:
                self._last_cursor = None
                break
            page_token = next_page
            self._last_cursor = next_page

        self._items_synced = synced
        self._last_sync = datetime.now()

    def _current_token(self) -> str:
        """Return the cached access token (may be expired)."""
        tokens = load_tokens(self._credentials_path)
        if not tokens:
            raise RuntimeError("Gmail not authenticated")
        return tokens.get("token") or tokens.get("access_token") or ""

    def _refresh_token(self) -> str:
        """Refresh the access token using the stored refresh token.

        Raises ``RuntimeError`` if refresh fails (typically because the
        refresh token has been revoked — user must re-authorise).
        """
        new = refresh_google_token(self._credentials_path)
        if not new:
            raise RuntimeError(
                "Gmail token refresh failed — re-run `vortis connect gmail`"
            )
        return new

    def _call_with_refresh(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Invoke a ``_gmail_api_*`` function with auto-refresh on 401.

        Tries with the cached token first.  If the call raises an
        ``httpx.HTTPStatusError`` with a 401, refresh the access token
        once and retry.  Any other failure propagates unchanged.
        """
        import httpx

        token = self._current_token()
        try:
            return fn(token, *args, **kwargs)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise
            token = self._refresh_token()
            return fn(token, *args, **kwargs)

    def delete_message(self, msg_id: str) -> None:
        """Move a message to Trash (recoverable for 30 days)."""
        self._call_with_refresh(_gmail_api_trash_message, msg_id)

    def archive_message(self, msg_id: str) -> None:
        """Archive a message by removing the INBOX label."""
        self._call_with_refresh(
            _gmail_api_modify_message, msg_id, remove_labels=["INBOX"]
        )

    def sync_status(self) -> SyncStatus:
        """Return sync progress from the most recent :meth:`sync` call."""
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            last_sync=self._last_sync,
            cursor=self._last_cursor,
        )


    def mcp_tools(self) -> List[ToolSpec]:
        """Expose three MCP tool specs for real-time Gmail queries."""
        return [
            ToolSpec(
                name="gmail_search_emails",
                description=(
                    "Search Gmail messages using a query string. "
                    "Supports the same syntax as the Gmail search box "
                    "(e.g. 'from:alice subject:report is:unread')."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Gmail search query",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of emails to return",
                            "default": 20,
                        },
                    },
                    "required": ["query"],
                },
                category="communication",
            ),
            ToolSpec(
                name="gmail_get_thread",
                description=("Retrieve all messages in a Gmail thread by thread ID."),
                parameters={
                    "type": "object",
                    "properties": {
                        "thread_id": {
                            "type": "string",
                            "description": "Gmail thread ID",
                        },
                    },
                    "required": ["thread_id"],
                },
                category="communication",
            ),
            ToolSpec(
                name="gmail_list_unread",
                description=(
                    "List unread Gmail messages, optionally filtered by label."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Gmail label to filter by (e.g. 'INBOX')",
                            "default": "INBOX",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of messages to return",
                            "default": 20,
                        },
                    },
                    "required": [],
                },
                category="communication",
            ),
        ]
