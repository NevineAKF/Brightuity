"""
shared/call_agent_model.py
Brightuity — Model-access engine with automatic failover and schema validation.

Implements blueprint section 4 exactly:
  1. Try PRIMARY model (timeout; empty/invalid/non-validating response = failure).
  2. On failure: retry PRIMARY once (same prompt, same model).
  3. On 2nd failure: switch silently to FALLBACK (same prompt, same contract).
  4. If FALLBACK also fails: raise ModelUnavailableError → Orchestrator escalates
     to human via Band.

JSON enforcement is tiered per the verified capability matrix (2026-06-14):
  "schema" → response_format json_schema strict (AI/ML API: all models)
  "object" → response_format json_object        (Featherless: DeepSeek-V4 only)
  "plain"  → no response_format                 (Featherless: Qwen3, Kimi, GLM, Gemma)

Every response — regardless of tier — passes through one shared normalize+validate
path before being accepted. A response that won't parse or won't validate against
the expected Pydantic schema is treated identically to a model error: routed to
retry then failover. Malformed output can never be returned as a verdict.

This module knows NOTHING about agents, verdicts, Band, or business logic.
It receives a model spec + prompt + schema and returns a validated object.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import (
    OpenAI,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
)
from pydantic import BaseModel, ValidationError

from shared.config import (
    AGENT_MODEL_CHAINS,
    CALL_TIMEOUT_SECONDS,
    MAX_TOKENS_DEFAULT,
    PLATFORMS,
    ModelChain,
    Platform,
)

logger = logging.getLogger(__name__)


# ── Return type ────────────────────────────────────────────────────────────────

@dataclass
class ModelResponse:
    """
    Result of a successful call_agent_model() invocation.

    Fields:
        data        — validated Pydantic verdict instance (schema class depends on
                      the schema argument passed to call_agent_model).
        model_used  — the model ID that actually responded (primary or fallback).
        platform    — "aimlapi" or "featherless".
        was_fallback — True if the primary model failed and the fallback was used.
        attempts    — total API call attempts made (1 = direct hit; 3 = both
                      primary retries failed, fallback succeeded).
        latency_ms  — wall-clock milliseconds for the successful call only
                      (not cumulative across retries).
    """
    data:        Any    # validated Pydantic BaseModel instance
    model_used:  str
    platform:    str
    was_fallback: bool
    attempts:    int
    latency_ms:  int


# ── Exception ──────────────────────────────────────────────────────────────────

class ModelUnavailableError(Exception):
    """
    Raised when both primary and fallback models fail for the same agent.
    The Orchestrator catches this and escalates to the human reviewer via Band,
    as specified in blueprint section 4 step 5.
    """

    def __init__(
        self,
        agent_name: str,
        primary: str,
        fallback: str,
        last_error: str,
    ) -> None:
        self.agent_name = agent_name
        self.primary = primary
        self.fallback = fallback
        self.last_error = last_error
        super().__init__(
            f"All models unavailable for agent '{agent_name}'. "
            f"primary='{primary}', fallback='{fallback}'. "
            f"Last error: {last_error}. "
            f"Escalating to human reviewer."
        )


# ── Internal: client cache ─────────────────────────────────────────────────────

_client_cache: dict[str, OpenAI] = {}


def _get_client(platform: Platform) -> OpenAI:
    """Return a cached OpenAI-compatible client for the given platform."""
    key = platform.value
    if key not in _client_cache:
        cfg = PLATFORMS[platform]
        _client_cache[key] = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=CALL_TIMEOUT_SECONDS,
            max_retries=0,
        )
        logger.debug("platform=%s client initialised base_url=%s", platform.value, cfg.base_url)
    return _client_cache[key]


# ── Schema helpers ─────────────────────────────────────────────────────────────

def _make_strict_schema(model_cls: type[BaseModel]) -> dict:
    """
    Convert a Pydantic model schema to the compact form required for strict
    json_schema mode: additionalProperties added, titles/descriptions stripped.

    The result matches the hand-crafted schemas that passed the 2026-06-14
    structured-output probe on all three AI/ML API models.
    """
    schema = model_cls.model_json_schema()
    schema["additionalProperties"] = False
    schema.pop("title", None)
    schema.pop("description", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
        prop.pop("description", None)
    return schema


def _schema_name(model_cls: type[BaseModel]) -> str:
    """Convert CamelCase class name to snake_case for the json_schema name field."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", model_cls.__name__).lower()


