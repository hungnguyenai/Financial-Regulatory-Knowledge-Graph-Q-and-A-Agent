# FIN-C2-182 — Proof-of-Boundary: domain-specific boundary verification
#
# PB-1: emit_trace_event() in every execute() body (S-4 audit)
# PB-6: _security_gate_* not overridden; _extra_* hooks callable; FunctionNode subclasses
# Domain: retrieved_passages NON-SUPPRESSIBLE (citation trail); uncited answers blocked (S-3);
#         a circumvention/loophole-intent query is rejected BEFORE retrieval (zero KB calls);
#         an unmatched query forces NO_MATCH (never an affirmative ungrounded synthesis).
#
# Graph-level coverage: isolated node-level unit tests can pass while the REAL
# Graph.invoke() path (with the framework's own built-in S-2 PII-masking pipeline in front of
# every node) silently defeats a domain gate. These tests drive the SAME real path every
# production caller uses: Graph(config=...).compile().invoke(...) — never a manually composed
# node chain, never .run().
#
# CI-safe: fully deterministic offline (no live API/vector store).

import inspect

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext, TrustLevel

from src.nodes.pre_process_node import PreProcessNode
from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.graph.graph import Graph
from src.schemas.state import State


def _state(**kw):
    base = {
        "correlation_id": "pb-corr", "session_id": "pb-session", "thread_id": "pb-thread",
        "trace_id": "pb-trace", "node_history": [], "error_log": [], "input_context": {},
    }
    base.update(kw)
    return base


class TestPB1TraceEmission:
    def test_pre_process_emits(self):
        assert "emit_trace_event" in inspect.getsource(PreProcessNode.execute)

    def test_main_emits(self):
        assert "emit_trace_event" in inspect.getsource(MainNode.execute)

    def test_post_process_emits(self):
        assert "emit_trace_event" in inspect.getsource(PostProcessNode.execute)


class TestPB6SecurityGates:
    def test_gate_input_not_overridden(self):
        assert "_security_gate_input" not in PreProcessNode.__dict__

    def test_gate_output_not_overridden(self):
        assert "_security_gate_output" not in PostProcessNode.__dict__

    def test_extra_hooks_callable(self):
        assert callable(getattr(PreProcessNode(), "_extra_security_gate_input", None))
        assert callable(getattr(PostProcessNode(), "_extra_security_gate_output", None))

    def test_all_nodes_are_functionnode(self):
        for cls in (PreProcessNode, MainNode, PostProcessNode):
            assert issubclass(cls, FunctionNode), f"{cls.__name__} must extend FunctionNode"


class TestRetrievedPassagesNonSuppressible:
    def _state_with_passages(self):
        return _state(
            disposition="ANSWERED",
            kb_version_manifest=["FATF Recommendation 16 (Travel Rule) (2026-07-01)"],
            cited_answer="Per FATF-R16-2025-11 (KB version 2026-07-01), ...",
            retrieved_passages=[
                {"citation": "FATF-R16-2025-11", "regime": "FATF Recommendation 16 (Travel Rule)",
                 "effective_date": "2025-11-01", "jurisdiction": "Global", "kb_date": "2026-07-01",
                 "snippet": "..."},
            ],
        )

    def test_post_process_does_not_touch_retrieved_passages(self):
        result = PostProcessNode().execute(self._state_with_passages())
        assert "retrieved_passages" not in result, (
            "PostProcessNode must not rewrite/empty the non-suppressible retrieved_passages"
        )
        assert result["status"] == AgentStatus.SUCCESS.value


