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

from src.services.service import (
    ANSWERED,
    NO_MATCH,
    retrieve_passages,
    synthesize_answer,
)

from shared.utils.audit_logger import emit_trace_event


class MainNode(FunctionNode):
    """VersionedRegulatoryRetrieve + CitedSynthesis.

    Retrieves versioned passages from the FSA AI MRM / 犯収法 / FATF / FISC corpus
    (a query may match multiple regimes — the cross-regime reconciliation case) and
    synthesises a cited draft answer reconciling effective dates and jurisdiction
    scope. `retrieved_passages` is written once here — NON-SUPPRESSIBLE (the citation
    trail); downstream nodes must never filter or empty it.

    The versioned kb_client (production) or the deterministic corpus (CI) is used. If
    an injected client (or the deterministic corpus) yields no passages, return a
    `NO_MATCH` disposition and NEVER synthesise an ungrounded answer.

    S-1: INTERNAL.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def __init__(self, kb_client: Any = None) -> None:
        super().__init__()
        self._kb_client = kb_client

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR, AgentStatus.ERROR.value):
            return {}

        emit_trace_event("regulatory_retrieve_start", {"node": "MainNode"}, state)

        query = state.get("sanitized_query") or state.get("validated_input") or ""

        try:
            passages = retrieve_passages(query, kb_client=self._kb_client)
        except Exception as e:  # noqa: BLE001
            emit_trace_event("regulatory_retrieve_error", {"error": str(e)}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": state.get("error_log", []) + [f"MainNode: {e}"],
            }

        # Readiness gate: no matched passages must never synthesise an ungrounded
        # answer — force NO_MATCH rather than an affirmative reply.
        if not passages:
            emit_trace_event("no_regulatory_match", {"query_length": len(query)}, state)
            return {
                "disposition": NO_MATCH,
                "retrieved_passages": [],
                "kb_version_manifest": [],
                "status": AgentStatus.ERROR.value,
                "error_log": state.get("error_log", [])
                + [
                    "MainNode: no_regulatory_match — no versioned regulatory passage matched "
                    "this query across FSA AI MRM / 犯収法 / FATF / FISC; cannot synthesise "
                    "an answer without current regulatory grounding"
                ],
            }

        for p in passages:
            emit_trace_event(
                "passage_retrieved",
                {
                    "citation": p.get("citation"),
                    "regime": p.get("regime"),
                    "effective_date": p.get("effective_date"),
                    "kb_date": p.get("kb_date"),
                },
                state,
            )

        kb_version_manifest = sorted({f"{p['regime']} ({p['kb_date']})" for p in passages})
        cited_answer = synthesize_answer(query, passages)

        emit_trace_event(
            "cited_synthesis_complete",
            {"regime_count": len(kb_version_manifest), "passage_count": len(passages)},
            state,
        )

        return {
            "retrieved_passages": passages,
            "kb_version_manifest": kb_version_manifest,
            "disposition": ANSWERED,
            "cited_answer": cited_answer,
            "status": AgentStatus.SUCCESS.value,
        }
