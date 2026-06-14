"""
shared/config.py
Brightuity — Central configuration for the model-access layer.

Single source of truth for:
  - Platform definitions (base URL, env-var key name)
  - Per-agent model chains (primary model, fallback model, platform)
  - Global call parameters (timeout)

This module knows NOTHING about agents, verdicts, Band, or business logic.
It is pure configuration: names, URLs, and model IDs.

To add a new model or change a model ID: edit the AGENT_MODEL_CHAINS dict.
To add a new platform: add an entry to PLATFORMS.
Nothing in call_agent_model.py needs to change for either operation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv

# Load .env from the project root (two levels up from shared/).
# In production (Docker) environment variables are injected directly —
# load_dotenv() is a no-op when the vars are already set.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))


# ── Platform enum ──────────────────────────────────────────────────────────────

class Platform(str, Enum):
    """
    Model-serving platforms. str base class so the value is usable directly
    as a log string and JSON field without .value access.
    """
    AIMLAPI = "aimlapi"         # AI/ML API — sensitive agents (Orchestrator, KYC, Compliance)
    FEATHERLESS = "featherless" # Featherless — analytical agents (Doc, Risk, Tokenizer)


# ── Platform configuration ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PlatformConfig:
    """
    Connection parameters for one model-serving platform.
    Both platforms expose an OpenAI-compatible /v1/chat/completions endpoint,
    so the same OpenAI SDK client works for both — only base_url and key differ.
    """
    base_url: str
    env_key_name: str   # name of the environment variable holding the API key

    @property
    def api_key(self) -> str:
        """
        Read the API key from the environment at call time.
        Raises EnvironmentError loudly if the variable is missing or empty,
        so misconfiguration surfaces immediately rather than silently producing
        authentication errors buried in API call logs.
        """
        key = os.getenv(self.env_key_name, "").strip()
        if not key:
            raise EnvironmentError(
                f"\n"
                f"  Missing API key for platform '{self.env_key_name}'.\n"
                f"  Required environment variable: {self.env_key_name}\n"
                f"  Fix: copy .env.example → .env and populate '{self.env_key_name}'.\n"
                f"  In Docker/production: inject via environment, not .env file."
            )
        return key


# ── Agent model chain ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelChain:
    """
    Primary and fallback model specification for one LLM agent.

    Both models run on the same platform. The only exception in the blueprint
    is KYC Guardian whose fallback crosses model families (Claude → GPT) but
    stays on the same platform (AI/ML API serves both).
    """
    primary: str     # model ID string as expected by the platform's /v1 endpoint
    fallback: str    # model ID used after two consecutive primary failures
    platform: Platform


# ── Platform registry ──────────────────────────────────────────────────────────

PLATFORMS: dict[Platform, PlatformConfig] = {
    Platform.AIMLAPI: PlatformConfig(
        # AI/ML API — OpenAI-compatible multi-model gateway.
        # Hosts Anthropic (Claude), Google (Gemini), OpenAI (GPT), and others.
        # Docs: https://api.aimlapi.com  |  Model list: https://api.aimlapi.com/models
        base_url="https://api.aimlapi.com/v1",
        env_key_name="AIMLAPI_KEY",
    ),
    Platform.FEATHERLESS: PlatformConfig(
        # Featherless — OpenAI-compatible serverless inference for open-weight models.
        # Uses Hugging Face model IDs (org/model-name convention).
        # Docs: https://featherless.ai  |  Model list: https://featherless.ai/models
        base_url="https://api.featherless.ai/v1",
        env_key_name="FEATHERLESS_KEY",
    ),
}


# ── Agent model chains (blueprint section 3) ───────────────────────────────────
#
# Model IDs reflect the blueprint spec as of June 2026.
# ⚠ VERIFY each model ID against the platform's live model catalog before
# running in production — IDs can change when providers release new versions.
#
# To change a model (e.g. promote a fallback after a primary is deprecated):
# edit ONE line here. Nothing else in the codebase needs to change.
# This single-line change is how Gemini 3.1 Pro was promoted to primary for
# Dynamic Compliance on 2026-06-12 after Fable 5 was suspended — live proof.

AGENT_MODEL_CHAINS: dict[str, ModelChain] = {

    # ── Orchestrator (AI/ML API) ────────────────────────────────────────────
    # CrewAI-based. Needs the strongest reasoning for dynamic case routing.
    "orchestrator": ModelChain(
        primary="claude-opus-4-8",
        fallback="claude-sonnet-4-6",
        platform=Platform.AIMLAPI,
    ),

    # ── Doc Auditor (Featherless) ───────────────────────────────────────────
    # First gate. Examines deeds, extracts fields, flags document issues.
    # "Qwen 3.6" → Qwen/Qwen3.6-27B; "Gemma-4" → google/gemma-4-E4B-it.
    # Verified non-gated on Featherless 2026-06-14.
    "doc_auditor": ModelChain(
        primary="Qwen/Qwen3.6-27B",
        fallback="google/gemma-4-E4B-it",
        platform=Platform.FEATHERLESS,
    ),

    # ── KYC Guardian (AI/ML API) ────────────────────────────────────────────
    # Most sensitive agent. Cross-family fallback (Claude → GPT) = platform
    # redundancy: if Anthropic models degrade, OpenAI models take over.
    # Both are served by AI/ML API — same endpoint, different model IDs.
    "kyc_guardian": ModelChain(
        primary="claude-opus-4-8",
        fallback="gpt-4o",
        platform=Platform.AIMLAPI,
    ),

    # ── Dynamic Compliance (AI/ML API) ──────────────────────────────────────
    # LangChain + RAG. Long-context model essential (MiCA ≈ 200 pages).
    # Primary was Claude Fable 5; promoted to Gemini on 2026-06-12 after
    # export-control suspension. gemini-3.1-pro 404'd on AI/ML API →
    # google/gemini-2.5-pro confirmed working 2026-06-14. Two real failovers,
    # zero downtime — live proof the failover engine works exactly as designed.
    "dynamic_compliance": ModelChain(
        primary="google/gemini-2.5-pro",
        fallback="gpt-4o",
        platform=Platform.AIMLAPI,
    ),

    # ── Stress-Test Simulator (Featherless) ─────────────────────────────────
    # Quantitative risk analysis: fair value, risk score 0-100, scenario stress.
    # "DeepSeek-V4-Pro" → deepseek-ai/DeepSeek-V4-Pro (exact blueprint match).
    # Verified non-gated on Featherless 2026-06-14.
    "stress_test": ModelChain(
        primary="deepseek-ai/DeepSeek-V4-Pro",
        fallback="Qwen/Qwen3.6-27B",
        platform=Platform.FEATHERLESS,
    ),

    # ── Asset Tokenizer (Featherless) ───────────────────────────────────────
    # Designs ERC-3643 token structure: supply, unit price, transfer restrictions.
    # "Kimi-K2.6" → moonshotai/Kimi-K2.6; "GLM 4.6" → zai-org/GLM-4.6.
    # Verified non-gated on Featherless 2026-06-14.
    "asset_tokenizer": ModelChain(
        primary="moonshotai/Kimi-K2.6",
        fallback="zai-org/GLM-4.6",
        platform=Platform.FEATHERLESS,
    ),

    # consensus_signer is intentionally absent — it uses ECDSA, no LLM.
}


# ── Global call parameters ─────────────────────────────────────────────────────

CALL_TIMEOUT_SECONDS: float = 60.0   # per-attempt timeout (extended for Gemini 2.5 Pro thinking)
MAX_TOKENS_DEFAULT: int = 4096        # thinking models (Gemini 2.5 Pro) burn tokens before output
