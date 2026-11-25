"""EAGC/EAS commodity grading, aflatoxin safety gates, and exact dry-matter moisture shrinkage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

_Q2 = Decimal("0.01")
_HUNDRED = Decimal("100")


class Grade(StrEnum):
    GRADE_1 = "grade_1"
    GRADE_2 = "grade_2"
    GRADE_3 = "grade_3"
    REJECT = "reject"


@dataclass(frozen=True)
class CommodityStandard:
    """East African Standard (EAS) / EAGC warehouse storage and grading limits."""

    key: str
    display_name: str
    standard_code: str
    standard_moisture_pct: Decimal
    max_intake_moisture_pct: Decimal
    max_aflatoxin_ppb: Decimal
    g1_max_fm_pct: Decimal
    g2_max_fm_pct: Decimal
    g3_max_fm_pct: Decimal
    g1_max_damaged_pct: Decimal
    g2_max_damaged_pct: Decimal
    g3_max_damaged_pct: Decimal
    handling_shrink_pct: Decimal = Decimal("0.5")


COMMODITY_STANDARDS: dict[str, CommodityStandard] = {
    "maize": CommodityStandard(
        key="maize",
        display_name="Dry Shelled Maize",
        standard_code="EAS 2:2017",
        standard_moisture_pct=Decimal("13.5"),
        max_intake_moisture_pct=Decimal("22.0"),
        max_aflatoxin_ppb=Decimal("10.0"),
        g1_max_fm_pct=Decimal("0.5"),
        g2_max_fm_pct=Decimal("1.0"),
        g3_max_fm_pct=Decimal("1.5"),
        g1_max_damaged_pct=Decimal("2.0"),
        g2_max_damaged_pct=Decimal("4.0"),
        g3_max_damaged_pct=Decimal("6.0"),
    ),
    "beans": CommodityStandard(
        key="beans",
        display_name="Dry Beans",
        standard_code="EAS 46:2017",
        standard_moisture_pct=Decimal("14.0"),
        max_intake_moisture_pct=Decimal("20.0"),
        max_aflatoxin_ppb=Decimal("10.0"),
        g1_max_fm_pct=Decimal("0.5"),
        g2_max_fm_pct=Decimal("1.0"),
        g3_max_fm_pct=Decimal("1.5"),
        g1_max_damaged_pct=Decimal("2.0"),
        g2_max_damaged_pct=Decimal("4.0"),
        g3_max_damaged_pct=Decimal("6.0"),
    ),
    "robusta_coffee": CommodityStandard(
        key="robusta_coffee",
        display_name="Robusta Coffee (Green FAQ)",
        standard_code="EAS 105",
        standard_moisture_pct=Decimal("12.5"),
        max_intake_moisture_pct=Decimal("18.0"),
        max_aflatoxin_ppb=Decimal("10.0"),
        g1_max_fm_pct=Decimal("0.3"),
        g2_max_fm_pct=Decimal("0.8"),
        g3_max_fm_pct=Decimal("1.5"),
        g1_max_damaged_pct=Decimal("3.0"),
        g2_max_damaged_pct=Decimal("6.0"),
        g3_max_damaged_pct=Decimal("12.0"),
    ),
    "sorghum": CommodityStandard(
        key="sorghum",
        display_name="Dry Sorghum Grains",
        standard_code="EAS 757",
        standard_moisture_pct=Decimal("13.5"),
        max_intake_moisture_pct=Decimal("20.0"),
        max_aflatoxin_ppb=Decimal("10.0"),
        g1_max_fm_pct=Decimal("0.5"),
        g2_max_fm_pct=Decimal("1.0"),
        g3_max_fm_pct=Decimal("2.0"),
        g1_max_damaged_pct=Decimal("2.0"),
        g2_max_damaged_pct=Decimal("4.0"),
        g3_max_damaged_pct=Decimal("6.0"),
    ),
    "sesame": CommodityStandard(
        key="sesame",
        display_name="Sesame Seeds (Simsim)",
        standard_code="EAS 895",
        standard_moisture_pct=Decimal("7.0"),
        max_intake_moisture_pct=Decimal("12.0"),
        max_aflatoxin_ppb=Decimal("10.0"),
        g1_max_fm_pct=Decimal("1.0"),
        g2_max_fm_pct=Decimal("2.0"),
        g3_max_fm_pct=Decimal("3.0"),
        g1_max_damaged_pct=Decimal("1.0"),
        g2_max_damaged_pct=Decimal("2.0"),
        g3_max_damaged_pct=Decimal("4.0"),
    ),
}


def get_commodity_standard(key: str) -> CommodityStandard:
    norm = key.strip().lower().replace("-", "_").replace(" ", "_")
    if norm not in COMMODITY_STANDARDS:
        raise KeyError(f"Unknown commodity '{key}'. Available: {', '.join(sorted(COMMODITY_STANDARDS))}")
    return COMMODITY_STANDARDS[norm]


def moisture_shrinkage_weight(
    clean_weight_kg: Decimal,
    intake_moisture_pct: Decimal,
    target_moisture_pct: Decimal,
    handling_shrink_pct: Decimal = Decimal("0.5"),
) -> Decimal:
    """Exact dry-matter-conserving moisture weight shrinkage.

    W_dry = W_clean * (100 - M_in) / (100 - M_std) * (1 - handling_shrink/100)
    when M_in > M_std; no moisture weight gain is credited if M_in <= M_std.
    """
    if clean_weight_kg <= 0:
        raise ValueError("clean_weight_kg must be positive")
    if intake_moisture_pct <= target_moisture_pct:
        return clean_weight_kg.quantize(_Q2, rounding=ROUND_HALF_UP)
    dry_ratio = (_HUNDRED - intake_moisture_pct) / (_HUNDRED - target_moisture_pct)
    handling_factor = (_HUNDRED - handling_shrink_pct) / _HUNDRED
    return (clean_weight_kg * dry_ratio * handling_factor).quantize(_Q2, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DeliveryLot:
    """Raw grain/commodity lot delivered to a certified warehouse."""

    commodity: str
    gross_weight_kg: Decimal
    intake_moisture_pct: Decimal
    foreign_matter_pct: Decimal
    damaged_grain_pct: Decimal
    aflatoxin_ppb: Decimal = Decimal("0")


@dataclass(frozen=True)
class IntakeResult:
    """Certified net receipted weight, assigned EAGC grade, and deductions."""

    commodity: str
    standard_code: str
    gross_weight_kg: Decimal
    foreign_matter_deduction_kg: Decimal
    moisture_shrink_deduction_kg: Decimal
    net_receipted_weight_kg: Decimal
    drying_required: bool
    grade: Grade
    eligible_for_receipt: bool
    rejection_reasons: tuple[str, ...]


def evaluate_delivery_intake(lot: DeliveryLot) -> IntakeResult:
    """Clean, dry-shrink, aflatoxin-screen, and grade a warehouse delivery lot."""
    std = get_commodity_standard(lot.commodity)
    if lot.gross_weight_kg <= 0:
        raise ValueError("gross_weight_kg must be positive")

    reasons: list[str] = []
    if lot.aflatoxin_ppb > std.max_aflatoxin_ppb:
        reasons.append(
            f"AFLATOXIN REJECT: {lot.aflatoxin_ppb} ppb exceeds EAS limit {std.max_aflatoxin_ppb} ppb."
        )
    if lot.intake_moisture_pct > std.max_intake_moisture_pct:
        reasons.append(
            f"EXCESSIVE MOISTURE REJECT: {lot.intake_moisture_pct}% exceeds max intake {std.max_intake_moisture_pct}%."
        )

    fm_deduct = (lot.gross_weight_kg * (lot.foreign_matter_pct / _HUNDRED)).quantize(_Q2, rounding=ROUND_HALF_UP)
    clean_kg = max(Decimal("0.00"), lot.gross_weight_kg - fm_deduct)
    drying_needed = lot.intake_moisture_pct > std.standard_moisture_pct

    if clean_kg > 0 and drying_needed:
        net_kg = moisture_shrinkage_weight(
            clean_kg,
            lot.intake_moisture_pct,
            std.standard_moisture_pct,
            std.handling_shrink_pct,
        )
    else:
        net_kg = clean_kg
    moisture_deduct = (clean_kg - net_kg).quantize(_Q2, rounding=ROUND_HALF_UP)

    if reasons:
        grade = Grade.REJECT
    elif lot.foreign_matter_pct <= std.g1_max_fm_pct and lot.damaged_grain_pct <= std.g1_max_damaged_pct:
        grade = Grade.GRADE_1
    elif lot.foreign_matter_pct <= std.g2_max_fm_pct and lot.damaged_grain_pct <= std.g2_max_damaged_pct:
        grade = Grade.GRADE_2
    elif lot.foreign_matter_pct <= std.g3_max_fm_pct and lot.damaged_grain_pct <= std.g3_max_damaged_pct:
        grade = Grade.GRADE_3
    else:
        grade = Grade.REJECT
        reasons.append(
            f"QUALITY DEFECT REJECT: foreign matter {lot.foreign_matter_pct}% / damaged {lot.damaged_grain_pct}% "
            "exceeds Grade 3 limits."
        )

    return IntakeResult(
        commodity=std.key,
        standard_code=std.standard_code,
        gross_weight_kg=lot.gross_weight_kg.quantize(_Q2, rounding=ROUND_HALF_UP),
        foreign_matter_deduction_kg=fm_deduct,
        moisture_shrink_deduction_kg=moisture_deduct,
        net_receipted_weight_kg=net_kg,
        drying_required=drying_needed,
        grade=grade,
        eligible_for_receipt=grade != Grade.REJECT,
        rejection_reasons=tuple(reasons),
    )
