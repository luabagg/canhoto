from pathlib import Path

import finance_ingest.config as config
from finance_ingest import service
from finance_ingest.models import BudgetCategory, TransactionKind

FIXTURES = Path(__file__).parent / "fixtures"


def test_ingest_and_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_DATA_DIR", str(tmp_path / "data"))
    # reload paths
    config.DEFAULT_DATA_DIR = tmp_path / "data"

    out = service.ingest_paths(
        [
            str(FIXTURES / "mercadopago-account-2026-06.txt"),
            str(FIXTURES / "mercadopago-card-2026-07.txt"),
        ]
    )
    assert out["transaction_count"] > 20

    # June account activity
    june = service.get_monthly_summary("2026-06")
    assert june["transaction_count"] > 0
    # card payment should be excluded from expenses
    rec = service.reconcile("2026-06")
    assert rec["counts"]["card_payments"] >= 1

    pending = service.get_pending_review(month="2026-06")
    if pending:
        pid = pending[0]["id"]
        applied = service.apply_classifications(
            [
                {
                    "id": pid,
                    "category": BudgetCategory.OTHERS.value,
                    "kind": TransactionKind.EXPENSE.value,
                    "is_expense": True,
                    "needs_review": False,
                    "confidence": 0.99,
                    "merchant_normalized": "Test Merchant",
                }
            ]
        )
        assert applied["applied"] == 1

    export = service.export_json("2026-06")
    assert Path(export["path"]).exists()
