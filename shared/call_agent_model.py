"""
shared/call_agent_model.py
Brightuity — Model-access engine with automatic failover.

Implements blueprint section 4 exactly:
  1. Try PRIMARY model (30 s timeout; empty/invalid response = failure).
  2. On failure: retry PRIMARY once (same prompt, same model).
  3. On 2nd failure: switch silently to FALLBACK (same prompt, same contract).
  4. If FALLBACK also fails: raise ModelUnavailableError → Orchestrator escalates
     to human via Band.

Triggers for retry/failover: API errors, timeouts, rate limits, exhausted
credits, malformed responses, or empty text in an otherwise valid response.

This module knows NOTHING about agents, verdicts, Band, or business logic.
It receives a model spec + prompt and returns text, with failover. Any
agent can call it without knowing which platform or model is behind it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from openai import (
    OpenAI,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
)

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
        text        — the model's response text, stripped of leading/trailing whitespace.
        model_used  — the model ID that actually responded (primary or fallback).
        platform    — "aimlapi" or "featherless".
        was_fallback — True if the primary model failed and the fallback was used.
                       The Orchestrator uses this flag to log a switchover event
                       to the audit trail via Band.
        attempts    — total API call attempts made (1 = direct hit; 3 = both
                      primary retries failed, fallback succeeded).
        latency_ms  — wall-clock milliseconds for the successful call only
                      (not cumulative across retries).
    """
    text: str
    model_used: str
    platform: str
    was_fallback: bool
    attempts: int
    latency_ms: int


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

# One OpenAI-compatible client per platform, created on first use and reused.
# Keys are Platform enum values (strings). Thread-safe for read after first write
# because GIL protects the dict assignment; in an async context use a lock.
_client_cache: dict[str, OpenAI] = {}


def _get_client(platform: Platform) -> OpenAI:
    """
    Return a cached OpenAI-compatible client for the given platform.
    Reads the API key from the environment on first call (via PlatformConfig.api_key).
    """
    key = platform.value
    if key not in _client_cache:
        cfg = PLATFORMS[platform]
        _client_cache[key] = OpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=CALL_TIMEOUT_SECONDS,
            max_retries=0,   # we own the retry logic — disable SDK auto-retry
        )
        logger.debug("platform=%s client initialised base_url=%s", platform.value, cfg.base_url)
    return _client_cache[key]


# ── Internal: single attempt ───────────────────────────────────────────────────

def _call_once(
    client: OpenAI,
    model_id: str,
    prompt: str,
    system_prompt: str | None,
) -> tuple[str, int]:
    """
    Make one API call and return (response_text, latency_ms).

    Raises on any API error or if the returned text is empty/whitespace.
    Callers are responsible for deciding whether to retry or failover.
    """
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    t0 = time.monotonic()
    completion = client.chat.completions.create(
        model=model_id,
        messages=messages,
        max_tokens=MAX_TOKENS_DEFAULT,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    text: str | None = completion.choices[0].message.content
    if not text or not text.strip():
        raise ValueError(
            f"Model '{model_id}' returned an empty response. "
            "Treating as failure and triggering retry/failover."
        )

    return text.strip(), latency_ms


# ── Public interface ───────────────────────────────────────────────────────────

def call_agent_model(
    agent_name: str,
    prompt: str,
    system_prompt: str | None = None,
) -> ModelResponse:
    """
    Call the appropriate model for the named agent, with automatic failover.

    Blueprint section 4 failover sequence (implemented exactly):
      Attempt 1 — PRIMARY model.
      Attempt 2 — PRIMARY model (silent retry on any failure).
      Attempt 3 — FALLBACK model (after two primary failures, with switchover log).
      If attempt 3 fails → raise ModelUnavailableError.

    All transitions are logged at WARNING level so the audit layer can detect
    switchover events without requiring a database write from this module.

    Args:
        agent_name:    One of the six LLM agent names defined in config.py
                       (orchestrator, doc_auditor, kyc_guardian,
                       dynamic_compliance, stress_test, asset_tokenizer).
                       'consensus_signer' is not valid — it uses no LLM.
        prompt:        The user-turn message to send to the model.
        system_prompt: Optional system-turn message prepended to every call.
                       Typically the agent's persona and task instructions.

    Returns:
        ModelResponse with the text, model/platform used, failover flag,
        attempt count, and latency of the successful call.

    Raises:
        ValueError:             agent_name not found in AGENT_MODEL_CHAINS.
        ModelUnavailableError:  all attempts (primary × 2 + fallback × 1) failed.
        EnvironmentError:       API key env var is missing or empty.
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
    for attempt_num in range(1, 3):   # 1, 2
        total_attempts += 1
        logger.info(
            "agent=%s platform=%s model=%s attempt=%d/%d",
            agent_name, chain.platform.value, chain.primary, attempt_num, 3,
        )
        try:
            text, latency_ms = _call_once(client, chain.primary, prompt, system_prompt)
            logger.info(
                "agent=%s model=%s SUCCESS attempt=%d latency_ms=%d",
                agent_name, chain.primary, attempt_num, latency_ms,
            )
            return ModelResponse(
                text=text,
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
            # Catch-all for unexpected SDK changes or platform-specific errors.
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "agent=%s model=%s attempt=%d UNEXPECTED_FAILURE error=%s",
                agent_name, chain.primary, attempt_num, last_error,
            )

    # ── Attempt 3: FALLBACK ────────────────────────────────────────────────────
    # Primary exhausted. Log the switchover — this is the event the audit layer
    # must capture. was_fallback=True in the response carries the same signal.
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
        text, latency_ms = _call_once(client, chain.fallback, prompt, system_prompt)
        logger.info(
            "agent=%s model=%s FALLBACK_SUCCESS attempt=3 latency_ms=%d",
            agent_name, chain.fallback, latency_ms,
        )
        return ModelResponse(
            text=text,
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
