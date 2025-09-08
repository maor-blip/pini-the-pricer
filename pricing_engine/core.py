from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple
import yaml

FeatureKey = str  # 'kpis','channels','countries','users'

@dataclass
class LicenseDef:
    base_fee: float
    included: Dict[FeatureKey, int]
    unit_prices: Dict[FeatureKey, float]

@dataclass
class PriceTables:
    version: str
    licenses: Dict[str, LicenseDef]
    tiers: Dict[FeatureKey, List[Tuple[int, float]]]
    license_discounts: Dict[str, float]

def load_tables(path: str) -> PriceTables:
    with open(path, 'r') as f:
        raw = yaml.safe_load(f)
    licenses = {}
    for name, rec in raw['licenses'].items():
        licenses[name] = LicenseDef(
            base_fee = float(rec.get('base_fee', 0.0)),
            included = {k:int(v) for k,v in rec.get('included', {}).items()},
            unit_prices = {k:float(v) for k,v in rec.get('unit_prices', {}).items()},
        )
    tiers = {k:[(int(q), float(d)) for q,d in v] for k,v in raw['tiers'].items()}
    license_discounts = {k: float(v) for k,v in raw.get('license_discounts', {}).items()}
    return PriceTables(
        version=str(raw.get('version','v0')),
        licenses=licenses,
        tiers=tiers,
        license_discounts=license_discounts
    )

def discount_for(count: int, ladder: List[Tuple[int,float]]) -> float:
    d = 0.0
    for q,disc in ladder:
        if count >= q:
            d = disc
        else:
            break
    return d

def progressive_addon_total(unit_price: float, included: int, requested: int, ladder: List[Tuple[int,float]]):
    extras = max(0, requested - included)
    if extras == 0:
        return 0.0, []
    total = 0.0
    trail = []
    for n in range(included+1, requested+1):
        disc = discount_for(n, ladder)
        price_n = round(unit_price * (1.0 - disc), 2)
        total += price_n
        trail.append({
            "unit_number": n,
            "discount": disc,
            "unit_price": unit_price,
            "price_after_discount": price_n
        })
    return round(total, 2), trail

def quote(tables: PriceTables, license_name: str, kpis:int, channels:int, countries:int, users:int) -> dict:
    lic = tables.licenses[license_name]
    out = {
        "license": license_name,
        "version": tables.version,
        "items": [],
        "base_fee": round(lic.base_fee, 2),
    }
    subtotal = lic.base_fee
    for key, req in [("kpis",kpis),("channels",channels),("countries",countries),("users",users)]:
        unit = float(lic.unit_prices.get(key, 0.0))
        inc = int(lic.included.get(key, 0))
        total, trail = progressive_addon_total(unit, inc, req, tables.tiers[key])
        out["items"].append({
            "key": key,
            "requested": req,
            "included": inc,
            "unit_price": unit,
            "progressive_breakdown": trail,
            "line_total": total
        })
        subtotal += total
    # Apply license level discount to subtotal (base + all add-ons)
    lic_disc = float(tables.license_discounts.get(license_name, 0.0))
    discount_amount = round(subtotal * lic_disc, 2)
    total_after_discount = round(subtotal - discount_amount, 2)
    out["subtotal_before_license_discount"] = round(subtotal, 2)
    out["license_discount_pct"] = lic_disc
    out["license_discount_amount"] = discount_amount
    out["total_monthly"] = total_after_discount
    out["total_annual"] = round(total_after_discount * 12, 2)
    return out

def recommend_license(tables: PriceTables, kpis:int, channels:int, countries:int, users:int) -> dict:
    quotes = {}
    for lic in tables.licenses.keys():
        q = quote(tables, lic, kpis, channels, countries, users)
        quotes[lic] = q
    best = min(quotes.values(), key=lambda q: q["total_monthly"])
    return {"recommended": best["license"], "quotes": quotes}
