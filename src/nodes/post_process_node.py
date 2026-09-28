"""AgentCore Platform v1.0"""

# Node contract (agents_layer_design.md §1):
#  - Extend FunctionNode; implement execute(state) -> dict (return ONLY changed keys)
#  - Return AgentStatus enum constants — never plain strings [A1]
#  - S-1 trust declared via required_trust_level ClassVar (compliance/legal/risk staff)

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from shared.utils.audit_logger import emit_trace_event

# Credential-like patterns rejected in output (additive to the default scan).
_SENSITIVE_PATTERNS = (
    "bearer ",
    "authorization:",
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "connection_string",
    "conn_str",
)

# Unsupported legal-certainty phrasing the answer must NOT assert. This agent
# produces informational cross-regime reconciliation, never a legal determination.
_LEGAL_ADVICE_PATTERNS = (
    "this is legal advice",
    "we certify that",
    "guaranteed to be compliant",
    "this constitutes a legal opinion",
    "legally binding determination",
    "no compliance action is required",
)

# ResponseValidate — a synthesized answer MUST retain a regulatory citation marker
# so it stays grounded in the passages it cites (no unsupported claims).
_CITATION_MARKERS = ("FSA-", "AML-KYC-", "FATF-", "FISC-", "KB version")

# The non-suppressible informational disclaimer appended to every answered response.
_DISCLAIMER = (
    "\n\n---\n**This is informational regulatory reconciliation, not legal advice.** "
    "Verify against the authoritative regulatory text and consult qualified legal "
    "counsel before taking a compliance action."
)

# Sentinel used when disposition is NO_MATCH (no grounding to check).
_NO_MATCH_SENTINEL = "no_regulatory_match"

# Rendered when there is no cited_answer to validate (e.g. main_node never ran, or
# was invoked directly with a degenerate state). The grounding check below is
# skipped for this sentinel — there is nothing to cite.
_NO_ANSWER_SENTINEL = "No regulatory answer synthesized"


class PostProcessNode(FunctionNode):
    """OutputValidate (S-3) + DecisionTraceAudit (S-4).

    Responsibilities:
    - Append the non-suppressible "informational — not legal advice" disclaimer to
      every answered response.
    - S-3: block credential-like patterns; block unsupported legal-certainty
      phrasing; ResponseValidate rejects an answer that carries no regulatory
      citation (grounding requirement).
    - S-4: emit_trace_event audit record — query metadata, KB source/version
      manifest, citation count, disposition; no credentials/PII.

    S-1: INTERNAL.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR, AgentStatus.ERROR.value):
            return {}

        emit_trace_event("output_validate_start", {"node": "PostProcessNode"}, state)

        cited_answer = state.get("cited_answer") or ""
        passages = state.get("retrieved_passages") or []
        kb_version_manifest = state.get("kb_version_manifest") or []
        disposition = state.get("disposition") or _NO_MATCH_SENTINEL

        body = cited_answer if cited_answer.strip() else _NO_ANSWER_SENTINEL
        validated_answer = body + _DISCLAIMER
        citation_count = len({p.get("citation") for p in passages if p.get("citation")})

        emit_trace_event(
            "decision_trace_audit",
            {
                "disposition": disposition,
                "kb_version_manifest": kb_version_manifest,
                "citation_count": citation_count,
            },
            state,
        )

        return {
            "validated_answer": validated_answer,
            "citation_count": citation_count,
            "formatted_output": validated_answer,
            "result": validated_answer,
            "status": AgentStatus.SUCCESS.value,
        }

    # ── S-3 output gate ────────────────────────────────────────────────────

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """S-3 domain hook (runs after the default credential scan).

        Contract (FunctionNode 1.0.0): receive the execute() result dict, RETURN it;
        MAY raise to block output.
        - Block credential-like patterns / connection strings.
        - Block unsupported legal-certainty assertions.
        - ResponseValidate: a synthesized answer MUST retain a regulatory citation
          marker (grounding requirement — no unsupported regulatory claims).
        """
        for key, value in result.items():
            if not isinstance(value, str):
                continue
            lowered = value.lower()
            for pattern in _SENSITIVE_PATTERNS:
                if pattern in lowered:
                    raise RuntimeError(f"PostProcessNode S-3: sensitive pattern '{pattern}' in result['{key}']")
            for pattern in _LEGAL_ADVICE_PATTERNS:
                if pattern in lowered:
                    raise RuntimeError(
                        f"PostProcessNode S-3: unsupported legal-certainty phrasing " f"'{pattern}' in result['{key}']"
                    )

        answer = result.get("validated_answer")
        if isinstance(answer, str) and answer.strip() and _NO_ANSWER_SENTINEL not in answer:
            if not any(marker in answer for marker in _CITATION_MARKERS):
                raise RuntimeError(
                    "PostProcessNode S-3 ResponseValidate: answer carries no regulatory "
                    "citation — blocking unsupported regulatory reconciliation claim"
                )
        return result