class TestNoMatchNeverSynthesises:
    class _EmptyKB:
        def retrieve(self, query):
            return []

    def test_empty_kb_forces_error_never_answered(self):
        r = MainNode(kb_client=self._EmptyKB()).execute(
            _state(sanitized_query="what is the current inflation rate")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert "cited_answer" not in r  # never issues an ungrounded synthesis
        assert any("no_regulatory_match" in e for e in r["error_log"])


class TestGraphLevelInputGate:
    """Graph-level Proof-of-Boundary — sibling-incident follow-up.

    Drives real-graph verification: FIN-C2-182's own gates
    (out-of-scope/credential-shaped rejection + CircumventionScreen in
    PreProcessNode) are exercised through `Graph(config={"kb_client": ...})
    .compile().invoke(...)` — the SAME real path production uses — with an
    instrumented spy KB client injected exactly the way `Graph.register_nodes()`
    wires it into `MainNode(kb_client=...)`.

    Also empirically proves the specific HCR-class hazard does NOT apply here:
    `is_circumvention_intent` (src/services/service.py) and the pre_process
    out-of-scope markers are 100% phrase/keyword based — none key off a
    digit-shaped pattern — so the framework's built-in PII-masking of a long
    digit run can neither defeat an intended rejection nor corrupt a legitimate
    retrieval/synthesis. Both directions proved empirically below, not assumed.
    """

    class _SpyKBClient:
        """Fake versioned regulatory KB client implementing the real interface
        consumed by `services.service.retrieve_passages` (`retrieve(query) ->
        list[dict]`, exactly as looked up and called from inside
        `MainNode.execute()` via `self._kb_client`). Records every call so the
        test can assert zero retrieval on a rejected path.
        """

        def __init__(self):
            self.calls: list[str] = []

        def retrieve(self, query: str):
            self.calls.append(query)
            return [{
                "citation": "SPY-KB-001", "regime": "Spy Regulatory Index",
                "effective_date": "2026-07-01", "jurisdiction": "Global",
                "kb_date": "2026-07-15", "snippet": "spy regulatory evidence snippet",
            }]

    @staticmethod
    def _build_graph(kb_client):
        graph = Graph(config={"kb_client": kb_client})
        graph.compile()
        return graph

    @staticmethod
    def _ctx(session_id: str) -> InvocationContext:
        # All three FIN-C2-182 nodes declare required_trust_level = INTERNAL
        # (authorized compliance/legal/risk staff); use that level so the negative
        # assertions below are conditioned on the domain gates, not an S-1 denial.
        return InvocationContext(
            session_id=session_id,
            caller_trust_level=TrustLevel.INTERNAL,
            caller_id="pb-graph-test",
        )

    # ── negative paths: rejection must survive the REAL graph wiring ────────

    def test_graph_invoke_circumvention_rejected_zero_kb_retrieval(self):
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "How can we structure our wire transfers to avoid KYC reporting requirements?",
            ctx=self._ctx("pb-graph-circumvention"),
        )

        assert result["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value), result
        assert not result.get("output"), result
        assert "cited_answer" not in result, (
            "a circumvention/loophole-intent input must never reach VersionedRegulatoryRetrieve"
        )
        assert spy.calls == [], (
            f"Real Graph.invoke() reached regulatory retrieval (kb_client.retrieve) "
            f"for a circumvention-intent input — calls: {spy.calls}"
        )
        # route() sends ERROR straight to finalize — post_process must never run.
        assert "PostProcessNode" not in result.get("node_history", []), result.get("node_history")

    def test_graph_invoke_out_of_scope_rejected_zero_kb_retrieval(self):
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "Bearer eyJhbGciOiJIUzI1NiJ9.xxx — what is the KYC requirement?",
            ctx=self._ctx("pb-graph-outofscope"),
        )

        assert result["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value), result
        assert not result.get("output"), result
        assert spy.calls == [], (
            f"Real Graph.invoke() reached regulatory retrieval for a "
            f"credential-shaped/out-of-scope input — calls: {spy.calls}"
        )
        assert "PostProcessNode" not in result.get("node_history", []), result.get("node_history")

    # ── positive control: proves the negative assertions aren't vacuous ─────

    def test_graph_invoke_positive_control_legitimate_query_reaches_kb_client(self):
        """Same real Graph, same real (injected) kb_client, same real .invoke()
        entry point — proves the negative tests above are conditioned on the
        real domain-gate outcome, and not on retrieval being unreachable/broken
        through the graph wiring in general."""
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "What does the current 犯収法 KYC requirement demand for correspondent banking?",
            ctx=self._ctx("pb-graph-positive"),
        )

        assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value), result
        assert spy.calls == [
            "What does the current 犯収法 KYC requirement demand for correspondent banking?"
        ], spy.calls
        assert "SPY-KB-001" in str(result.get("output")), result
        assert "informational" in str(result.get("output")).lower()
        assert "PostProcessNode" in result.get("node_history", [])
        assert "MainNode" in result.get("node_history", [])

    # ── NO_MATCH path: must never synthesise through the real graph ─────────

    def test_graph_invoke_unmatched_query_never_synthesises(self):
        class _EmptyKB:
            def retrieve(self, query):
                return []

        graph = self._build_graph(_EmptyKB())

        result = graph.invoke(
            "What is the weather forecast for tomorrow?",
            ctx=self._ctx("pb-graph-nomatch"),
        )

        assert result["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value), result
        assert not result.get("output"), result
        assert "PostProcessNode" not in result.get("node_history", [])

    # ── HCR-class hazard: built-in PII masking must not corrupt FIN's OWN gate ──

    def test_graph_invoke_pii_shaped_value_does_not_defeat_legitimate_answer(self):
        """A legitimate, in-scope question that also carries a PII-shaped long
        digit run (e.g. a case reference number) must NOT be spuriously rejected
        merely because the built-in S-2 scan masks that digit run to `[MASKED]`
        before PreProcessNode.execute() ever sees it — FIN's own circumvention/
        retrieval logic is phrase-based and must survive intact."""
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "Case reference 123456789012 — what is the FATF Travel Rule threshold "
            "for correspondent banking?",
            ctx=self._ctx("pb-graph-pii-legitimate"),
        )
        assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value), result
        assert spy.calls, (
            "built-in PII masking of the digit run must not have swallowed the "
            f"FATF Travel Rule retrieval signal: {result}"
        )

    def test_graph_invoke_pii_masking_does_not_defeat_circumvention_rejection(self):
        """Empirically confirm FIN's own CircumventionScreen trigger is
        phrase-based, not digit-shape-based — unlike a detector whose ONLY
        signal for one input is a digit-shape regex the built-in masker also
        matches (the HCR incident class). Here the rejection phrase is
        deliberately paired with a maskable digit run; if FIN's detection
        secretly depended on the (now-masked) digits surviving, this would flip
        from ERROR to SUCCESS — it must not."""
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "Reference number 123456789012 — how can we structure transfers to "
            "avoid KYC reporting requirements?",
            ctx=self._ctx("pb-graph-pii-circumvention"),
        )

        assert result["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value), (
            "PII-shaped-value masking of the digit run must not have defeated the "
            f"phrase-based circumvention-intent rejection: {result}"
        )
        assert spy.calls == [], spy.calls
        assert "PostProcessNode" not in result.get("node_history", [])


