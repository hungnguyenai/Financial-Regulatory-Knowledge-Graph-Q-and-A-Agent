# docs/02_design.md — FIN-C2-182 Design Specification

**Template ID**: FIN-C2-182
**Name**: Financial Regulatory Knowledge Graph Q&A Agent (cognee + FSA AI MRM)
**Category**: Cat 2 | **Industry**: FIN | **Pattern**: VectorRAG
**L1 Base:** AgentBaseGraph (L1 direct)
**Status**: Design — new-gen scaffold

---

## 1. Overview

Cross-regime regulatory Q&A for compliance, legal, and risk professionals. Given a natural-language
regulatory question, the agent validates and screens the request, retrieves versioned passages from a
FSA AI Model Risk Management / 犯収法 (AML/KYC) / FATF Recommendation 16 (Travel Rule) / FISC
(self-hosting, data residency) corpus, and synthesises a **cited** answer reconciling effective dates
and jurisdiction scope across every regime the question touches. It is informational, **not legal
advice**; loophole/evasion-intent queries are rejected before retrieval.

Example: *"For a cross-border correspondent-banking relationship, what does the current 犯収法 KYC
requirement demand versus FATF Recommendation 16, and what changed as of the latest effective date?"*
→ a cited answer reconciling `AML-KYC-2026-06` and `FATF-R16-2025-11` (KB version 2026-07-01).

---

## 2. Architecture — L1 Base

**L1 Base:** `AgentBaseGraph` (`framework/graph/agent_base_graph.py`), inherited directly.

Per the 2026-05-18 architecture change, templates inherit directly from L1; the retired base-agent
layer is no longer an inheritance path. `VectorRAGAgent` survives only as the **node-backbone
pattern** label (`config/agent.yaml` `base_type`). The outer graph `Graph(AgentBaseGraph)` registers
three domain nodes into the fixed framework backbone; `InitializeNode`/`FinalizeNode` are injected by
`super().register_nodes()`. `add_edges()` is NOT overridden.

The canonical cross-regime flow (InputValidate → CircumventionScreen → VersionedRegulatoryRetrieve →
CitedSynthesis → OutputValidate(S-3) → DecisionTraceAudit(S-4)) is consolidated onto the fixed 3
domain slots: InputValidate+CircumventionScreen fold into `pre_process`; VersionedRegulatoryRetrieve+
CitedSynthesis fold into `main`; OutputValidate+DecisionTraceAudit fold into `post_process`. All 6
canonical steps are preserved across the 3 nodes — no step is dropped.

---

## 3. Node Flow (5-node backbone)

```
START → initialize → pre_process → main → post_process → finalize → END
```

| Slot | Node | Canonical step(s) | Responsibility |
|------|------|-------------------|-----------------|
| `initialize`   | InitializeNode (framework) | — | Seed IDs / context |
| `pre_process`  | PreProcessNode (FunctionNode) | InputValidate + CircumventionScreen | Validate + sanitise + S-2 out-of-scope/credential-shaped block + deterministic loophole/evasion-intent reject |
| `main`         | MainNode (FunctionNode) | VersionedRegulatoryRetrieve + CitedSynthesis | Retrieve versioned cross-regime passages (VectorRAG); reconcile effective-date + jurisdiction; synthesise cited draft answer; `NO_MATCH` if nothing matched |
| `post_process` | PostProcessNode (FunctionNode) | OutputValidate + S-3 + DecisionTraceAudit + S-4 | Append non-suppressible informational disclaimer; block uncited/credential/legal-certainty output; emit audit record |
| `finalize`     | FinalizeNode (framework) | — | Finalize status |

`main` is a `FunctionNode` (no inner graph). The versioned regulatory KB client is injected via graph
config; absent → deterministic fallback corpus. Any node returning `AgentStatus.ERROR` short-circuits
the remaining domain nodes (a `CircumventionScreen` reject or a `NO_MATCH` never reaches
`post_process`).

---

## 4. State Schema

`src/schemas/state.py` — `class State(AgentState)`. The request arrives as inherited `user_input`.

| Field (agent-specific) | Type | Set by | Description |
|-------------------------|------|--------|-------------|
| `sanitized_query` | `Optional[str]` | pre_process | Whitespace-normalised, screened request |
| `circumvention_flagged` | `Optional[bool]` | pre_process | True when CircumventionScreen rejected the query |
| `retrieved_passages` | `Optional[list[dict]]` | main | `{citation, regime, effective_date, jurisdiction, kb_date, snippet}` — **non-suppressible citation trail** |
| `kb_version_manifest` | `Optional[list[str]]` | main | One entry per regime cited (S-4 audit + data-currency) |
| `disposition` | `Optional[str]` | main | `ANSWERED` \| `NO_MATCH` |
| `cited_answer` | `Optional[str]` | main | Draft cited cross-regime reconciliation (pre-S-3) |
| `validated_answer` | `Optional[str]` | post_process | Final answer incl. informational disclaimer |
| `citation_count` | `Optional[int]` | post_process | Number of distinct regulatory citations in the answer |

