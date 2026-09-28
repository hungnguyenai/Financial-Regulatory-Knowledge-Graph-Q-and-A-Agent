# FIN-C2-182 — Unit Tests: PostProcessNode (OutputValidate S-3 + DecisionTraceAudit S-4)

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.post_process_node import PostProcessNode


def _state(**kw):
    base = {
        "correlation_id": "test-correlation", "session_id": "test-session",
        "trace_id": "test-trace", "node_history": [], "error_log": [],
    }
    base.update(kw)
    return base


def _answered_state():
    return _state(
        disposition="ANSWERED",
        kb_version_manifest=["FATF Recommendation 16 (Travel Rule) (2026-07-01)"],
        cited_answer="Per FATF-R16-2025-11, the Travel Rule requires ... (KB version 2026-07-01)",
        retrieved_passages=[
            {"citation": "FATF-R16-2025-11", "regime": "FATF Recommendation 16 (Travel Rule)",
             "effective_date": "2025-11-01", "jurisdiction": "Global", "kb_date": "2026-07-01",
             "snippet": "..."},
        ],
    )


class TestPostProcessNodeDisclaimerAndAudit:
    def test_disclaimer_appended(self):
        r = PostProcessNode().execute(_answered_state())
        assert r["status"] == AgentStatus.SUCCESS.value
        assert "informational" in r["validated_answer"].lower()
        assert "not legal advice" in r["validated_answer"].lower()

    def test_citation_count_computed(self):
        r = PostProcessNode().execute(_answered_state())
        assert r["citation_count"] == 1

    def test_error_state_short_circuits(self):
        r = PostProcessNode().execute(_state(status=AgentStatus.ERROR.value))
        assert r == {}


class TestPostProcessNodeS3Grounding:
    def test_uncited_answer_blocked(self):
        node = PostProcessNode()
        result = {"validated_answer": "The Travel Rule applies here.", "status": AgentStatus.SUCCESS.value}
        raised = False
        try:
            node._extra_security_gate_output(result)
        except RuntimeError:
            raised = True
        assert raised, "S-3 ResponseValidate must block an answer with no regulatory citation"

    def test_cited_answer_passes(self):
        node = PostProcessNode()
        result = {
            "validated_answer": "Per FATF-R16-2025-11 (KB version 2026-07-01), ...",
            "status": AgentStatus.SUCCESS.value,
        }
        node._extra_security_gate_output(result)  # must not raise

    def test_credential_pattern_blocked(self):
        node = PostProcessNode()
        result = {"validated_answer": "the password is hunter2 (FATF-R16-2025-11)",
                  "status": AgentStatus.SUCCESS.value}
        raised = False
        try:
            node._extra_security_gate_output(result)
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block a credential pattern from reaching output"

    def test_legal_advice_certainty_blocked(self):
        node = PostProcessNode()
        result = {"validated_answer": "This is legal advice (FATF-R16-2025-11).",
                  "status": AgentStatus.SUCCESS.value}
        raised = False
        try:
            node._extra_security_gate_output(result)
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block unsupported legal-certainty phrasing"


class TestPostProcessNodeTrust:
    def test_internal_trust_declared(self):
        assert PostProcessNode.required_trust_level == TrustLevel.INTERNAL