class TestS3Grounding:
    def test_uncited_answer_blocked(self):
        node = PostProcessNode()
        result = {"validated_answer": "The Travel Rule applies to this transfer.",
                  "status": AgentStatus.SUCCESS.value}
        try:
            node._extra_security_gate_output(result)
            raised = False
        except RuntimeError:
            raised = True
        assert raised, "S-3 ResponseValidate must block an answer with no regulatory citation"

    def test_credential_pattern_blocked(self):
        node = PostProcessNode()
        result = {"validated_answer": "the password is hunter2 (FATF-R16-2025-11)",
                  "status": AgentStatus.SUCCESS.value}
        try:
            node._extra_security_gate_output(result)
            raised = False
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block a credential pattern from reaching output"

    def test_legal_advice_certainty_blocked(self):
        node = PostProcessNode()
        result = {"validated_answer": "This is legal advice (FATF-R16-2025-11).",
                  "status": AgentStatus.SUCCESS.value}
        try:
            node._extra_security_gate_output(result)
            raised = False
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block an unsupported legal-certainty assertion"


class TestGraphStructure:
    def test_inherits_agent_base_graph(self):
        from framework.graph.agent_base_graph import AgentBaseGraph
        assert issubclass(Graph, AgentBaseGraph)

    def test_does_not_override_add_edges(self):
        assert "add_edges" not in Graph.__dict__

    def test_state_schema_is_state(self):
        assert Graph().state_schema is State

    def test_agent_name(self):
        assert Graph().name == "fin_c2_182"
