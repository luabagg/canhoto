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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from canhoto.core import store as core_store
from canhoto.core.models import ClassificationPatch, ClassificationResult, LedgerTransaction

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
    Rows already settled (not needs_review, non-empty category other than
    ``uncategorized``) are left unchanged so human/memory labels stick.
    """
    out = tx.model_copy(deep=True)
    if not _eligible_for_rule_reclassify(out):
        return out
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
    """List month transactions, apply rules, then merchant memory, persist patches.

    Order:
    1. Deterministic rule pack + self-transfer markers
    2. Merchant category memory for rows still needing review
    """
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
    if patches:
        rules_result = core_store.apply_classifications(patches, path=path)
    else:
        rules_result = ClassificationResult(applied=0, missing=[])

    memory_result = apply_merchant_memory_for_month(month, path=path, limit=limit)
    return ClassificationResult(
        applied=rules_result.applied + memory_result.applied,
        missing=list(rules_result.missing) + list(memory_result.missing),
        merchant_memory_applied=memory_result.applied,
    )


def apply_merchant_memory_for_month(
    month: str,
    *,
    path: Path | None = None,
    limit: int = _DEFAULT_MONTH_LIMIT,
) -> ClassificationResult:
    """Apply stored merchant→category map to still-pending rows in ``month``.

    Only rows with ``needs_review=True`` (or empty/uncategorized category) are
    considered. Known structural classifications are left alone. Learnable keys
    only — person-id-like keys never match.
    """
    _validate_month(month)
    txs = core_store.list_transactions(month=month, limit=limit, path=path)
    patches: list[ClassificationPatch] = []
    for tx in txs:
        if not _eligible_for_merchant_memory(tx):
            continue
        key = merchant_key_for(tx)
        if key is None:
            continue
        category = core_store.get_merchant_category(key, path=path)
        if not category:
            continue
        classified = _classify_from_merchant_memory(tx, category=category)
        patch = _diff_classification(tx, classified)
        if patch is not None:
            patches.append(patch)
    if not patches:
        return ClassificationResult(applied=0, missing=[], merchant_memory_applied=0)
    result = core_store.apply_classifications(patches, path=path)
    return ClassificationResult(
        applied=result.applied,
        missing=list(result.missing),
        merchant_memory_applied=result.applied,
    )


def is_learnable_merchant_key(merchant_key: str) -> bool:
    """Return False for empty or person-id-like keys (CPF / digit-heavy).

    Simple heuristic only — not a full identity detector.
    """
    key = (merchant_key or "").strip()
    if not key:
        return False
    digits_only = re.sub(r"\D", "", key)
    letters = sum(1 for c in key if c.isalpha())
    # CPF-sized digit runs with little alphabetic content (person transfers).
    if len(digits_only) >= 11 and letters <= 6:
        return False
    alnum = re.sub(r"[^0-9A-Za-z]", "", key)
    if not alnum:
        return False
    digit_ratio = sum(c.isdigit() for c in alnum) / len(alnum)
    if digit_ratio >= 0.8 and letters < 2:
        return False
    return True


def merchant_key_for(tx: LedgerTransaction) -> str | None:
    """Stable learnable key for a row, or None if nothing safe to remember."""
    key = (tx.merchant_normalized or "").strip()
    if not key:
        key = _normalize_merchant(_description_blob(tx)).strip()
    if not key or not is_learnable_merchant_key(key):
        return None
    return key


def _eligible_for_rule_reclassify(tx: LedgerTransaction) -> bool:
    """True when rules may overwrite classification fields."""
    if tx.needs_review:
        return True
    cat = (tx.category or "").strip().lower()
    return cat in ("", "uncategorized")


def _eligible_for_merchant_memory(tx: LedgerTransaction) -> bool:
    return _eligible_for_rule_reclassify(tx)


def _classify_from_merchant_memory(
    tx: LedgerTransaction, *, category: str
) -> LedgerTransaction:
    amount_minor = tx.amount_minor
    if amount_minor < 0:
        kind = "expense"
        is_expense = True
    elif amount_minor > 0:
        kind = tx.kind or "income"
        is_expense = False
    else:
        kind = tx.kind or ""
        is_expense = False
    return _classify(
        tx,
        category=category,
        kind=kind or tx.kind or "expense",
        is_expense=is_expense,
        confidence=max(tx.confidence, 0.75),
        needs_review=False,
        review_reason=None,
        merchant_normalized=tx.merchant_normalized
        or merchant_key_for(tx)
        or _normalize_merchant(_description_blob(tx))
        or None,
    )


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
    "apply_merchant_memory_for_month",
    "apply_rules",
    "default_rules",
    "is_learnable_merchant_key",
    "merchant_key_for",
    "run_rules_for_month",
]
