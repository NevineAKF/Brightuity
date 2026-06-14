"""
shared/schemas.py
Brightuity — Pydantic verdict schemas for every LLM agent.

These are the single source of truth for what each agent MUST return.
They serve two purposes simultaneously:
  1. Request-time: model_json_schema() is sent to the API in json_schema mode
     so the platform enforces the structure before we even see the response.
  2. Response-time: model_validate() validates every response before it is
     accepted as a verdict — malformed output routes to failover, not through.

Adding a new agent: add its schema here, import it in the agent's logic.py,
pass it to call_agent_model(). Nothing else in the engine needs to change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DocAuditorVerdict(BaseModel):
    """
    Output contract for the Doc Auditor agent.
    First compliance gate — document completeness and ownership-chain integrity.
    """
    verdict:      Literal["pass", "fail"]
    summary:      str
    issues_found: list[str]


class KycGuardianVerdict(BaseModel):
    """
    Output contract for the KYC Guardian agent.
    Three-verdict system: halt is a hard pipeline stop requiring human sign-off.
    """
    verdict:      Literal["pass", "fail", "halt"]
    summary:      str
    flags_raised: list[str]


class DynamicComplianceVerdict(BaseModel):
    """
    Output contract for the Dynamic Compliance agent.
    RAG-grounded regulatory opinion — citations prove grounding in retrieved law.
    """
    verdict:      Literal["pass", "fail"]
    summary:      str
    jurisdiction: str
    citations:    list[str]
    concerns:     list[str]


class StressTestVerdict(BaseModel):
    """
    Output contract for the Stress-Test Simulator agent.
    Quantitative market and liquidity risk assessment for RWA tokenisation.
    """
    verdict:      Literal["pass", "fail"]
    summary:      str
    risk_level:   Literal["low", "medium", "high", "critical"]
    risk_factors: list[str]


class AssetTokenizerVerdict(BaseModel):
    """
    Output contract for the Asset Tokenizer agent.
    Proposes the on-chain tokenisation structure for a real-world asset.
    Does not mint or issue — it produces a structure recommendation for human approval.
    """
    verdict:             Literal["pass", "fail"]
    summary:             str
    token_standard:      str     # proposed standard / class label (e.g. ERC-3643 T-REX)
    total_tokens:        int     # proposed total supply
    value_per_token_eur: float   # nominal EUR value per token
    structure_notes:     list[str]  # key parameters, assumptions, caveats
