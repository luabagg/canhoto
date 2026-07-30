"""Deterministic classification rules for ledger rows.

Portable accounting intent (architecture §9):
- Card purchases count as expenses.
- Paying the card from a cash account is ``card_payment`` (not spend).
- Self transfers via configured own-name markers are ``self_transfer`` (not spend).
- Uncertain rows stay ``needs_review=True``.

Category/kind values are free strings (no closed enums). Default rule pack is
data overridable later; package defaults never include personal names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from canhoto.core.models import ClassificationPatch, ClassificationResult, LedgerTransaction
from canhoto.core import store as core_store

# Month listing ceiling for a single rules pass (household-scale statements).
_DEFAULT_MONTH_LIMIT = 50_000


@dataclass(frozen=True)
class Rule:
    """One regex rule: description match → category/kind/is_expense."""

    pattern: re.Pattern[str]
    category: str
    kind: str
    is_expense: bool
    confidence: float = 0.85


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Portable defaults only — no personal names, no household-specific merchants.
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule(
        _compile(r"PAGAMENTO\s+(DA\s+)?FATURA|PAGAMENTO\s+CART[AÃ]O"),
        category="transfer",
        kind="card_payment",
        is_expense=False,
        confidence=0.95,
    ),
    Rule(
        _compile(r"DINHEIRO\s+RESERVADO|DINHEIRO\s+RETIRADO|POCKET|COFRINHO"),
        category="transfer",
        kind="internal_transfer",
        is_expense=False,
        confidence=0.9,
    ),
    Rule(
        _compile(r"\bRENDIMENTOS?\b|\bJUROS\s+SOBRE\b|\bDIVIDENDOS?\b"),
        category="income",
        kind="income",
        is_expense=False,
        confidence=0.85,
    ),
)


def default_rules() -> list[Rule]:
    """Return a mutable copy of the built-in rule pack."""
    return list(DEFAULT_RULES)


def apply_rules(
    tx: LedgerTransaction,
    *,
    own_name_markers: list[str] | None = None,
    rules: Sequence[Rule] | None = None,
) -> LedgerTransaction:
    """Return a deep-copied row with classification fields filled by rules.

    Does not mutate ``tx``. Does not touch the store.
    """
    out = tx.model_copy(deep=True)
    desc = _description_blob(out)
    markers = [m for m in (own_name_markers or []) if m and m.strip()]
    pack = list(rules) if rules is not None else default_rules()

    # 1) Card payment / portable regex pack (highest confidence structural rules).
    for rule in pack:
        if rule.pattern.search(desc):
            return _classify(
                out,
                category=rule.category,
                kind=rule.kind,
                is_expense=rule.is_expense,
                confidence=rule.confidence,
                needs_review=False,
                review_reason=None,
                merchant_normalized=out.merchant_normalized or _normalize_merchant(desc),
            )

    # 2) Self-transfer: PIX/TED-style counterparty contains a configured marker.
    if markers and _looks_like_person_transfer(desc) and _marker_match(desc, markers):
        return _classify(
            out,
            category="transfer",
            kind="self_transfer",
            is_expense=False,
            confidence=0.9,
            needs_review=False,
            review_reason=None,
            merchant_normalized=out.merchant_normalized or _normalize_merchant(desc),
        )

    # 3) Sign / source defaults — leave uncertain rows for review.
    amount_minor = out.amount_minor
    source = (out.source_kind or "").strip().lower()

    if amount_minor > 0 and source == "account":
        return _classify(
            out,
            category=out.category or "income",
            kind=out.kind or "income",
            is_expense=False,
            confidence=max(out.confidence, 0.4),
            needs_review=True,
            review_reason=out.review_reason or "income_unclassified",
            merchant_normalized=out.merchant_normalized or _normalize_merchant(desc),
        )

    if amount_minor < 0:
        return _classify(
            out,
            category=out.category or "uncategorized",
            kind=out.kind or "expense",
            is_expense=True,
            confidence=max(out.confidence, 0.2),
            needs_review=True,
            review_reason=out.review_reason or "needs_category",
            merchant_normalized=out.merchant_normalized or _normalize_merchant(desc),
        )

    # Zero-amount or ambiguous sign.
    return _classify(
        out,
        category=out.category or "",
        kind=out.kind or "",
        is_expense=False,
        confidence=out.confidence,
        needs_review=True,
        review_reason=out.review_reason or "unknown",
        merchant_normalized=out.merchant_normalized or _normalize_merchant(desc) or None,
    )


def run_rules_for_month(
    month: str,
    *,
    path: Path | None = None,
    own_name_markers: list[str] | None = None,
    rules: Sequence[Rule] | None = None,
    limit: int = _DEFAULT_MONTH_LIMIT,
) -> ClassificationResult:
    """List month transactions, apply rules, persist changed classification fields."""
    _validate_month(month)
    txs = core_store.list_transactions(month=month, limit=limit, path=path)
    patches: list[ClassificationPatch] = []
    for tx in txs:
        classified = apply_rules(
            tx,
            own_name_markers=own_name_markers,
            rules=rules,
        )
        patch = _diff_classification(tx, classified)
        if patch is not None:
            patches.append(patch)
    if not patches:
        return ClassificationResult(applied=0, missing=[])
    return core_store.apply_classifications(patches, path=path)


def _diff_classification(
    before: LedgerTransaction,
    after: LedgerTransaction,
) -> ClassificationPatch | None:
    """Build a patch only when classification fields actually change."""
    fields = (
        "category",
        "kind",
        "is_expense",
        "needs_review",
        "confidence",
        "review_reason",
        "merchant_normalized",
    )
    changed: dict[str, object] = {}
    for name in fields:
        b = getattr(before, name)
        a = getattr(after, name)
        if b != a:
            changed[name] = a
    if not changed:
        return None
    return ClassificationPatch(id=before.id, **changed)  # type: ignore[arg-type]


def _classify(
    tx: LedgerTransaction,
    *,
    category: str,
    kind: str,
    is_expense: bool,
    confidence: float,
    needs_review: bool,
    review_reason: str | None,
    merchant_normalized: str | None,
) -> LedgerTransaction:
    return tx.model_copy(
        update={
            "category": category,
            "kind": kind,
            "is_expense": is_expense,
            "confidence": confidence,
            "needs_review": needs_review,
            "review_reason": review_reason,
            "merchant_normalized": merchant_normalized,
        }
    )


def _description_blob(tx: LedgerTransaction) -> str:
    parts = [tx.description or "", tx.merchant_raw or "", tx.merchant_normalized or ""]
    return " ".join(p for p in parts if p).strip()


def _looks_like_person_transfer(desc: str) -> bool:
    return bool(
        re.search(
            r"\bPIX\s+(ENVIADO|RECEBIDO)\b|\bTED\b|\bDOC\b|\bTRANSFER[EÊ]NCIA\b",
            desc,
            flags=re.IGNORECASE,
        )
    )


def _marker_match(desc: str, markers: list[str]) -> bool:
    upper = desc.upper()
    return any(marker.strip().upper() in upper for marker in markers if marker.strip())


def _normalize_merchant(desc: str) -> str:
    d = re.sub(r"\s+", " ", desc).strip()
    d = re.sub(
        r"^(Pix enviado|Pix recebido|Pagamento de conta|Pagamento com QR Pix)\s+",
        "",
        d,
        flags=re.IGNORECASE,
    )
    d = re.sub(r"^(DL\*|MP\*|EC\*|IFD\*)\s*", "", d, flags=re.IGNORECASE)
    return d[:80]


_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _validate_month(month: str) -> None:
    if not _MONTH_RE.match(month or ""):
        raise ValueError(f"month must be YYYY-MM, got {month!r}")
    year_s, month_s = month.split("-")
    month_n = int(month_s)
    if not 1 <= month_n <= 12:
        raise ValueError(f"month must be YYYY-MM, got {month!r}")
    # year range is intentionally wide; format is the contract.
    _ = int(year_s)


__all__ = [
    "DEFAULT_RULES",
    "Rule",
    "apply_rules",
    "default_rules",
    "run_rules_for_month",
]