All fields flat, msgpack-safe primitives (ADR-005) — no non-flat objects, no datetime/bytes, no
credentials or connection strings. No customer/transaction PII is ever part of this agent's domain
(it answers regulatory questions, not customer-specific determinations).

---

## 5. Domain Logic — Screening, Retrieval & Synthesis

`src/services/service.py` — deterministic offline corpus (`REGULATORY_KB`) spanning FSA AI MRM /
犯収法 (AML/KYC) / FATF Recommendation 16 / FISC, each passage carrying `citation`/`regime`/
`effective_date`/`jurisdiction`/`kb_date`/`snippet`.

- **CircumventionScreen** (`is_circumvention_intent`): deterministic keyword ruleset (rule/keyword, not
  LLM) for loophole/evasion-intent phrasing (e.g. "avoid KYC", "bypass AML", "loophole", "抜け穴",
  "structuring to avoid"). Runs in `pre_process`, BEFORE retrieval — a query flagged here never
  reaches `VersionedRegulatoryRetrieve`.
- **VersionedRegulatoryRetrieve** (`retrieve_passages`): keyword-matched retrieval across all four
  regime lexicons at once — a query may legitimately match multiple regimes (the cross-regime
  reconciliation case, e.g. AML/KYC + FATF Travel Rule for a correspondent-banking question). No
  match across any regime → `NO_MATCH`.
- **CitedSynthesis** (`synthesize_answer`): deterministic grounded synthesis, NOT a pure single-passage
  lookup — reconciles effective dates (sorted ascending) and jurisdiction scope across every matched
  regime, then states the compliance action (stricter-requirement-governs framing for overlapping
  regimes). This deterministic synthesiser is the offline/CI fallback for an injected LLM reasoner
  (deferred — §11); the citation/effective-date/jurisdiction contract stays stable either way.

In production the injected versioned `kb_client` replaces the corpus (same `retrieve(query) ->
list[dict]` interface, per architect ruling 2026-07-16 Option A: template-owned versioned
approved-corpus index — no runtime/user memory, no write-back, no shared KG abstraction). Only
regulatory citations + snippets are ever surfaced — never source-system credentials.

---

## 6. Security Model (5-layer)

| Layer | Where | Design |
|-------|-------|--------|
| S-1 Trust | every node | `required_trust_level = INTERNAL` (authorized compliance/legal/risk staff) — declared on all three FunctionNode subclasses + `config/agent.yaml` |
| S-2 Input | `PreProcessNode._extra_security_gate_input` + `execute()` | Length-cap + out-of-scope/credential-shaped guard (returns state; never raises); execute() also runs the deterministic CircumventionScreen |
| S-3 Output | `PostProcessNode._extra_security_gate_output` | Block credential patterns; block unsupported legal-certainty phrasing; **ResponseValidate** rejects an answer with no regulatory citation (grounding); the informational disclaimer is appended non-suppressibly in `execute()` |
| S-4 Audit | every `execute()` | `emit_trace_event()` domain events (input_validated, circumvention_rejected, passage_retrieved, no_regulatory_match, cited_synthesis_complete, decision_trace_audit …) — no PII, no credentials |
| S-5 Credential | CI `gate-credential-scan` + deps | No hardcoded secrets; deps `==`-pinned; no secrets/connection strings in State or corpus |

`retrieved_passages` is written once by `main` and never filtered downstream (citation-trail integrity
— an answer must stay grounded in the regulatory basis it cites).

---

## 7. KB Dependency (versioned offline snapshot)

Data dependency on the versioned FSA AI MRM / 犯収法 / FATF / FISC corpus — a template-owned
approved-corpus index (architect ruling 2026-07-16, Option A). **No cross-template code import**; the
indexer is not called at runtime. Readiness gate: corpus must be current before deploy. Fallback:
`NO_MATCH` disposition when the injected client (or the deterministic corpus) yields nothing — the
agent never synthesises an answer without current regulatory grounding. The KB version manifest is
recorded in state + audit.

---

## 8. Interfaces

**Input** (`user_input`): a cross-regime regulatory question (free text).
**Output** (`result.output` / `formatted_output`): a cited answer — regime-by-regime reconciliation +
compliance-action framing + informational (not-legal-advice) disclaimer.
Entry points: `src/api/server.py` (`POST /invoke`, `GET /health`) and direct `agent.invoke()`.

