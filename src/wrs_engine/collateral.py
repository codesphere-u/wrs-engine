"""Electronic Warehouse Receipt issuance, SHA-256 sealing, and mark-to-market margin calls."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from .grading import Grade, IntakeResult

_Q2 = Decimal("0.01")
_Q4 = Decimal("0.0001")

GRADE_PRICE_MULTIPLIER: dict[Grade, Decimal] = {
    Grade.GRADE_1: Decimal("1.00"),
    Grade.GRADE_2: Decimal("0.95"),
    Grade.GRADE_3: Decimal("0.88"),
    Grade.REJECT: Decimal("0.00"),
}

GRADE_MAX_INITIAL_LTV: dict[Grade, Decimal] = {
    Grade.GRADE_1: Decimal("0.70"),
    Grade.GRADE_2: Decimal("0.65"),
    Grade.GRADE_3: Decimal("0.55"),
    Grade.REJECT: Decimal("0.00"),
}


class MarginStatus(StrEnum):
    HEALTHY = "healthy"
    MARGIN_CALL = "margin_call"
    LIQUIDATION_TRIGGER = "liquidation_trigger"


@dataclass(frozen=True)
class WarehouseReceipt:
    """Tamper-evident Electronic Warehouse Receipt (EWR) backed by graded stock."""

    receipt_id: str
    warehouse_id: str
    depositor_id: str
    commodity: str
    grade: Grade
    net_weight_kg: Decimal
    issued_at_utc: str
    storage_fee_per_tonne_day: Decimal
    sha256_seal: str


def _seal_receipt(
    *,
    warehouse_id: str,
    depositor_id: str,
    commodity: str,
    grade: Grade,
    net_weight_kg: Decimal,
    issued_at_utc: str,
    storage_fee_per_tonne_day: Decimal,
) -> str:
    payload = {
        "warehouse_id": warehouse_id,
        "depositor_id": depositor_id,
        "commodity": commodity,
        "grade": grade.value,
        "net_weight_kg": str(net_weight_kg),
        "issued_at_utc": issued_at_utc,
        "storage_fee_per_tonne_day": str(storage_fee_per_tonne_day),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def issue_warehouse_receipt(
    intake: IntakeResult,
    *,
    warehouse_id: str,
    depositor_id: str,
    storage_fee_per_tonne_day: Decimal = Decimal("0.35"),
    issued_at_utc: str | None = None,
) -> WarehouseReceipt:
    """Issue a SHA-256 sealed Electronic Warehouse Receipt from an eligible intake."""
    if not intake.eligible_for_receipt:
        raise ValueError(f"Cannot issue warehouse receipt for rejected lot: {'; '.join(intake.rejection_reasons)}")
    ts = issued_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    fee = storage_fee_per_tonne_day.quantize(_Q2, rounding=ROUND_HALF_UP)
    seal = _seal_receipt(
        warehouse_id=warehouse_id,
        depositor_id=depositor_id,
        commodity=intake.commodity,
        grade=intake.grade,
        net_weight_kg=intake.net_receipted_weight_kg,
        issued_at_utc=ts,
        storage_fee_per_tonne_day=fee,
    )
    return WarehouseReceipt(
        receipt_id=f"EWR-{seal[:12].upper()}",
        warehouse_id=warehouse_id,
        depositor_id=depositor_id,
        commodity=intake.commodity,
        grade=intake.grade,
        net_weight_kg=intake.net_receipted_weight_kg,
        issued_at_utc=ts,
        storage_fee_per_tonne_day=fee,
        sha256_seal=seal,
    )


def verify_warehouse_receipt(receipt: WarehouseReceipt) -> bool:
    """Verify an Electronic Warehouse Receipt's cryptographic SHA-256 seal."""
    expected = _seal_receipt(
        warehouse_id=receipt.warehouse_id,
        depositor_id=receipt.depositor_id,
        commodity=receipt.commodity,
        grade=receipt.grade,
        net_weight_kg=receipt.net_weight_kg,
        issued_at_utc=receipt.issued_at_utc,
        storage_fee_per_tonne_day=receipt.storage_fee_per_tonne_day,
    )
    return receipt.sha256_seal == expected and receipt.receipt_id == f"EWR-{expected[:12].upper()}"


