# FIN-C2-182 — Unit Tests: MainNode (VersionedRegulatoryRetrieve + CitedSynthesis)

import inspect

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.main_node import MainNode


def _state(**kw):
    base = {
        "correlation_id": "test-correlation", "session_id": "test-session",
        "trace_id": "test-trace", "node_history": [], "error_log": [],
    }
    base.update(kw)
    return base


class TestMainNodeRetrievalAndSynthesis:
    def test_aml_kyc_query_retrieves_and_answers(self):
        r = MainNode().execute(_state(sanitized_query="What is the current 犯収法 KYC requirement?"))
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["disposition"] == "ANSWERED"
        assert r["retrieved_passages"]
        assert any(p["citation"] == "AML-KYC-2026-06" for p in r["retrieved_passages"])
        assert "AML-KYC-2026-06" in r["cited_answer"]

    def test_cross_regime_query_matches_multiple_regimes(self):
        r = MainNode().execute(
            _state(sanitized_query="Correspondent banking KYC versus FATF Recommendation 16 travel rule")
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        citations = {p["citation"] for p in r["retrieved_passages"]}
        assert "AML-KYC-2026-06" in citations
        assert "FATF-R16-2025-11" in citations
        assert len(r["kb_version_manifest"]) == 2

    def test_unmatched_query_forces_no_match(self):
        r = MainNode().execute(_state(sanitized_query="What is the weather today?"))
        assert r["status"] == AgentStatus.ERROR.value
        assert r["disposition"] == "NO_MATCH"
        assert r["retrieved_passages"] == []
        assert any("no_regulatory_match" in e for e in r["error_log"])

    def test_error_state_short_circuits(self):
        r = MainNode().execute(_state(status=AgentStatus.ERROR.value))
        assert r == {}


class TestMainNodeKBClientInjection:
    class _EmptyKB:
        def retrieve(self, query):
            return []

    def test_empty_injected_kb_forces_no_match_never_answers(self):
        r = MainNode(kb_client=self._EmptyKB()).execute(
            _state(sanitized_query="犯収法 KYC requirement")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert r["disposition"] == "NO_MATCH"
        assert "cited_answer" not in r  # never issues an ungrounded answer


class TestMainNodeContract:
    def test_execute_method_signature(self):
        assert hasattr(MainNode, "execute"), "MainNode must implement execute()"
        sig = inspect.signature(MainNode.execute)
        params = list(sig.parameters.keys())
        assert len(params) >= 2
        assert params[1] == "state"
        assert "_invoke_impl" not in MainNode.__dict__

    def test_internal_trust_declared(self):
        assert MainNode.required_trust_level == TrustLevel.INTERNAL
