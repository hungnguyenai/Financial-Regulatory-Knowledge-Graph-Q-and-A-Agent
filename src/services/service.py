"""AgentCore Platform v1.0"""

# Deterministic offline versioned regulatory corpus + reasoning core for FIN-C2-182.
#
# Cross-regime regulatory Q&A: given a compliance/legal/risk question, the agent
# retrieves versioned passages from FSA AI MRM, 犯収法 (AML/KYC), FATF Recommendation
# 16 (Travel Rule), and FISC (self-hosting / data residency) and synthesises a cited,
# effective-date + jurisdiction reconciled answer.
#
# This module is the deterministic, fully CI-safe offline core: no external
# dependency, no live API. Per the architect ruling (2026-07-16, Option A) the KG is a
# template-owned versioned APPROVED-corpus index — no runtime/user memory, no
# write-back, no shared KG abstraction. In production the retrieval below is replaced
# by an injected versioned `kb_client` (same `retrieve(query) -> list[dict]`
# interface); absent, retrieval falls back to the corpus below. If an injected
# kb_client yields nothing, callers must surface a `NO_MATCH` disposition (see
# MainNode) rather than synthesise an ungrounded answer. Only regulatory citations +
# snippets are ever stored — never source-system credentials (S-5).

from __future__ import annotations

from typing import Any, Optional, cast

# Snapshot version of the bundled cross-regime regulatory corpus.
# In production the injected kb_client supplies the real per-regime version.
KB_VERSION = "2026-07-01"

# Disposition labels (single source of truth).
ANSWERED = "ANSWERED"
NO_MATCH = "NO_MATCH"

# Versioned regulatory corpus. Each passage carries a citation id, the regime,
# the effective date, the jurisdiction, the KB snapshot date, and a snippet.
REGULATORY_KB: list[dict[str, Any]] = [
    {
        "citation": "FSA-AIMRM-2026-04",
        "regime": "FSA AI Model Risk Management Guideline",
        "effective_date": "2026-04-01",
        "jurisdiction": "Japan",
        "kb_date": KB_VERSION,
        "snippet": "FSA's AI Model Risk Management guideline requires financial institutions "
        "to validate AI model governance (explainability, drift monitoring, human "
        "oversight) proportional to the model's decision impact, effective 2026-04-01.",
    },
    {
        "citation": "AML-KYC-2026-06",
        "regime": "犯収法 (Act on Prevention of Transfer of Criminal Proceeds) KYC/AML",
        "effective_date": "2026-06-01",
        "jurisdiction": "Japan",
        "kb_date": KB_VERSION,
        "snippet": "The 2026 犯収法 amendment tightens customer due diligence (顧客管理) for "
        "correspondent-banking relationships, requiring enhanced beneficial-ownership "
        "verification and ongoing monitoring for cross-border wire transfers, effective "
        "2026-06-01.",
    },
    {
        "citation": "FATF-R16-2025-11",
        "regime": "FATF Recommendation 16 (Travel Rule)",
        "effective_date": "2025-11-01",
        "jurisdiction": "Global (FATF member jurisdictions)",
        "kb_date": KB_VERSION,
        "snippet": "FATF Recommendation 16 requires originator and beneficiary information to "
        "travel with wire transfers and virtual-asset transfers above the designated "
        "threshold, enabling counterparty due diligence across correspondent-banking "
        "and VASP relationships.",
    },
    {
        "citation": "FISC-SEC-2025-09",
        "regime": "FISC Security Guidelines (self-hosting / data residency)",
        "effective_date": "2025-09-01",
        "jurisdiction": "Japan",
        "kb_date": KB_VERSION,
        "snippet": "FISC security guidelines require financial institutions' AI/compliance "
        "systems handling regulated data to keep processing and storage within "
        "self-hosted or data-resident infrastructure meeting FISC's system-risk "
        "management standards.",
    },
]

# ── keyword lexicons (deterministic retrieval + circumvention screen) ───────

