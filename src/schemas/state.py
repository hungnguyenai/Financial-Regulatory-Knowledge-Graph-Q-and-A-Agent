"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict (see ADR-005 for the prohibited alternatives).
# LangGraph checkpoints use msgpack serialization; non-flat objects cause silent
# corruption. Extend AgentState with agent-specific fields only. Do NOT add
# credentials, secrets, or other non-flat objects.

from typing import Optional

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """State for FIN-C2-182 Financial Regulatory Knowledge Graph Q&A Agent (VectorRAG).

    Inherited fields from AgentState (do not re-declare):
      user_input, status, session_id, node_history, error_log,
      validated_input, hitl_*, trace_id, correlation_id, schema_version,
      response_metadata, trust_level, formatted_output, result

    A cross-regime regulatory question (free text) arrives as user_input. All fields
    below are flat, msgpack-safe primitives (ADR-005) — no credentials, no connection
    strings. Only regulatory citations + versioned corpus snippets are retained; no
    customer/transaction PII is ever part of this agent's domain.
    """

    # ── pre_process outputs (InputValidate + CircumventionScreen) ────────
    sanitized_query: Optional[str]
    # True when the query was rejected as circumvention/loophole-intent (S-2 domain gate).
    circumvention_flagged: Optional[bool]

    # ── main outputs (VersionedRegulatoryRetrieve + CitedSynthesis) ──────
    # Retrieved passages: {citation, regime, effective_date, jurisdiction, kb_date, snippet}.
    # NON-SUPPRESSIBLE citation trail — downstream nodes must never empty it (an answer
    # must stay grounded in the regulatory basis it cites).
    retrieved_passages: Optional[list[dict[str, str | int | float | bool | None]]]
    # Versioned KB manifest — one entry per regime cited (S-4 audit + data-currency).
    kb_version_manifest: Optional[list[str]]
    # ANSWERED | NO_MATCH — NO_MATCH forces a "no current regulatory basis found" reply,
    # never an affirmative synthesis without grounding.
    disposition: Optional[str]
    # Draft cited answer (pre-S-3) — effective-date + jurisdiction + compliance action.
    cited_answer: Optional[str]

    # ── post_process outputs (OutputValidate S-3 + DecisionTraceAudit S-4) ─
    validated_answer: Optional[str]  # final answer incl. informational disclaimer
    citation_count: Optional[int]  # number of distinct regulatory citations in the answer
