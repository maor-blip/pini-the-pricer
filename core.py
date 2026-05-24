from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import yaml

FeatureKey = str  # 'kpis','channels','countries','users'

# Allowed values for the new modifier inputs
ANALYST_VALUES = {"none", "included"}
REFRESH_VALUES = {"weekly", "biweekly", "daily"}
GRANULARITY_VALUES = {"channel", "channel_and_campaign"}
SALES_CHANNELS_VALUES = {1, 2, 3, 4}


@dataclass
class LicenseDef:
    base_fee: float
    included: Dict[FeatureKey, int]
    unit_prices: Dict[FeatureKey, float]


@dataclass
class Modifiers:
    """
    Multipliers (as percentage adjustments) and flat fees that apply on top of
    the base license + volume add-ons.

    additive_pct values stack additively. e.g. +30, -20, +30 -> +40% -> ×1.40.
    """
    analyst: Dict[str, float]
    refresh: Dict[str, float]
    granularity: Dict[str, float]
    sales_channels: Dict[int, float]
    monthly_report_fee: float


@dataclass
class PriceTables:
    version: str
    licenses: Dict[str, LicenseDef]
    tiers: Dict[FeatureKey, List[Tuple[int, float]]]
    license_discounts: Dict[str, float]
    modifiers: Modifiers


def load_tables(path: str) -> PriceTables:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    licenses = {}
    for name, rec in raw["licenses"].items():
        licenses[name] = LicenseDef(
            base_fee=float(rec.get("base_fee", 0.0)),
            included={k: int(v) for k, v in rec.get("included", {}).items()},
            unit_prices={k: float(v) for k, v in rec.get("unit_prices", {}).items()},
        )

    tiers = {k: [(int(q), float(d)) for q, d in v] for k, v in raw["tiers"].items()}
    license_discounts = {k: float(v) for k, v in raw.get("license_discounts", {}).items()}

    mod_raw = raw.get("modifiers", {}) or {}
    modifiers = Modifiers(
        analyst={k: float(v) for k, v in (mod_raw.get("analyst") or {}).items()},
        refresh={k: float(v) for k, v in (mod_raw.get("refresh") or {}).items()},
        granularity={k: float(v) for k, v in (mod_raw.get("granularity") or {}).items()},
        sales_channels={int(k): float(v) for k, v in (mod_raw.get("sales_channels") or {}).items()},
        monthly_report_fee=float(mod_raw.get("monthly_report_fee", 0.0)),
    )

    return PriceTables(
        version=str(raw.get("version", "v0")),
        licenses=licenses,
        tiers=tiers,
        license_discounts=license_discounts,
        modifiers=modifiers,
    )


def discount_for(count: int, ladder: List[Tuple[int, float]]) -> float:
    d = 0.0
    for q, disc in ladder:
        if count >= q:
            d = disc
        else:
            break
    return d


def progressive_addon_total(unit_price: float, included: int, requested: int, ladder: List[Tuple[int, float]]):
    extras = max(0, requested - included)
    if extras == 0:
        return 0.0, []
    total = 0.0
    trail = []
    for n in range(included + 1, requested + 1):
        disc = discount_for(n, ladder)
        price_n = round(unit_price * (1.0 - disc), 2)
        total += price_n
        trail.append({
            "unit_number": n,
            "discount": disc,
            "unit_price": unit_price,
            "price_after_discount": price_n,
        })
    return round(total, 2), trail


def _validate_modifier_choices(
    analyst: str,
    refresh: str,
    granularity: str,
    sales_channels: int,
) -> None:
    if analyst not in ANALYST_VALUES:
        raise ValueError(f"analyst must be one of {sorted(ANALYST_VALUES)}, got {analyst!r}")
    if refresh not in REFRESH_VALUES:
        raise ValueError(f"refresh must be one of {sorted(REFRESH_VALUES)}, got {refresh!r}")
    if granularity not in GRANULARITY_VALUES:
        raise ValueError(f"granularity must be one of {sorted(GRANULARITY_VALUES)}, got {granularity!r}")
    if sales_channels not in SALES_CHANNELS_VALUES:
        raise ValueError(f"sales_channels must be one of {sorted(SALES_CHANNELS_VALUES)}, got {sales_channels!r}")


def _cascade_positive_modifiers(breakdown: List[dict]) -> List[dict]:
    """
    Apply a cascading 25% haircut to stacked POSITIVE modifiers.

    Sort positive modifiers by their pct descending. The largest is applied at
    100%, the next at 75%, then 50%, then 25%. Negative and zero modifiers are
    always applied at 100%.

    Mutates each item in breakdown by adding:
      - stack_rank: position among positives (1 = largest), or None for non-positive
      - stack_weight: 1.00 / 0.75 / 0.50 / 0.25 / 0.0... (1.0 for non-positive)
      - effective_pct: pct * stack_weight (used in the additive sum)
    """
    positives = [item for item in breakdown if item["pct"] > 0]
    positives.sort(key=lambda x: x["pct"], reverse=True)

    rank_to_weight = {}
    for i, item in enumerate(positives):
        rank = i + 1
        weight = max(0.0, 1.0 - 0.25 * i)  # 1.0, 0.75, 0.50, 0.25, 0.0, ...
        rank_to_weight[id(item)] = (rank, weight)

    for item in breakdown:
        if item["pct"] > 0 and id(item) in rank_to_weight:
            rank, weight = rank_to_weight[id(item)]
            item["stack_rank"] = rank
            item["stack_weight"] = weight
            item["effective_pct"] = round(item["pct"] * weight, 4)
        else:
            item["stack_rank"] = None
            item["stack_weight"] = 1.0
            item["effective_pct"] = round(float(item["pct"]), 4)

    return breakdown


