def last_unit_list_price(item: dict) -> float:
    """
    Returns the LIST price of the 'last' unit (not what they pay after inclusions).
    Always returns a price for at least unit #1, even if requested is 0 or included.
    Tries multiple progressive_breakdown shapes to be robust.
    """
    requested = int(item.get("requested", 0) or 0)
    target_unit = max(1, requested)  # always show unit #1 at minimum

    pb = item.get("progressive_breakdown")

    # 1) If backend already sends a direct unit price, prefer it
    # (some APIs include item['unit_price'] or item['base_unit_price'])
    for k in ["unit_price", "base_unit_price", "list_unit_price"]:
        v = item.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)

    # 2) progressive_breakdown as dict keyed by unit number (string/int)
    if isinstance(pb, dict):
        entry = pb.get(str(target_unit)) or pb.get(target_unit)
        if isinstance(entry, dict):
            for key in ["unit_price", "list_unit_price", "base_unit_price", "net_unit_price"]:
                v = entry.get(key)
                if isinstance(v, (int, float)) and v >= 0:
                    return float(v)

    # 3) progressive_breakdown as list of step dicts
    if isinstance(pb, list):
        # Try to find an entry whose unit index matches target_unit
        for row in pb:
            if not isinstance(row, dict):
                continue
            unit_idx = row.get("unit") or row.get("n") or row.get("index") or row.get("idx")
            try:
                unit_idx = int(unit_idx)
            except Exception:
                unit_idx = None

            if unit_idx == target_unit:
                for key in ["unit_price", "list_unit_price", "base_unit_price", "net_unit_price"]:
                    v = row.get(key)
                    if isinstance(v, (int, float)) and v >= 0:
                        return float(v)

        # If no exact match, use last row as a fallback
        last_row = pb[-1] if pb else None
        if isinstance(last_row, dict):
            for key in ["unit_price", "list_unit_price", "base_unit_price", "net_unit_price"]:
                v = last_row.get(key)
                if isinstance(v, (int, float)) and v >= 0:
                    return float(v)

    # 4) Final fallback: nothing usable found
    return 0.0
