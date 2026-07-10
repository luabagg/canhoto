from __future__ import annotations

import re

from finance_ingest.models import (
    BudgetCategory,
    Transaction,
    TransactionKind,
)

# Rule table: (regex on description upper, category, kind, is_expense)
RULES: list[tuple[re.Pattern[str], BudgetCategory, TransactionKind, bool]] = [
    (re.compile(r"PAGAMENTO CART[AÃ]O|PAGAMENTO DA FATURA", re.I), BudgetCategory.TRANSFER, TransactionKind.CARD_PAYMENT, False),
    (re.compile(r"DINHEIRO RESERVADO PIGGY|DINHEIRO RETIRADO PIGGY", re.I), BudgetCategory.TRANSFER, TransactionKind.PIGGY_RESERVE, False),
    (re.compile(r"RENDIMENTOS", re.I), BudgetCategory.INCOME, TransactionKind.INCOME, False),
    (re.compile(r"STAR PROTECAO|STAR PROTEÇÃO", re.I), BudgetCategory.CAR_PAYMENT, TransactionKind.EXPENSE, True),
    (re.compile(r"EDIFICIO MONREALE|EDIF[IÍ]CIO MONREALE", re.I), BudgetCategory.CONDO_FEE, TransactionKind.EXPENSE, True),
    (re.compile(r"RGE SUL|ENERGIA", re.I), BudgetCategory.ELECTRIC, TransactionKind.EXPENSE, True),
    (re.compile(r"VIA SUL|INTERNET|LOCAWEB|LINKED STORE", re.I), BudgetCategory.INTERNET, TransactionKind.EXPENSE, True),
    (re.compile(r"AUTO POSTO|ABASTECEDORA|POSTO ", re.I), BudgetCategory.GAS_TRAVEL, TransactionKind.EXPENSE, True),
    (re.compile(r"MERCADO UNIAO|HORTIFRUTI|BENTOSUL|ALVI AZUL", re.I), BudgetCategory.GROCERIES, TransactionKind.EXPENSE, True),
    (re.compile(r"BURG|CAFFE|GELAT|PADARIA|IFD\*|IFOOD|RESTAURANTE", re.I), BudgetCategory.EATING, TransactionKind.EXPENSE, True),
    (re.compile(r"RAIA|DROGARIA|FARMA", re.I), BudgetCategory.PERSONAL_CARE, TransactionKind.EXPENSE, True),
    (re.compile(r"GOOGLE|YOUTUB|YOUTUBE|\bX\b|OPENAI|CHATGPT|MELIMAIS|ANOMALY", re.I), BudgetCategory.ENTERTAINMENT, TransactionKind.EXPENSE, True),
    (re.compile(r"AREZZO|ADIDAS|MERCADOLIVRE|CAMPING", re.I), BudgetCategory.PURCHASES, TransactionKind.EXPENSE, True),
    (re.compile(r"BLINGERP|VINDI", re.I), BudgetCategory.OTHERS, TransactionKind.EXPENSE, True),
]


def _looks_like_self_transfer(desc: str, own_markers: list[str]) -> bool:
    d = desc.upper()
    if "PIX ENVIADO" in d or "PIX RECEBIDO" in d:
        for marker in own_markers:
            if marker.upper() in d:
                return True
    return False


def apply_rules(tx: Transaction, own_name_markers: list[str] | None = None) -> Transaction:
    markers = own_name_markers or ["LUAN BAGGIO", "Luan Baggio"]
    desc = tx.description

    # Preserve card payments already tagged
    if tx.kind is TransactionKind.CARD_PAYMENT:
        tx.is_expense = False
        tx.category = BudgetCategory.TRANSFER
        tx.needs_review = False
        tx.confidence = max(tx.confidence, 0.95)
        tx.merchant_normalized = tx.merchant_normalized or "Credit card payment"
        return tx

    if _looks_like_self_transfer(desc, markers):
        tx.kind = TransactionKind.SELF_TRANSFER
        tx.category = BudgetCategory.TRANSFER
        tx.is_expense = False
        tx.needs_review = False
        tx.confidence = 0.9
        tx.merchant_normalized = tx.merchant_normalized or "Self transfer"
        tx.review_reason = None
        return tx

    for pattern, category, kind, is_expense in RULES:
        if pattern.search(desc):
            tx.category = category
            tx.kind = kind
            tx.is_expense = is_expense
            tx.merchant_normalized = tx.merchant_normalized or _normalize_merchant(desc)
            tx.confidence = 0.85
            tx.needs_review = False
            tx.review_reason = None
            return tx

    # Defaults by sign for account moves
    if tx.amount > 0 and tx.source_kind.value == "account":
        tx.kind = TransactionKind.INCOME
        tx.category = BudgetCategory.INCOME
        tx.is_expense = False
        tx.confidence = 0.4
        tx.needs_review = True
        tx.review_reason = "income_unclassified"
        tx.merchant_normalized = tx.merchant_normalized or _normalize_merchant(desc)
        return tx

    if tx.amount < 0:
        tx.kind = TransactionKind.EXPENSE
        tx.category = BudgetCategory.UNCATEGORIZED
        tx.is_expense = True
        tx.confidence = 0.2
        tx.needs_review = True
        tx.review_reason = "needs_category"
        tx.merchant_normalized = tx.merchant_normalized or _normalize_merchant(desc)
        return tx

    tx.needs_review = True
    tx.review_reason = tx.review_reason or "unknown"
    return tx


def _normalize_merchant(desc: str) -> str:
    d = re.sub(r"\s+", " ", desc).strip()
    d = re.sub(r"^(Pix enviado|Pix recebido|Pagamento de conta|Pagamento com QR Pix)\s+", "", d, flags=re.I)
    d = re.sub(r"^(DL\*|MP\*|EC\*|IFD\*)\s*", "", d, flags=re.I)
    return d[:80]


def categorize_many(txs: list[Transaction], own_name_markers: list[str] | None = None) -> list[Transaction]:
    return [apply_rules(tx.model_copy(deep=True), own_name_markers=own_name_markers) for tx in txs]