# ── Shared normalize + validate ────────────────────────────────────────────────

def _normalize_and_validate(
    raw: str,
    schema: type[BaseModel],
    model_id: str,
    agent_name: str,
) -> BaseModel:
    """
    Strip formatting artifacts, extract the first JSON object, validate against
    the Pydantic schema. Raises ValueError on any failure — the caller routes
    that failure to retry/failover identically to a network or API error.

    Steps (applied in order):
      a. Strip <think>...</think> blocks (Qwen3, DeepSeek, Claude extended thinking)
      b. Extract content between ```json ... ``` fences if present (Gemini)
         OR strip stray fence markers if not in a complete fence block
      c. Locate the first { via json.JSONDecoder().raw_decode — stops at the
         end of the first valid JSON object, ignoring any trailing prose
      d. Validate by constructing schema.model_validate(parsed_dict) — Pydantic
         enforces field presence, types, and enum membership
    """
    text = raw.strip()

    # a. Strip think blocks
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    # b. Strip markdown fences
    fence_match = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n?\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        text = re.sub(r"```(?:json)?", "", text).strip()

    # c. Parse the first JSON object
    brace = text.find("{")
    if brace < 0:
        raise ValueError(
            f"{agent_name}: no JSON object found in response from {model_id}. "
            f"Raw (first 200 chars): {raw[:200]!r}"
        )

    try:
        data_dict, _ = json.JSONDecoder().raw_decode(text, brace)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{agent_name}: JSON parse failed from {model_id}: {exc}. "
            f"Raw (first 200 chars): {raw[:200]!r}"
        ) from exc

    # d. Validate against Pydantic schema
    try:
        return schema.model_validate(data_dict)
    except ValidationError as exc:
        raise ValueError(
            f"{agent_name}: schema validation failed for {model_id}: {exc}"
        ) from exc


# ── Internal: single attempt ───────────────────────────────────────────────────

def _call_once(
    client: OpenAI,
    model_id: str,
    json_mode: str,
    prompt: str,
    system_prompt: str | None,
    schema: type[BaseModel],
    agent_name: str,
) -> tuple[BaseModel, int]:
    """
    Make one API call and return (validated_schema_instance, latency_ms).

    Builds the request with the appropriate response_format for this model's
    json_mode, calls the API, then passes the raw response through
    _normalize_and_validate. Raises on any API error, empty response, or
    validation failure — callers decide whether to retry or failover.
    """
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {
        "model":      model_id,
        "messages":   messages,
        "max_tokens": MAX_TOKENS_DEFAULT,
    }

    if json_mode == "schema":
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name":   _schema_name(schema),
                "strict": True,
                "schema": _make_strict_schema(schema),
            },
        }
    elif json_mode == "object":
        kwargs["response_format"] = {"type": "json_object"}
    # "plain": no response_format key added

    t0 = time.monotonic()
    completion = client.chat.completions.create(**kwargs)
    latency_ms = int((time.monotonic() - t0) * 1000)

    raw: str | None = completion.choices[0].message.content
    if not raw or not raw.strip():
        raise ValueError(
            f"Model '{model_id}' returned an empty response "
            f"(finish_reason={completion.choices[0].finish_reason}). "
            "Triggering retry/failover."
        )

    validated = _normalize_and_validate(raw.strip(), schema, model_id, agent_name)
    return validated, latency_ms


# ── Public interface ───────────────────────────────────────────────────────────

