"""
backend/band_bridge.py
Brightuity — Band Agent API bridge.

The backend authenticates as a dedicated "Backend Trigger" Band agent (its own
API key and UUID). Per-case it creates a dedicated chat room, seeds it with all
specialist agents as participants, posts the @Orchestrator trigger, then polls
the room's context endpoint for the terminal tool_result event written by the
orchestrator adapter.  No filesystem IPC — results travel over Band only.

Band Agent API (base: {THENVOI_REST_URL}/api/v1/agent):
  POST /chats                         Create room  (body: {"chat": {}})
  POST /chats/{chat_id}/participants  Add agent participant
  POST /chats/{chat_id}/messages      Post trigger message
  GET  /chats/{chat_id}/context       Poll for terminal result event

Auth: X-API-Key: {BAND_BACKEND_API_KEY} on every call (NOT Authorization: Bearer).

Required env vars:
  BAND_BACKEND_API_KEY        API key for the backend's Band agent identity.
  BAND_BACKEND_AGENT_ID       UUID of the backend Band agent (self-identification).
  BAND_ORCHESTRATOR_AGENT_ID  UUID of the Orchestrator agent (trigger target).

Agent UUIDs for participant seeding (all optional — add as agents are onboarded):
  BAND_ORCHESTRATOR_AGENT_ID, BAND_KYC_AGENT_ID, BAND_COMPLIANCE_AGENT_ID,
  BAND_DOCAUDITOR_AGENT_ID, BAND_STRESSTEST_AGENT_ID, BAND_TOKENIZER_AGENT_ID,
  BAND_CONSENSUS_AGENT_ID, BAND_GOVERNANCE_AGENT_ID.

Config (with defaults):
  THENVOI_REST_URL            Band base URL (default: https://app.band.ai).
  BAND_ORCHESTRATOR_HANDLE    Orchestrator @handle for mention (default: Orchestrator).
  BAND_BRIDGE_POLL_INTERVAL   Seconds between context polls (default: 5).
  BAND_BRIDGE_TIMEOUT         Max wait seconds for the terminal result (default: 180).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from backend import case_store

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Configuration ──────────────────────────────────────────────────────────────

_REST_URL         = os.getenv("THENVOI_REST_URL",             "https://app.band.ai").rstrip("/")
_BACKEND_API_KEY  = os.getenv("BAND_BACKEND_API_KEY",         "")
_BACKEND_AGENT_ID = os.getenv("BAND_BACKEND_AGENT_ID",        "")
_ORCH_ID          = os.getenv("BAND_ORCHESTRATOR_AGENT_ID",   "")
_ORCH_HANDLE      = os.getenv("BAND_ORCHESTRATOR_HANDLE",     "Orchestrator")
_POLL_SECS        = float(os.getenv("BAND_BRIDGE_POLL_INTERVAL", "5"))
_TIMEOUT_SECS     = float(os.getenv("BAND_BRIDGE_TIMEOUT",       "180"))

# All agent UUIDs to seed into the room.
# dict.fromkeys preserves insertion order and deduplicates (e.g. if the same
# UUID is set for two env vars), filter(None, ...) drops empty strings.
_PARTICIPANT_IDS: tuple[str, ...] = tuple(dict.fromkeys(filter(None, [
    os.getenv("BAND_ORCHESTRATOR_AGENT_ID",  ""),
    os.getenv("BAND_KYC_AGENT_ID",           ""),
    os.getenv("BAND_COMPLIANCE_AGENT_ID",    ""),
    os.getenv("BAND_DOCAUDITOR_AGENT_ID",    ""),
    os.getenv("BAND_STRESSTEST_AGENT_ID",    ""),
    os.getenv("BAND_TOKENIZER_AGENT_ID",     ""),
    os.getenv("BAND_CONSENSUS_AGENT_ID",     ""),
    os.getenv("BAND_GOVERNANCE_AGENT_ID",    ""),
])))

_AGENT_BASE = f"{_REST_URL}/api/v1/agent"

# Unique content prefix embedded in every terminal result event by the
# orchestrator adapter.  The backend's _find_terminal_result() locates the
# event by this marker — no regex, no NLP.
_TERMINAL_PREFIX = "brightuity_terminal:"


# ── Public interface ───────────────────────────────────────────────────────────

def is_configured() -> bool:
    """
    Return True when the three minimum Band credentials are present.

    False → main.py falls back to the in-process run_pipeline() path.
    True  → run_case_via_band() is safe to call.
    """
    return bool(_BACKEND_API_KEY and _BACKEND_AGENT_ID and _ORCH_ID)


def run_case_via_band(request_id: str) -> tuple[dict, list[dict]]:
    """
    Drive the live Band orchestrator for request_id and return its result.

    Steps:
      1. Create (or reuse) a Band chat room linked to this case.
      2. Seed the room with all configured specialist agent participants.
      3. Post "@Orchestrator {request_id}" as the pipeline trigger.
      4. Poll GET /agent/chats/{chat_id}/context at BAND_BRIDGE_POLL_INTERVAL
         until the orchestrator adapter posts its terminal tool_result event.

    Returns:
        (decision_record, event_log) — identical shape to run_pipeline(), so
        the unchanged assemble_evidence_package → case_store flow keeps working.

    Raises:
        RuntimeError:          bridge not configured; call is_configured() first.
        TimeoutError:          orchestrator did not post a terminal result in time.
        httpx.HTTPStatusError: non-2xx from Band API (body logged at ERROR).
        ValueError:            terminal result event is missing required keys.
    """
    if not is_configured():
        raise RuntimeError(
            "band_bridge: not configured — set BAND_BACKEND_API_KEY, "
            "BAND_BACKEND_AGENT_ID, and BAND_ORCHESTRATOR_AGENT_ID in .env."
        )

    with _api_client() as client:
        chat_id = _create_or_reuse_room(client, request_id)
        logger.info("band_bridge: REQ %s created/polling chat_id=%s", request_id, chat_id)
        try:
            case_store.set_band_chat_id(request_id, chat_id)
        except Exception as e:
            logger.warning("band_bridge: could not persist chat_id for %s: %s", request_id, e)
        _add_participants(client, chat_id)
        _post_trigger(client, chat_id, request_id)
        return _await_result(client, chat_id, request_id)


def fetch_room_messages(chat_id: str) -> list[dict]:
    """
    Fetch the current messages of a Band room by chat_id.

    Reuses _api_client() and _AGENT_BASE — no hardcoded URLs or keys.
    Applies the same defensive response-shape handling as _await_result() so
    all plausible Band context shapes are handled:
      bare list → items = context_data
      dict with messages/events/history/items/data keys → items extended from each

    Returns a normalized list of message dicts:
        { "sender_id", "message_type", "content", "metadata" }

    Raises httpx.HTTPStatusError on a non-2xx Band API response.
    Raises ValueError on an unparseable response body.
    An empty room legitimately returns [].
    """
    with _api_client() as client:
        url  = f"{_AGENT_BASE}/chats/{chat_id}/context"
        resp = client.get(url)

        if not resp.is_success:
            logger.error(
                "band_bridge: fetch_room_messages HTTP %s for chat_id=%s: %s",
                resp.status_code, chat_id, resp.text[:200],
            )
            resp.raise_for_status()

        try:
            context_data = resp.json()
        except Exception as exc:
            raise ValueError(
                f"band_bridge: fetch_room_messages — unparseable response for "
                f"chat_id={chat_id}: {exc}"
            ) from exc

        # Normalise into a flat item list — same logic as _await_result()
        items: list[Any] = []
        if isinstance(context_data, list):
            items = context_data
        elif isinstance(context_data, dict):
            for key in ("messages", "events", "history", "items", "data"):
                val = context_data.get(key)
                if isinstance(val, list):
                    items.extend(val)

        return [
            {
                "sender_id":    item.get("sender_id") or item.get("sender_name"),
                "message_type": item.get("message_type"),
                "content":      item.get("content") or item.get("text") or "",
                "metadata":     item.get("metadata") or item.get("data") or {},
            }
            for item in items
            if isinstance(item, dict)
        ]


# ── HTTP client ────────────────────────────────────────────────────────────────

def _api_client() -> httpx.Client:
    """
    Return an httpx.Client pre-configured for the Band Agent API.

    Auth:    X-API-Key (Band's documented agent authentication, NOT Bearer).
    Timeout: 10 s connect / 30 s read — adequate for single API calls.
             The polling wall-clock deadline in _await_result is managed
             separately via time.monotonic(), not httpx timeouts.
    """
    return httpx.Client(
        headers={
            "X-API-Key":    _BACKEND_API_KEY,
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
    )


# ── Room creation ──────────────────────────────────────────────────────────────

def _create_or_reuse_room(client: httpx.Client, request_id: str) -> str:
    """
    POST /agent/chats  →  create a Band chat room linked to this case.

    Idempotency: if Band returns 409 Conflict (room already exists —
    e.g. a pipeline re-run), we parse the existing chat_id from the
    response body and reuse the room rather than raising.  Any other non-2xx
    status propagates so the caller sees a clean error.

    Returns:
        chat_id — the room identifier for all subsequent API calls.
    """
    url  = f"{_AGENT_BASE}/chats"
    resp = client.post(url, json={"chat": {}})

    if resp.status_code == 409:
        chat_id = _extract_chat_id(resp)
        if not chat_id:
            logger.error(
                "band_bridge: 409 for %s but no chat_id in response: %r",
                request_id, resp.text[:400],
            )
            resp.raise_for_status()
        logger.info(
            "band_bridge: room already exists — reusing chat_id=%s for %s",
            chat_id, request_id,
        )
        return chat_id

    if not resp.is_success:
        logger.error(
            "band_bridge: POST /agent/chats HTTP %s for %s: %s",
            resp.status_code, request_id, resp.text[:400],
        )
        resp.raise_for_status()

    chat_id = _extract_chat_id(resp)
    if not chat_id:
        raise ValueError(
            f"band_bridge: POST /agent/chats HTTP {resp.status_code} but no "
            f"chat_id in response for {request_id}: {resp.text[:400]}"
        )

    logger.info(
        "band_bridge: room created chat_id=%s request_id=%s",
        chat_id, request_id,
    )
    return chat_id


def _extract_chat_id(resp: httpx.Response) -> str:
    """
    Parse chat_id from a Band API response body.

    Band may represent the identifier as chat_id, id, or nested under a
    "chat" key.  Returns an empty string if nothing is found so the caller
    can decide whether to raise.
    """
    try:
        data = resp.json()
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(
        (data.get("data") or {}).get("id")
        or data.get("chat_id")
        or data.get("id")
        or (data.get("chat") or {}).get("chat_id")
        or (data.get("chat") or {}).get("id")
        or ""
    )


# ── Participant seeding ────────────────────────────────────────────────────────

def _add_participants(client: httpx.Client, chat_id: str) -> None:
    """
    POST /agent/chats/{chat_id}/participants  for every configured agent UUID.

    Failure policy:
    • 409 (already a participant) → DEBUG log, continue — idempotent re-run.
    • Other non-2xx              → WARNING log, continue — a missing advisory
      agent must not abort the pipeline for the rest.
    • Network error              → WARNING log, continue.
    """
    url = f"{_AGENT_BASE}/chats/{chat_id}/participants"

    for agent_id in _PARTICIPANT_IDS:
        try:
            resp = client.post(url, json={"participant": {"participant_id": agent_id}})
            if resp.status_code == 409:
                logger.debug(
                    "band_bridge: agent %s already in chat %s", agent_id, chat_id,
                )
            elif not resp.is_success:
                logger.warning(
                    "band_bridge: add agent %s to chat %s — HTTP %s: %s",
                    agent_id, chat_id, resp.status_code, resp.text[:200],
                )
            else:
                logger.debug(
                    "band_bridge: added agent %s to chat %s", agent_id, chat_id,
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "band_bridge: network error adding agent %s to chat %s: %s",
                agent_id, chat_id, exc,
            )


# ── Trigger ────────────────────────────────────────────────────────────────────

def _post_trigger(client: httpx.Client, chat_id: str, request_id: str) -> None:
    """
    POST /agent/chats/{chat_id}/messages  — send the @Orchestrator trigger.

    Uses Band's documented message body shape (content + typed mentions array)
    so the orchestrator adapter reliably identifies this as a targeted @mention
    and starts a new pipeline case.  Raises on non-2xx — the trigger is
    required; without it the orchestrator never starts.
    """
    url     = f"{_AGENT_BASE}/chats/{chat_id}/messages"
    payload = {
        "message": {
            "content":  f"@{_ORCH_HANDLE} {request_id}",
            "mentions": [
                {
                    "id":     _ORCH_ID,
                    "name":   "Orchestrator",
                    "handle": _ORCH_HANDLE,
                }
            ],
        }
    }

    resp = client.post(url, json=payload)
    if not resp.is_success:
        logger.error(
            "band_bridge: POST trigger chat_id=%s request_id=%s — HTTP %s: %s",
            chat_id, request_id, resp.status_code, resp.text[:400],
        )
        resp.raise_for_status()

    logger.info(
        "band_bridge: trigger posted chat_id=%s request_id=%s",
        chat_id, request_id,
    )


# ── Result polling ─────────────────────────────────────────────────────────────

def _await_result(
    client: httpx.Client,
    chat_id: str,
    request_id: str,
) -> tuple[dict, list[dict]]:
    """
    Poll GET /agent/chats/{chat_id}/context until the orchestrator adapter
    posts its terminal tool_result event, then extract and return the result.

    The orchestrator adapter posts a terminal event with exactly:
        content      = "brightuity_terminal:{request_id}"
        message_type = "tool_result"
        metadata     = {
            "request_id":      request_id,
            "terminal_result": True,
            "decision_record": {...},
            "event_log":       [...],
        }

    Polling is bounded: BAND_BRIDGE_POLL_INTERVAL seconds per cycle up to
    BAND_BRIDGE_TIMEOUT seconds total before TimeoutError is raised.

    Transient network errors and non-2xx responses are logged and retried;
    only a hard timeout causes this function to raise.
    """
    url      = f"{_AGENT_BASE}/chats/{chat_id}/context"
    deadline = time.monotonic() + _TIMEOUT_SECS

    logger.info(
        "band_bridge: awaiting result chat_id=%s request_id=%s "
        "(timeout=%.0fs interval=%.0fs)",
        chat_id, request_id, _TIMEOUT_SECS, _POLL_SECS,
    )

    while time.monotonic() < deadline:
        try:
            resp = client.get(url)
            if resp.is_success:
                context_data = resp.json()
                # ── Diagnostic: log what GET /context returned this cycle ────
                _diag_items: list[Any] = []
                if isinstance(context_data, list):
                    _diag_items = context_data
                elif isinstance(context_data, dict):
                    for _k in ("messages", "events", "history", "items", "data"):
                        _v = context_data.get(_k)
                        if isinstance(_v, list):
                            _diag_items.extend(_v)
                logger.info(
                    "band_bridge: REQ %s poll: %d context items",
                    request_id, len(_diag_items),
                )
                for _it in _diag_items:
                    if not isinstance(_it, dict):
                        continue
                    _c = _it.get("content") or _it.get("text") or ""
                    logger.info(
                        "band_bridge:   item type=%s sender=%s content=%r",
                        _it.get("message_type"),
                        _it.get("sender_id") or _it.get("sender_name"),
                        _c[:60],
                    )
                # ─────────────────────────────────────────────────────────────
                result = _find_terminal_result(context_data, request_id)
                if result is not None:
                    decision_record, event_log = result
                    logger.info(
                        "band_bridge: terminal result received chat_id=%s "
                        "request_id=%s pipeline_status=%s",
                        chat_id, request_id,
                        decision_record.get("pipeline_status"),
                    )
                    return decision_record, event_log
            else:
                logger.warning(
                    "band_bridge: GET context HTTP %s for %s — retrying",
                    resp.status_code, request_id,
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "band_bridge: network error polling context for %s: %s — retrying",
                request_id, exc,
            )

        time.sleep(_POLL_SECS)

    raise TimeoutError(
        f"band_bridge: orchestrator did not post a terminal result for "
        f"{request_id} within {_TIMEOUT_SECS:.0f}s (chat_id={chat_id}). "
        "Check Band agent logs."
    )


def _find_terminal_result(
    context_data: Any,
    request_id: str,
) -> tuple[dict, list[dict]] | None:
    """
    Search a GET /agent/chats/{chat_id}/context response for the terminal event.

    Handles all plausible Band context response shapes:
      {"messages": [...], "events": [...]}   — messages and events as separate lists
      {"history": [...]}                      — unified history list
      [...]                                   — bare top-level list

    Within each item it applies a dual-signal match to avoid false positives
    from other tool_result events already in the room:
      • content.startswith("brightuity_terminal:{request_id}")   — distinctive prefix
      • OR metadata["terminal_result"] is True and metadata["request_id"] matches

    Returns:
        (decision_record, event_log) on success, None if not yet present.
        Malformed events (missing decision_record) are logged and skipped so
        the polling loop continues rather than raising.
    """
    items: list[Any] = []

    if isinstance(context_data, list):
        items = context_data
    elif isinstance(context_data, dict):
        for key in ("messages", "events", "history", "items", "data"):
            val = context_data.get(key)
            if isinstance(val, list):
                items.extend(val)

    marker = f"{_TERMINAL_PREFIX}{request_id}"

    for item in items:
        if not isinstance(item, dict):
            continue

        content  = item.get("content") or item.get("text") or ""
        metadata = item.get("metadata") or item.get("data") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        if "brightuity_terminal" in content:
            logger.info(
                "band_bridge: saw terminal-ish item: content=%r meta_keys=%s",
                content[:80],
                list(metadata.keys()),
            )
        # Band prepends mention tokens to message content, e.g.:
        #   "@[[uuid]] brightuity_terminal:REQ-2041 {...}"
        # Use find() so the marker is located regardless of any leading prefix.
        idx           = content.find(marker) if isinstance(content, str) else -1
        content_match = idx != -1
        meta_match    = (
            metadata.get("terminal_result") is True
            and metadata.get("request_id") == request_id
        )

        if not (content_match or meta_match):
            continue

        decision_record = metadata.get("decision_record")
        event_log       = metadata.get("event_log")

        # Fallback: the orchestrator delivers the terminal result as a
        # send_message @mentioning the backend (text messages appear in the
        # backend's GET /context view; send_event does not).  Text messages
        # carry no metadata, so parse the JSON payload from the content.
        # Slice from idx (the marker position) to skip any leading @[[uuid]] prefix.
        #   tail format: "brightuity_terminal:{id} {json_payload}"
        if not isinstance(decision_record, dict) and content_match:
            try:
                tail        = content[idx:]                # from marker onward
                payload_str = tail[len(marker):].lstrip()  # strip marker + whitespace
                parsed = json.loads(payload_str)
                decision_record = parsed.get("decision_record")
                event_log       = parsed.get("event_log", [])
            except (ValueError, KeyError):
                pass

        if not isinstance(decision_record, dict):
            logger.warning(
                "band_bridge: terminal event for %s has no valid "
                "decision_record — skipping malformed entry", request_id,
            )
            continue

        if not isinstance(event_log, list):
            logger.warning(
                "band_bridge: terminal event for %s has no event_log "
                "in metadata — using empty list", request_id,
            )
            event_log = []

        return decision_record, event_log

    return None
