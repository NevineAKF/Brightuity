"""
shared/test_model_access.py
Brightuity — Live integration test for the model-access layer.

Tests three scenarios against the REAL APIs (requires keys in .env):
  A. Featherless happy path   — doc_auditor, primary succeeds
  B. AI/ML API happy path     — kyc_guardian, primary succeeds
  C. Failover under load      — doc_auditor primary replaced with an invalid
                                model ID, forcing two failures before the
                                fallback takes over. was_fallback must be True.

Run: python -m shared.test_model_access
  or: python shared/test_model_access.py

Requires: .env with AIMLAPI_KEY and FEATHERLESS_KEY populated.
See .env.example for the exact variable names.
"""

from __future__ import annotations

import logging
import sys
import textwrap

# ── Logging ────────────────────────────────────────────────────────────────────
# Configure before any imports that trigger module-level code.
# INFO shows each attempt; WARNING shows retries and switchover events.
logging.basicConfig(
    level=logging.INFO,
    format="  %(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)   # suppress SDK HTTP noise

# ── Project imports ────────────────────────────────────────────────────────────
import shared.config as _config_module
from shared.config import AGENT_MODEL_CHAINS, ModelChain, Platform
from shared.call_agent_model import ModelResponse, ModelUnavailableError, call_agent_model

# ── Helpers ────────────────────────────────────────────────────────────────────

_SEP   = "─" * 68
_SEP2  = "═" * 68
_PASS  = "✓"
_FAIL  = "✗"

def _banner(title: str) -> None:
    print(f"\n{_SEP}")
    print(f"  {title}")
    print(_SEP)

def _show_response(r: ModelResponse) -> None:
    preview = textwrap.shorten(r.text, width=120, placeholder=" …")
    print(f"  model_used   : {r.model_used}")
    print(f"  platform     : {r.platform}")
    print(f"  was_fallback : {r.was_fallback}")
    print(f"  attempts     : {r.attempts}")
    print(f"  latency_ms   : {r.latency_ms}")
    print(f"  text preview : {preview}")

def _check(condition: bool, label: str) -> bool:
    icon = _PASS if condition else _FAIL
    print(f"  {icon}  {label}")
    return condition

# ── Test prompt (trivial so it costs minimal tokens) ──────────────────────────

_PROMPT = (
    "Reply in exactly one sentence: what is the most fundamental principle "
    "of AML (Anti-Money Laundering) compliance?"
)

# ── Tests ──────────────────────────────────────────────────────────────────────

def test_a_featherless_happy_path() -> bool:
    """
    Call doc_auditor (Featherless) with a trivial prompt.
    Proves: Featherless connectivity + primary-success happy path.
    """
    _banner("TEST A  |  Featherless happy path  (agent: doc_auditor)")
    chain = AGENT_MODEL_CHAINS["doc_auditor"]
    print(f"  primary  : {chain.primary}")
    print(f"  fallback : {chain.fallback}")
    print(f"  platform : {chain.platform.value}")
    print()

    try:
        r = call_agent_model("doc_auditor", _PROMPT)
        _show_response(r)
        print()
        ok = True
        ok &= _check(r.was_fallback is False, "was_fallback is False (primary succeeded)")
        ok &= _check(r.attempts == 1, f"attempts == 1 (got {r.attempts})")
        ok &= _check(len(r.text) > 10, "response is non-trivial")
        ok &= _check(r.platform == "featherless", f"platform == featherless (got {r.platform})")
        return ok
    except ModelUnavailableError as exc:
        print(f"  {_FAIL}  ModelUnavailableError: {exc}")
        return False
    except Exception as exc:
        print(f"  {_FAIL}  Unexpected error: {type(exc).__name__}: {exc}")
        return False


def test_b_aimlapi_happy_path() -> bool:
    """
    Call kyc_guardian (AI/ML API) with a trivial prompt.
    Proves: AI/ML API connectivity + primary-success happy path.
    """
    _banner("TEST B  |  AI/ML API happy path  (agent: kyc_guardian)")
    chain = AGENT_MODEL_CHAINS["kyc_guardian"]
    print(f"  primary  : {chain.primary}")
    print(f"  fallback : {chain.fallback}")
    print(f"  platform : {chain.platform.value}")
    print()

    try:
        r = call_agent_model("kyc_guardian", _PROMPT)
        _show_response(r)
        print()
        ok = True
        ok &= _check(r.was_fallback is False, "was_fallback is False (primary succeeded)")
        ok &= _check(r.attempts == 1, f"attempts == 1 (got {r.attempts})")
        ok &= _check(len(r.text) > 10, "response is non-trivial")
        ok &= _check(r.platform == "aimlapi", f"platform == aimlapi (got {r.platform})")
        return ok
    except ModelUnavailableError as exc:
        print(f"  {_FAIL}  ModelUnavailableError: {exc}")
        return False
    except Exception as exc:
        print(f"  {_FAIL}  Unexpected error: {type(exc).__name__}: {exc}")
        return False


def test_c_primary_failure_triggers_fallback() -> bool:
    """
    Inject an invalid primary model ID for doc_auditor, then call it.
    The engine must:
      - Fail attempt 1 (bad model ID → API error)
      - Fail attempt 2 (same bad model ID → API error, silent retry)
      - Log the SWITCHOVER event
      - Succeed on attempt 3 with the real fallback model
      - Return was_fallback=True, attempts=3

    Proves: failover is real against live APIs, not just theoretical.
    """
    _banner("TEST C  |  Primary failure → fallback  (agent: doc_auditor)")

    original_chain = AGENT_MODEL_CHAINS["doc_auditor"]
    bad_primary = "invalid-model-xyz-does-not-exist-brightuity-test"

    broken_chain = ModelChain(
        primary=bad_primary,
        fallback=original_chain.fallback,   # real model, should succeed
        platform=original_chain.platform,
    )

    print(f"  real primary    : {original_chain.primary}")
    print(f"  injected bad ID : {bad_primary}")
    print(f"  real fallback   : {original_chain.fallback}")
    print()
    print("  Injecting bad primary and calling... (expect 2 failures then fallback)")
    print()

    _config_module.AGENT_MODEL_CHAINS["doc_auditor"] = broken_chain
    try:
        r = call_agent_model("doc_auditor", _PROMPT)
        _show_response(r)
        print()
        ok = True
        ok &= _check(r.was_fallback is True,  "was_fallback is True  (failover triggered)")
        ok &= _check(r.attempts == 3,          f"attempts == 3         (got {r.attempts})")
        ok &= _check(r.model_used == original_chain.fallback,
                     f"model_used == fallback ({original_chain.fallback})")
        ok &= _check(len(r.text) > 10,         "fallback response is non-trivial")
        return ok
    except ModelUnavailableError as exc:
        # Means the fallback also failed — typically the real fallback model is
        # unavailable or needs verification. Print clearly so the user knows.
        print(f"  {_FAIL}  ModelUnavailableError (fallback also failed): {exc}")
        print()
        print("  This means the fallback model is unreachable or the model ID needs")
        print("  updating. Check FEATHERLESS_KEY and the fallback model ID in config.py.")
        return False
    except Exception as exc:
        print(f"  {_FAIL}  Unexpected error: {type(exc).__name__}: {exc}")
        return False
    finally:
        # Always restore the real chain, even if the test raises.
        _config_module.AGENT_MODEL_CHAINS["doc_auditor"] = original_chain


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")

    print()
    print(_SEP2)
    print("  BRIGHTUITY · Model-Access Layer · Integration Test")
    print("  Requires: .env with AIMLAPI_KEY and FEATHERLESS_KEY")
    print(_SEP2)

    results: dict[str, bool] = {}
    results["A — Featherless happy path"] = test_a_featherless_happy_path()
    results["B — AI/ML API happy path"]   = test_b_aimlapi_happy_path()
    results["C — Primary failure→fallback"] = test_c_primary_failure_triggers_fallback()

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print(_SEP2)
    print("  SUMMARY")
    print(_SEP2)
    all_passed = True
    for name, passed in results.items():
        icon = _PASS if passed else _FAIL
        status = "PASSED" if passed else "FAILED"
        print(f"  {icon}  {name:<38}  {status}")
        all_passed = all_passed and passed

    print()
    if all_passed:
        print("  All 3 tests passed. Model-access layer is production-ready.")
    else:
        print("  One or more tests failed. Check logs above for details.")
        print("  Common causes: wrong model IDs, missing/invalid API keys.")
    print(_SEP2)
    print()
    sys.exit(0 if all_passed else 1)