---

## 9. Failure / Error Routing

| Condition | Node | Behaviour |
|-----------|------|-----------|
| Empty / whitespace input | pre_process | `status=ERROR`, error_log entry; downstream nodes short-circuit |
| Oversized input (> 10,000 chars) | pre_process (execute + S-2 gate) | `status=ERROR` |
| Out-of-scope / credential-shaped input | pre_process (execute + S-2 gate) | `status=ERROR` |
| Circumvention/loophole-intent query | pre_process (CircumventionScreen) | `status=ERROR`, `circumvention_flagged=True`; retrieval never runs |
| Below-trust caller (< INTERNAL) | S-1 gate (framework) | refused before domain execute |
| No regulatory passage matched | main | `NO_MATCH` `status=ERROR` — never answer without grounding |
| Uncited / credential / legal-certainty output | post_process S-3 | `RuntimeError` raised, output blocked |

---

## 10. Acceptance Criteria

- Backbone runs `initialize → pre_process → main → post_process → finalize` in fixed order.
- Valid INTERNAL invocation for an in-scope, retrievable question returns a cited answer
  (`validated_answer` carries a `FSA-`/`AML-KYC-`/`FATF-`/`FISC-`/`KB version` citation marker + the
  informational disclaimer) with `status=SUCCESS`.
- A circumvention/loophole-intent query is rejected before retrieval — zero KB calls, `post_process`
  never runs.
- No answer passes S-3 without at least one regulatory citation.
- An unmatched query forces `NO_MATCH` — never an affirmative synthesis without grounding.
- Effective-date/jurisdiction reconciliation is grounded in the retrieved passages (no fabricated
  regime/date not present in `retrieved_passages`).
- All CI gates green: scaffold-integrity, design, import-isolation, composition, invoke-chain,
  credential-scan, trust-level, cat-consistency, stub-check, dep-pinning, run-tests.

---

## 11. Deferred to later implementation issues

The day-0 implementation is CI-safe and deterministic offline. The following land via their own
issues:

- **Versioned vector-KB / cognee retrieval** — replace the deterministic corpus with the injected
  versioned client over the real self-hosted cognee knowledge graph (with snapshot-freshness checks).
  Self-host vs platform KG/memory primitive is an architectural ruling still open (§12 dependency #1 in the
  proposal) — a persistence-layer design choice, not a hard blocker for this implementation.
- **LLM cross-regime synthesis reasoner** — richer reconciliation / rationale via an injected
  `BaseLLM` (`ctx.secrets.require(...)`); the deterministic synthesiser is retained as offline/CI
  fallback.
- **Corpus refresh pipeline** — scheduled versioned ingest of official FSA/犯収法/FATF/FISC sources
  (build-time pipeline, not part of the query-time graph).

---

## Supported entry point — HTTP/gateway only (Marketplace out of scope)

Every node in this template declares `required_trust_level = INTERNAL`, which is the design
decision recorded for this agent: the data it reads is not material an arbitrary authenticated
caller should be able to query.

The one-shot Marketplace runner stamps the caller at `VERIFIED_EXTERNAL` and exposes no
configuration surface or elevation path to `INTERNAL`, so the S-1 gate refuses every Marketplace
invocation **before** `execute()` runs. Two consequences are worth stating, because both read as
a broken image: the Pod still reports success and the audit counters do not move, and the terminal
failure carries no reason, so the chat surface shows an opaque error.

Nesting does not change this. A subgraph is invoked with the caller's own context
(`subgraph.invoke(..., ctx=ctx)`), so the trust level propagates unchanged and an inner node
cannot be reached at a higher level than the outer call arrived with.

### The HTTP path is also closed, deliberately

The standalone adapter used to promote an anonymous caller straight to `INTERNAL` once it
presented the shared `INVOKE_AUTH_TOKEN`. That token authenticates a *deployment*, not a person,
so granting `INTERNAL` on it placed a back door behind the very gate this design depends on. The
adapter now grants `VERIFIED_EXTERNAL`, which is what its own documentation always described.
**The gate is unchanged** — every node still requires `INTERNAL`.

The consequence is stated rather than hidden: since the nodes require `INTERNAL` and nothing in
either entry point can now supply it, **this template currently has no reachable entry point at
all**. That is fail-closed and intended.

One legitimate route remains open: trust established by upstream middleware is passed through
unchanged, so a gateway that has verified the caller's identity can still reach these nodes.

### What is NOT being done

- The nodes' `required_trust_level` is **not** lowered. Doing so would widen who may query this
  data, which is a product decision and not an engineering one.
- No Marketplace image is published and the template is not registered as a Marketplace agent.
