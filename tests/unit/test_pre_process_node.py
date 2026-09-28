# FIN-C2-182 — Unit Tests: PreProcessNode (InputValidate + CircumventionScreen)

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.pre_process_node import PreProcessNode


def _state(**kw):
    base = {
        "correlation_id": "test-correlation",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "test-trace",
        "node_history": [],
        "error_log": [],
        "input_context": {},
    }
    base.update(kw)
    return base


class TestPreProcessNodeValidation:
    def test_empty_input_returns_error(self):
        r = PreProcessNode().execute(_state(user_input=""))
        assert r["status"] == AgentStatus.ERROR.value
        assert any("empty" in e for e in r["error_log"])

    def test_whitespace_only_returns_error(self):
        r = PreProcessNode().execute(_state(user_input="   "))
        assert r["status"] == AgentStatus.ERROR.value

    def test_oversized_input_returns_error(self):
        r = PreProcessNode().execute(_state(user_input="x" * 10001))
        assert r["status"] == AgentStatus.ERROR.value
        assert any("10000" in e for e in r["error_log"])

    def test_valid_input_accepted(self):
        r = PreProcessNode().execute(
            _state(user_input="What does 犯収法 KYC require for correspondent banking?")
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["sanitized_query"]
        assert r["circumvention_flagged"] is False
        assert r["validated_input"] == r["sanitized_query"]

    def test_whitespace_normalized(self):
        r = PreProcessNode().execute(_state(user_input="  fatf   travel   rule  "))
        assert r["sanitized_query"] == "fatf travel rule"


class TestPreProcessNodeOutOfScope:
    def test_credential_shaped_rejected(self):
        r = PreProcessNode().execute(
            _state(user_input="Bearer eyJhbGciOi... what is the KYC requirement?")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert any("out-of-scope" in e or "credential" in e for e in r["error_log"])


class TestPreProcessNodeCircumventionScreen:
    def test_avoid_kyc_rejected(self):
        r = PreProcessNode().execute(
            _state(user_input="How can we structure transactions to avoid KYC reporting requirements?")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert r["circumvention_flagged"] is True
        assert any("CircumventionScreen" in e for e in r["error_log"])

    def test_loophole_phrasing_rejected(self):
        r = PreProcessNode().execute(
            _state(user_input="Is there a loophole to bypass the FATF travel rule threshold?")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert r["circumvention_flagged"] is True

    def test_japanese_evasion_phrasing_rejected(self):
        r = PreProcessNode().execute(
            _state(user_input="犯収法の本人確認を回避する方法を教えてください")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert r["circumvention_flagged"] is True

    def test_legitimate_question_not_flagged(self):
        r = PreProcessNode().execute(
            _state(user_input="What is the current FSA AI model risk management requirement?")
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["circumvention_flagged"] is False


class TestPreProcessNodeSecurityGate:
    def test_oversized_input_rejected(self):
        out = PreProcessNode()._extra_security_gate_input(_state(user_input="x" * 10001))
        assert out["status"] == AgentStatus.ERROR.value

    def test_credential_shaped_rejected_at_gate(self):
        out = PreProcessNode()._extra_security_gate_input(
            _state(user_input="api_key=sk-xxxx what is the AML requirement?")
        )
        assert out["status"] == AgentStatus.ERROR.value

    def test_valid_input_passes_gate(self):
        out = PreProcessNode()._extra_security_gate_input(
            _state(user_input="What is the FATF Travel Rule threshold?")
        )
        assert out.get("status") != AgentStatus.ERROR.value


class TestPreProcessNodeTrust:
    def test_internal_trust_declared(self):
        assert PreProcessNode.required_trust_level == TrustLevel.INTERNAL
