"""AgentCore Platform v1.0"""

# FIN-C2-182 — Financial Regulatory Knowledge Graph Q&A Agent (VectorRAG node-backbone)
#
# Cat 2 — Multi-step domain workflow (job-to-be-done).
#   Parent  : AgentBaseGraph (outer graph, L1 direct).
#   Pipeline: START → initialize → pre_process → main → post_process → finalize → END
#   Pattern : VectorRAG (cross-regime cited synthesis grounded in a versioned
#             FSA AI MRM / 犯収法 / FATF Rec.16 / FISC corpus snapshot).
#
#   pre_process  — InputValidate + CircumventionScreen: sanitise · S-2 gate ·
#                  deterministic loophole/evasion-intent reject
#   main         — VersionedRegulatoryRetrieve + CitedSynthesis (VectorRAG over the
#                  cross-regime regulatory KB)
#   post_process — OutputValidate (S-3 not-legal-advice + grounding gate) +
#                  DecisionTraceAudit (S-4)
#
# The versioned regulatory kb_client is injected via graph config at
# register_nodes() time (a DATA dependency on the template-owned versioned
# approved-corpus index, architect ruling 2026-07-16 Option A — no cross-template
# code import); absent → deterministic CI-safe fallback corpus (services.service).
# No live API at query time; no runtime/user memory or shared KG.

from framework.graph.agent_base_graph import AgentBaseGraph

from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class Graph(AgentBaseGraph):
    """Cat 2 outer graph for FIN-C2-182.

    Backbone: initialize → pre_process → main → post_process → finalize (fixed).
    Class name matches config/agent.yaml `class:` exactly.
    """

    @property
    def name(self) -> str:
        return "fin_c2_182"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode

        cfg = getattr(self, "config", None) or {}
        kb_client = cfg.get("kb_client")

        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = MainNode(kb_client=kb_client)
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.