@dataclass(frozen=True)
class CollateralLoan:
    """Short-term inventory-backed loan secured by a pledged Electronic Warehouse Receipt."""

    principal_amount: Decimal
    annual_interest_rate: Decimal  # e.g., Decimal("0.18") for 18% p.a.
    days_elapsed: int
    margin_call_ltv: Decimal = Decimal("0.80")
    liquidation_ltv: Decimal = Decimal("0.90")
    target_restore_ltv: Decimal = Decimal("0.70")
    fixed_fumigation_fee: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class MarkToMarketResult:
    """Daily mark-to-market collateral risk and margin-call obligation."""

    receipt_id: str
    grade_adjusted_price_per_kg: Decimal
    gross_collateral_value: Decimal
    accrued_warehouse_lien: Decimal
    net_collateral_value: Decimal
    max_initial_loan_eligible: Decimal
    total_loan_obligation: Decimal
    current_ltv: Decimal
    status: MarginStatus
    margin_top_up_cash: Decimal
    margin_top_up_kg: Decimal


def evaluate_mark_to_market(
    receipt: WarehouseReceipt,
    loan: CollateralLoan,
    *,
    spot_grade1_price_per_kg: Decimal,
) -> MarkToMarketResult:
    """Mark pledged grain collateral to market, deduct super-priority warehouse lien, and test LTV."""
    if spot_grade1_price_per_kg <= 0:
        raise ValueError("spot_grade1_price_per_kg must be positive")
    if loan.days_elapsed < 0 or loan.principal_amount <= 0:
        raise ValueError("Invalid loan principal or days_elapsed")

    grade_price = (spot_grade1_price_per_kg * GRADE_PRICE_MULTIPLIER[receipt.grade]).quantize(
        _Q4, rounding=ROUND_HALF_UP
    )
    gross_val = (receipt.net_weight_kg * grade_price).quantize(_Q2, rounding=ROUND_HALF_UP)

    tonnes = receipt.net_weight_kg / Decimal("1000")
    storage_lien = (tonnes * receipt.storage_fee_per_tonne_day * Decimal(loan.days_elapsed)).quantize(
        _Q2, rounding=ROUND_HALF_UP
    ) + loan.fixed_fumigation_fee.quantize(_Q2, rounding=ROUND_HALF_UP)

    net_val = max(Decimal("0.00"), gross_val - storage_lien)
    max_initial = (net_val * GRADE_MAX_INITIAL_LTV[receipt.grade]).quantize(_Q2, rounding=ROUND_HALF_UP)

    accrued_int = (
        loan.principal_amount * loan.annual_interest_rate * Decimal(loan.days_elapsed) / Decimal("365")
    ).quantize(_Q2, rounding=ROUND_HALF_UP)
    total_debt = (loan.principal_amount + accrued_int).quantize(_Q2, rounding=ROUND_HALF_UP)

    if net_val <= Decimal("0.00"):
        ltv = Decimal("9.9999")
    else:
        ltv = (total_debt / net_val).quantize(_Q4, rounding=ROUND_HALF_UP)

    if ltv >= loan.liquidation_ltv:
        status = MarginStatus.LIQUIDATION_TRIGGER
    elif ltv >= loan.margin_call_ltv:
        status = MarginStatus.MARGIN_CALL
    else:
        status = MarginStatus.HEALTHY

    if status == MarginStatus.HEALTHY:
        top_up_cash = Decimal("0.00")
        top_up_kg = Decimal("0.00")
    else:
        # Cash repayment needed so (total_debt - cash) / net_val == target_restore_ltv
        target_debt = (net_val * loan.target_restore_ltv).quantize(_Q2, rounding=ROUND_HALF_UP)
        top_up_cash = max(Decimal("0.00"), (total_debt - target_debt).quantize(_Q2, rounding=ROUND_HALF_UP))
        # Or additional collateral kg needed so total_debt / (net_val + add_kg * grade_price) == target_restore_ltv
        needed_net_val = (total_debt / loan.target_restore_ltv).quantize(_Q2, rounding=ROUND_HALF_UP)
        shortfall_val = max(Decimal("0.00"), needed_net_val - net_val)
        top_up_kg = (
            (shortfall_val / grade_price).quantize(_Q2, rounding=ROUND_HALF_UP)
            if grade_price > 0
            else Decimal("0.00")
        )

    return MarkToMarketResult(
        receipt_id=receipt.receipt_id,
        grade_adjusted_price_per_kg=grade_price,
        gross_collateral_value=gross_val,
        accrued_warehouse_lien=storage_lien,
        net_collateral_value=net_val,
        max_initial_loan_eligible=max_initial,
        total_loan_obligation=total_debt,
        current_ltv=ltv,
        status=status,
        margin_top_up_cash=top_up_cash,
        margin_top_up_kg=top_up_kg,
    )