def compute_modifier_adjustments(
    tables: PriceTables,
    analyst: str,
    refresh: str,
    granularity: str,
    sales_channels: int,
    monthly_report: bool,
) -> dict:
    """
    Returns the per-modifier percentage adjustments, the combined additive total
    (after cascading positive-modifier discount), the resulting multiplier, and
    the flat monthly report fee.

    additive total is in percentage points (e.g. 40.0 means +40%).
    multiplier = 1 + additive_total / 100
    """
    mods = tables.modifiers
    breakdown = [
        {"name": "analyst",        "choice": analyst,        "pct": mods.analyst.get(analyst, 0.0)},
        {"name": "refresh",        "choice": refresh,        "pct": mods.refresh.get(refresh, 0.0)},
        {"name": "granularity",    "choice": granularity,    "pct": mods.granularity.get(granularity, 0.0)},
        {"name": "sales_channels", "choice": sales_channels, "pct": mods.sales_channels.get(sales_channels, 0.0)},
    ]

    _cascade_positive_modifiers(breakdown)

    raw_total_pct = round(sum(item["pct"] for item in breakdown), 4)
    additive_total_pct = round(sum(item["effective_pct"] for item in breakdown), 4)
    multiplier = round(1.0 + additive_total_pct / 100.0, 6)
    monthly_report_fee = float(mods.monthly_report_fee) if monthly_report else 0.0

    return {
        "breakdown": breakdown,
        "raw_total_pct": raw_total_pct,
        "additive_total_pct": additive_total_pct,
        "multiplier": multiplier,
        "monthly_report_enabled": bool(monthly_report),
        "monthly_report_fee": round(monthly_report_fee, 2),
    }


def quote(
    tables: PriceTables,
    license_name: str,
    kpis: int,
    channels: int,
    countries: int,
    users: int,
    analyst: str = "none",
    refresh: str = "weekly",
    granularity: str = "channel",
    sales_channels: int = 2,
    monthly_report: bool = False,
) -> dict:
    if license_name not in tables.licenses:
        raise ValueError(f"Unknown license: {license_name}")
    _validate_modifier_choices(analyst, refresh, granularity, sales_channels)

    lic = tables.licenses[license_name]
    out = {
        "license": license_name,
        "version": tables.version,
        "items": [],
        "base_fee": round(lic.base_fee, 2),
        "inputs": {
            "kpis": kpis,
            "channels": channels,
            "countries": countries,
            "users": users,
            "analyst": analyst,
            "refresh": refresh,
            "granularity": granularity,
            "sales_channels": sales_channels,
            "monthly_report": bool(monthly_report),
        },
    }

    # 1) Base + volume add-ons (unchanged from prior versions)
    subtotal = lic.base_fee
    for key, req in [("kpis", kpis), ("channels", channels), ("countries", countries), ("users", users)]:
        unit = float(lic.unit_prices.get(key, 0.0))
        inc = int(lic.included.get(key, 0))
        total, trail = progressive_addon_total(unit, inc, req, tables.tiers[key])
        out["items"].append({
            "key": key,
            "requested": req,
            "included": inc,
            "unit_price": unit,
            "progressive_breakdown": trail,
            "line_total": total,
        })
        subtotal += total

    out["subtotal_before_modifiers"] = round(subtotal, 2)

    # 2) Apply additive modifier stack to subtotal
    mod_info = compute_modifier_adjustments(
        tables, analyst, refresh, granularity, sales_channels, monthly_report
    )
    multiplier = mod_info["multiplier"]
    subtotal_after_modifiers = round(subtotal * multiplier, 2)
    modifier_delta = round(subtotal_after_modifiers - subtotal, 2)

    out["modifiers"] = mod_info
    out["modifier_adjustment_amount"] = modifier_delta
    out["subtotal_after_modifiers"] = subtotal_after_modifiers

    # 3) Apply license-level discount on the modifier-adjusted subtotal
    lic_disc = float(tables.license_discounts.get(license_name, 0.0))
    discount_amount = round(subtotal_after_modifiers * lic_disc, 2)
    after_discount = round(subtotal_after_modifiers - discount_amount, 2)

    out["subtotal_before_license_discount"] = subtotal_after_modifiers
    out["license_discount_pct"] = lic_disc
    out["license_discount_amount"] = discount_amount

    # 4) Add flat monthly report fee on top of everything
    monthly_report_fee = mod_info["monthly_report_fee"]
    total_monthly = round(after_discount + monthly_report_fee, 2)

    out["total_monthly"] = total_monthly
    out["total_annual"] = round(total_monthly * 12, 2)
    return out


def recommend_license(
    tables: PriceTables,
    kpis: int,
    channels: int,
    countries: int,
    users: int,
    analyst: str = "none",
    refresh: str = "weekly",
    granularity: str = "channel",
    sales_channels: int = 2,
    monthly_report: bool = False,
) -> dict:
    quotes = {}
    for lic in tables.licenses.keys():
        q = quote(
            tables, lic, kpis, channels, countries, users,
            analyst=analyst, refresh=refresh, granularity=granularity,
            sales_channels=sales_channels, monthly_report=monthly_report,
        )
        quotes[lic] = q
    best = min(quotes.values(), key=lambda q: q["total_monthly"])
    return {"recommended": best["license"], "quotes": quotes}
