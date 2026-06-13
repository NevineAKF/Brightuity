# Purpose: Universal model-call wrapper used by all LLM agents.
# Implements the failover chain: try PRIMARY → retry PRIMARY → switch to FALLBACK → escalate.
# Logs every switchover (agent, models, error, timestamp) to the audit record.