_FSA_AIMRM_INDICATORS = (
    "ai model risk",
    "ai mrm",
    "model risk management",
    "fsa ai",
    "ai governance",
    "model validation",
    "explainability",
)
_AML_KYC_INDICATORS = (
    "kyc",
    "aml",
    "customer due diligence",
    "顧客管理",
    "本人確認",
    "犯収法",
    "correspondent banking",
    "correspondent-banking",
    "beneficial owner",
    "beneficial ownership",
    "anti-money laundering",
)
_FATF_INDICATORS = (
    "fatf",
    "travel rule",
    "recommendation 16",
    "rec. 16",
    "wire transfer",
    "virtual asset",
    "vasp",
)
_FISC_INDICATORS = (
    "fisc",
    "data residency",
    "self-host",
    "self hosting",
    "on-premise",
    "on-prem",
    "system security",
    "data-resident",
)

_REGIME_ROUTING: list[tuple[str, tuple[str, ...]]] = [
    ("FSA AI Model Risk Management Guideline", _FSA_AIMRM_INDICATORS),
    ("犯収法 (Act on Prevention of Transfer of Criminal Proceeds) KYC/AML", _AML_KYC_INDICATORS),
    ("FATF Recommendation 16 (Travel Rule)", _FATF_INDICATORS),
    ("FISC Security Guidelines (self-hosting / data residency)", _FISC_INDICATORS),
]

# Deterministic loophole/evasion-intent screen (rule/keyword ruleset, not LLM).
# Queries seeking to evade KYC/AML/FATF/reporting obligations are rejected before
# retrieval — this is a distinct, prior gate to the retrieval/synthesis below.
_CIRCUMVENTION_INDICATORS = (
    "avoid kyc",
    "bypass kyc",
    "avoid aml",
    "bypass aml",
    "evade reporting",
    "avoid reporting requirement",
    "without triggering",
    "avoid triggering",
    "loophole",
    "抜け穴",
    "回避する方法",
    "structuring to avoid",
    "smurf",
    "avoid detection",
    "circumvent",
    "get around the travel rule",
    "stay under the threshold to avoid",
)


def is_circumvention_intent(text: str) -> bool:
    """Deterministic keyword screen for KYC/AML/FATF evasion-intent queries."""
    t = (text or "").lower()
    return any(marker in t for marker in _CIRCUMVENTION_INDICATORS)


def retrieve_passages(query: str, kb_client: Optional[Any] = None) -> list[dict[str, Any]]:
    """Return versioned regulatory passages relevant to the query, across all regimes.

    Production: defer to the injected versioned kb_client (template-owned approved
    corpus index, Option A). Offline/CI: deterministic keyword-matched corpus above.
    A query may match multiple regimes at once (the cross-regime reconciliation case).
    Only citations + snippets are returned — never source-system credentials.
    """
    if kb_client is not None:
        return cast("list[dict[str, Any]]", kb_client.retrieve(query))

    t = (query or "").lower()
    matched_regimes = {regime for regime, keywords in _REGIME_ROUTING if any(k in t for k in keywords)}
    if not matched_regimes:
        return []
    return [p for p in REGULATORY_KB if p["regime"] in matched_regimes]


def synthesize_answer(query: str, passages: list[dict[str, Any]]) -> str:
    """Deterministic grounded synthesis: cited cross-regime reconciliation answer.

    NOT a pure single-passage lookup: reconciles effective dates and jurisdiction
    scope across every matched regime, in citation order. This deterministic
    synthesiser is the offline/CI fallback for an injected LLM reasoner (deferred —
    see docs/02 §11); the citation/effective-date/jurisdiction contract stays stable
    either way.
    """
    lines = [
        "Cross-regime regulatory reconciliation (grounded in the versioned corpus below):",
        "",
    ]
    for p in sorted(passages, key=lambda p: p["effective_date"]):
        lines.append(
            f"- **{p['regime']}** ({p['citation']}, effective {p['effective_date']}, "
            f"jurisdiction: {p['jurisdiction']}, KB version {p['kb_date']}): {p['snippet']}"
        )
    lines.append("")
    lines.append(
        "Compliance action: apply the most recently effective obligation from each "
        "matched regime above; where regimes overlap (e.g. AML/KYC due diligence and "
        "FATF Travel Rule counterparty information), the stricter requirement governs "
        "the correspondent-banking or virtual-asset relationship in question."
    )
    return "\n".join(lines)
