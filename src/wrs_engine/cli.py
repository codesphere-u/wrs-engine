"""CLI entrypoint for wrs-engine."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from .collateral import CollateralLoan, MarginStatus, evaluate_mark_to_market, issue_warehouse_receipt
from .grading import DeliveryLot, evaluate_delivery_intake


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wrs-engine",
        description="Grade commodity lots, apply exact moisture shrinkage, issue sealed EWRs, and check LTV margin.",
    )
    parser.add_argument(
        "--commodity",
        default="maize",
        help="Commodity key (maize, beans, robusta_coffee, sorghum, sesame).",
    )
    parser.add_argument("--gross-kg", type=Decimal, default=Decimal("10000"), help="Gross intake weight kg.")
    parser.add_argument("--moisture", type=Decimal, default=Decimal("17.5"), help="Intake moisture percent.")
    parser.add_argument("--fm", type=Decimal, default=Decimal("0.4"), help="Foreign matter percent.")
    parser.add_argument("--damaged", type=Decimal, default=Decimal("1.5"), help="Damaged grain percent.")
    parser.add_argument("--aflatoxin", type=Decimal, default=Decimal("3.0"), help="Aflatoxin ppb.")
    parser.add_argument("--spot-price", type=Decimal, default=Decimal("0.32"), help="Grade 1 spot price per kg.")
    parser.add_argument("--loan", type=Decimal, default=Decimal("2000"), help="Pledged loan principal.")
    parser.add_argument("--days", type=int, default=60, help="Storage and loan days elapsed.")
    args = parser.parse_args(argv)

    intake = evaluate_delivery_intake(
        DeliveryLot(
            commodity=args.commodity,
            gross_weight_kg=args.gross_kg,
            intake_moisture_pct=args.moisture,
            foreign_matter_pct=args.fm,
            damaged_grain_pct=args.damaged,
            aflatoxin_ppb=args.aflatoxin,
        )
    )
    if not intake.eligible_for_receipt:
        print(json.dumps({"intake": asdict(intake)}, indent=2, default=_json_default))
        return 1

    ewr = issue_warehouse_receipt(intake, warehouse_id="WH-MASINDI-01", depositor_id="COOP-001")
    mtm = evaluate_mark_to_market(
        ewr,
        CollateralLoan(principal_amount=args.loan, annual_interest_rate=Decimal("0.18"), days_elapsed=args.days),
        spot_grade1_price_per_kg=args.spot_price,
    )
    print(
        json.dumps(
            {"intake": asdict(intake), "receipt": asdict(ewr), "mark_to_market": asdict(mtm)},
            indent=2,
            default=_json_default,
        )
    )
    return 0 if mtm.status == MarginStatus.HEALTHY else 1


if __name__ == "__main__":
    raise SystemExit(main())
