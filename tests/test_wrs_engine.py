"""Tests for wrs-engine."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from wrs_engine import (
    CollateralLoan,
    DeliveryLot,
    Grade,
    MarginStatus,
    evaluate_delivery_intake,
    evaluate_mark_to_market,
    issue_warehouse_receipt,
    moisture_shrinkage_weight,
    verify_warehouse_receipt,
)
from wrs_engine.cli import main as cli_main


def test_dry_matter_moisture_shrinkage_exceeds_naive_linear_diff() -> None:
    # 10,000 kg at 17.5% dried to 13.5%: dry ratio = 82.5 / 86.5 = 0.953757 (4.62% moisture shrink + 0.5% handling)
    net = moisture_shrinkage_weight(Decimal("10000"), Decimal("17.5"), Decimal("13.5"), Decimal("0.5"))
    assert net == Decimal("9489.88")
    # Already dry grain (12.0% <= 13.5%) incurs zero moisture shrink
    assert moisture_shrinkage_weight(Decimal("10000"), Decimal("12.0"), Decimal("13.5")) == Decimal("10000.00")


def test_aflatoxin_rejection_blocks_receipt_issuance() -> None:
    lot = DeliveryLot("maize", Decimal("5000"), Decimal("13.0"), Decimal("0.3"), Decimal("1.0"), Decimal("18.5"))
    intake = evaluate_delivery_intake(lot)
    assert intake.grade == Grade.REJECT
    assert intake.eligible_for_receipt is False
    with pytest.raises(ValueError, match="Cannot issue warehouse receipt"):
        issue_warehouse_receipt(intake, warehouse_id="WH-1", depositor_id="F-1")


def test_sealed_ewr_and_mark_to_market_margin_call() -> None:
    lot = DeliveryLot("maize", Decimal("10000"), Decimal("13.5"), Decimal("0.4"), Decimal("1.5"), Decimal("2.0"))
    intake = evaluate_delivery_intake(lot)
    assert intake.grade == Grade.GRADE_1
    assert intake.net_receipted_weight_kg == Decimal("9960.00")

    ewr = issue_warehouse_receipt(
        intake,
        warehouse_id="WH-JINJA",
        depositor_id="COOP-99",
        issued_at_utc="2026-11-25T10:00:00Z",
    )
    assert verify_warehouse_receipt(ewr) is True
    assert verify_warehouse_receipt(replace(ewr, net_weight_kg=Decimal("12000.00"))) is False

    # Healthy at $0.35/kg with $2100 loan
    loan = CollateralLoan(principal_amount=Decimal("2100"), annual_interest_rate=Decimal("0.18"), days_elapsed=60)
    ok = evaluate_mark_to_market(ewr, loan, spot_grade1_price_per_kg=Decimal("0.35"))
    assert ok.status == MarginStatus.HEALTHY
    assert ok.margin_top_up_cash == Decimal("0.00")

    # Price drops to $0.27/kg => LTV > 80% triggers MARGIN_CALL
    mc = evaluate_mark_to_market(ewr, loan, spot_grade1_price_per_kg=Decimal("0.27"))
    assert mc.status == MarginStatus.MARGIN_CALL
    assert mc.margin_top_up_cash > Decimal("0.00")
    assert mc.margin_top_up_kg > Decimal("0.00")

    # Severe crash to $0.22/kg => LIQUIDATION_TRIGGER
    liq = evaluate_mark_to_market(ewr, loan, spot_grade1_price_per_kg=Decimal("0.22"))
    assert liq.status == MarginStatus.LIQUIDATION_TRIGGER


def test_cli_outputs_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(["--commodity", "maize", "--gross-kg", "10000", "--loan", "1800", "--spot-price", "0.35"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["receipt"]["receipt_id"].startswith("EWR-")
    assert out["mark_to_market"]["status"] == "healthy"