def call_agent_model(
    agent_name: str,
    prompt: str,
    system_prompt: str | None = None,
    *,
    schema: type[BaseModel],
) -> ModelResponse:
    """
    Call the appropriate model for the named agent, with automatic failover.

    Blueprint section 4 failover sequence (unchanged from prior version):
      Attempt 1 — PRIMARY model.
      Attempt 2 — PRIMARY model (silent retry on any failure).
      Attempt 3 — FALLBACK model (after two primary failures, with switchover log).
      If attempt 3 fails → raise ModelUnavailableError.

    What IS new: each attempt uses this model's verified json_mode to build the
    request, and every response — before being returned — must pass
    _normalize_and_validate against the provided Pydantic schema. A response
    that won't parse or validate is treated identically to a network error:
    routed to the next attempt. Malformed output cannot escape this function.

    Args:
        agent_name:    One of the six LLM agent names in config.py.
        prompt:        The user-turn message.
        system_prompt: Optional system-turn message.
        schema:        The Pydantic model class that defines the expected output
                       (keyword-only). Must be a subclass of BaseModel.

    Returns:
        ModelResponse with .data as a validated instance of `schema`,
        plus model_used, was_fallback, attempts, latency_ms.

    Raises:
        ValueError:             agent_name not in AGENT_MODEL_CHAINS.
        ModelUnavailableError:  all attempts failed.
        EnvironmentError:       API key env var missing or empty.
    """
    chain: ModelChain | None = AGENT_MODEL_CHAINS.get(agent_name)
    if chain is None:
        raise ValueError(
            f"Unknown agent '{agent_name}'. "
            f"Valid agents: {sorted(AGENT_MODEL_CHAINS)}. "
            f"Note: 'consensus_signer' uses no LLM and is not in the registry."
        )

    client = _get_client(chain.platform)
    last_error: str = ""
    total_attempts: int = 0

    # ── Attempts 1 & 2: PRIMARY (then one silent retry) ───────────────────────
    for attempt_num in range(1, 3):
        total_attempts += 1
        logger.info(
            "agent=%s platform=%s model=%s attempt=%d/3",
            agent_name, chain.platform.value, chain.primary, attempt_num,
        )
        try:
            validated, latency_ms = _call_once(
                client, chain.primary, chain.primary_json_mode,
                prompt, system_prompt, schema, agent_name,
            )
            logger.info(
                "agent=%s model=%s SUCCESS attempt=%d latency_ms=%d",
                agent_name, chain.primary, attempt_num, latency_ms,
            )
            return ModelResponse(
                data=validated,
                model_used=chain.primary,
                platform=chain.platform.value,
                was_fallback=False,
                attempts=total_attempts,
                latency_ms=latency_ms,
            )
        except (APITimeoutError, APIConnectionError, APIStatusError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "agent=%s model=%s attempt=%d FAILED error=%s",
                agent_name, chain.primary, attempt_num, last_error,
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "agent=%s model=%s attempt=%d UNEXPECTED_FAILURE error=%s",
                agent_name, chain.primary, attempt_num, last_error,
            )

    # ── Attempt 3: FALLBACK ────────────────────────────────────────────────────
    logger.warning(
        "agent=%s SWITCHOVER primary=%s exhausted (2 failures) → fallback=%s "
        "platform=%s last_error=%s",
        agent_name, chain.primary, chain.fallback, chain.platform.value, last_error,
    )

    total_attempts += 1
    logger.info(
        "agent=%s platform=%s model=%s attempt=3/3 (FALLBACK)",
        agent_name, chain.platform.value, chain.fallback,
    )
    try:
        validated, latency_ms = _call_once(
            client, chain.fallback, chain.fallback_json_mode,
            prompt, system_prompt, schema, agent_name,
        )
        logger.info(
            "agent=%s model=%s FALLBACK_SUCCESS attempt=3 latency_ms=%d",
            agent_name, chain.fallback, latency_ms,
        )
        return ModelResponse(
            data=validated,
            model_used=chain.fallback,
            platform=chain.platform.value,
            was_fallback=True,
            attempts=total_attempts,
            latency_ms=latency_ms,
        )
    except (APITimeoutError, APIConnectionError, APIStatusError, ValueError) as exc:
        last_error = f"{type(exc).__name__}: {exc}"
        logger.error(
            "agent=%s model=%s FALLBACK FAILED error=%s — escalating to human",
            agent_name, chain.fallback, last_error,
        )
    except Exception as exc:
        last_error = f"{type(exc).__name__}: {exc}"
        logger.error(
            "agent=%s model=%s FALLBACK UNEXPECTED_FAILURE error=%s — escalating",
            agent_name, chain.fallback, last_error,
        )

    raise ModelUnavailableError(
        agent_name=agent_name,
        primary=chain.primary,
        fallback=chain.fallback,
        last_error=last_error,
    )
