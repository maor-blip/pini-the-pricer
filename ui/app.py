import os
import requests
import streamlit as st


# ----------------------------
# Config
# ----------------------------
PRICER_API_URL = os.getenv("PRICER_API_URL", "http://localhost:8000").rstrip("/")
APP_TITLE = os.getenv("PRICER_APP_TITLE", "Get a price quote")


# ----------------------------
# Auth
# ----------------------------
def _get_access_key() -> str:
    """
    Supports multiple names so you can keep your existing Render env var.
    Pick ONE in Render and you're good.
    """
    candidates = [
        os.getenv("PRICER_ACCESS_KEY", ""),
        os.getenv("APP_ACCESS_KEY", ""),
        os.getenv("APP_PASSWORD", ""),
        os.getenv("STREAMLIT_PASSWORD", ""),
    ]
    for v in candidates:
        if v and v.strip():
            return v.strip()

    # Also allow Streamlit secrets if you're using those
    try:
        v = st.secrets.get("PRICER_ACCESS_KEY", "")  # type: ignore[attr-defined]
        if v and str(v).strip():
            return str(v).strip()
    except Exception:
        pass

    try:
        v = st.secrets.get("APP_PASSWORD", "")  # type: ignore[attr-defined]
        if v and str(v).strip():
            return str(v).strip()
    except Exception:
        pass

    return ""


def require_login():
    access_key = _get_access_key()

    # If no key is configured, we do NOT block (useful for local dev),
    # but we show a loud warning because you said "open to the world" is bad.
    if not access_key:
        st.warning(
            "Auth is NOT configured. This app is publicly accessible.\n\n"
            "Set one of these env vars in Render: PRICER_ACCESS_KEY, APP_ACCESS_KEY, APP_PASSWORD, STREAMLIT_PASSWORD."
        )
        return

    if st.session_state.get("authed"):
        return

    st.title(APP_TITLE)
    st.caption(f"API: {PRICER_API_URL}")

    st.subheader("Sign in")
    entered = st.text_input("Access key", type="password")

    col_a, col_b = st.columns([1, 5])
    with col_a:
        if st.button("Sign in", use_container_width=True):
            if entered.strip() == access_key:
                st.session_state["authed"] = True
                st.rerun()
            else:
                st.error("Wrong key.")

    st.stop()


# ----------------------------
# Helpers
# ----------------------------
def money(x: float) -> str:
    try:
        return f"${float(x):,.0f}"
    except Exception:
        return "$0"


def call_quote_api(payload: dict) -> dict:
    url = f"{PRICER_API_URL}/quote"
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def last_unit_list_price(item: dict) -> float:
    """
    Your original issue:
    - When progressive_breakdown is empty (no add-ons), UI showed 0.
    The correct "unit cost (last unit)" for packages with no add-ons is still the unit_price.

    This function always returns item['unit_price'] when present and > 0.
    Only falls back to progressive breakdown if needed.
    """
    v = item.get("unit_price")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)

    requested = int(item.get("requested", 0) or 0)
    target_unit = max(1, requested)
    pb = item.get("progressive_breakdown")

    # If breakdown exists, try to infer list unit price from it
    # (your backend trail uses unit_price and price_after_discount)
    if isinstance(pb, list) and pb:
        # If there is an entry for the target unit, use its unit_price if present
        for row in pb:
            if not isinstance(row, dict):
                continue
            unit_n = row.get("unit_number") or row.get("unit") or row.get("n")
            try:
                unit_n = int(unit_n)
            except Exception:
                unit_n = None
            if unit_n == target_unit:
                uv = row.get("unit_price")
                if isinstance(uv, (int, float)) and uv > 0:
                    return float(uv)

        # Otherwise use the last row's unit_price as best effort
        last_row = pb[-1]
        if isinstance(last_row, dict):
            uv = last_row.get("unit_price")
            if isinstance(uv, (int, float)) and uv > 0:
                return float(uv)

    return 0.0


def unit_number_label(item: dict) -> int:
    requested = int(item.get("requested", 0) or 0)
    return max(1, requested)


def render_unit_costs_block(quote_obj: dict):
    st.subheader("Unit cost (last unit)")
    items = quote_obj.get("items", []) or []

    if not items:
        st.info("No items returned.")
        return

    lines = []
    for item in items:
        key = (item.get("key") or "").strip().lower()
        unit_n = unit_number_label(item)
        price = last_unit_list_price(item)
        lines.append(f"- {key} #{unit_n}: {money(price)}/mo")

    st.markdown("\n".join(lines))


def render_quote_summary(quote_obj: dict):
    total_monthly = quote_obj.get("total_monthly", 0.0)
    total_annual = quote_obj.get("total_annual", 0.0)
    lic_disc_pct = quote_obj.get("license_discount_pct", 0.0)
    lic_disc_amt = quote_obj.get("license_discount_amount", 0.0)

    st.write("**Total Monthly (USD)**")
    st.write(f"### {money(total_monthly)}")

    try:
        pct = int(float(lic_disc_pct) * 100)
    except Exception:
        pct = 0

    st.write(f"License discount: {pct}% -> {money(lic_disc_amt)}")
    st.write("")
    st.write("**Annual (USD)**")
    st.write(f"### {money(total_annual)}")


def render_all_licenses_table(result: dict, recommended: str):
    """
    Shows what you said you miss:
    - totals for every license, not only the recommended one
    """
    quotes = result.get("quotes", {}) or {}
    if not quotes:
        return

    rows = []
    for lic_name, q in quotes.items():
        rows.append(
            {
                "License": lic_name,
                "Monthly": q.get("total_monthly", 0.0),
                "Annual": q.get("total_annual", 0.0),
                "Discount %": q.get("license_discount_pct", 0.0),
            }
        )

    # Sort by monthly ascending
    rows.sort(key=lambda r: float(r.get("Monthly", 0.0) or 0.0))

    st.subheader("All licenses")
    for r in rows:
        r["Monthly"] = money(r["Monthly"])
        r["Annual"] = money(r["Annual"])
        try:
            r["Discount %"] = f"{int(float(r['Discount %']) * 100)}%"
        except Exception:
            r["Discount %"] = "0%"

    st.table(rows)

    st.caption(f"Recommended: {recommended}")


# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
require_login()

st.title(APP_TITLE)
st.caption(f"API: {PRICER_API_URL}")

tab_quote, tab_sales = st.tabs(["Quote", "Sales assistant"])

with tab_quote:
    st.subheader("Inputs")

    # 4 equal columns fixes the alignment problem you showed
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpis = st.number_input("KPIs", min_value=0, value=1, step=1)
    with c2:
        channels = st.number_input("Channels", min_value=0, value=1, step=1)
    with c3:
        countries = st.number_input("Countries", min_value=0, value=1, step=1)
    with c4:
        users = st.number_input("Users (Admins)", min_value=0, value=1, step=1)

    st.write("")
    force_license = st.text_input("Force license (optional)", value="(auto)")
    force_license_clean = force_license.strip()
    if force_license_clean == "(auto)" or force_license_clean == "":
        force_license_clean = None

    if st.button("Get quote"):
        payload = {
            "license": force_license_clean,
            "kpis": int(kpis),
            "channels": int(channels),
            "countries": int(countries),
            "users": int(users),
        }

        try:
            result = call_quote_api(payload)
        except requests.HTTPError as e:
            st.error(f"API error: {e}")
            try:
                st.code(e.response.text)
            except Exception:
                pass
            st.stop()
        except Exception as e:
            st.error(f"Error calling API: {e}")
            st.stop()

        st.divider()

        # If API returns recommendation mode, show all licenses + the recommended license details
        if "recommended" in result and "quotes" in result:
            recommended = result.get("recommended", "")
            render_all_licenses_table(result, recommended)

            quote_obj = (result.get("quotes") or {}).get(recommended)
            if not quote_obj:
                st.error("Recommendation returned, but the recommended quote is missing.")
                with st.expander("Debug", expanded=False):
                    st.json(result)
                st.stop()

            st.divider()
            st.subheader(f"Recommended license details: {recommended}")
            render_quote_summary(quote_obj)
            st.divider()
            render_unit_costs_block(quote_obj)

            # Optional per-license breakdown (handy for sales)
            with st.expander("Compare line items by license", expanded=False):
                quotes = result.get("quotes", {}) or {}
                for lic_name, q in quotes.items():
                    st.markdown(f"#### {lic_name} - {money(q.get('total_monthly', 0.0))}/mo")
                    for item in (q.get("items") or []):
                        key = item.get("key", "")
                        req = item.get("requested", 0)
                        inc = item.get("included", 0)
                        unit_price = item.get("unit_price", 0.0)
                        line_total = item.get("line_total", 0.0)
                        st.write(
                            f"- {key}: requested {req}, included {inc}, unit {money(unit_price)}, add-ons {money(line_total)}/mo"
                        )
                    st.write("")

            # Hide raw payload, do not dump it in the page
            with st.expander("Debug: raw payload", expanded=False):
                st.json(result)

        else:
            # Forced license mode (single quote)
            quote_obj = result
            lic = quote_obj.get("license", "(unknown)")
            st.subheader(f"Selected: {lic}")

            render_quote_summary(quote_obj)
            st.divider()
            render_unit_costs_block(quote_obj)

            with st.expander("Line items", expanded=False):
                for item in (quote_obj.get("items") or []):
                    key = item.get("key", "")
                    req = item.get("requested", 0)
                    inc = item.get("included", 0)
                    unit_price = item.get("unit_price", 0.0)
                    line_total = item.get("line_total", 0.0)
                    trail = item.get("progressive_breakdown", [])

                    st.markdown(f"**{key}**")
                    st.write(f"Requested: {req} | Included: {inc}")
                    st.write(f"Unit price: {money(unit_price)}")
                    st.write(f"Add-ons total: {money(line_total)}/mo")

                    if trail:
                        st.caption("Progressive breakdown")
                        st.json(trail)
                    st.write("")

            with st.expander("Debug: raw payload", expanded=False):
                st.json(quote_obj)

with tab_sales:
    st.subheader("Sales assistant")
    st.caption("Optional. Requires OPENAI_API_KEY in the environment.")

    prompt = st.text_area(
        "What do you want to say to the prospect?",
        value="Write a short explanation of the quote and why this package fits. Keep it crisp.",
        height=120,
    )

    if st.button("Generate"):
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            st.error("OPENAI_API_KEY is not set. Add it to your environment and redeploy.")
            st.stop()

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)

            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a crisp, helpful pricing sales assistant. Keep it short and practical.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
            )
            out = resp.choices[0].message.content
            st.write(out)
        except Exception as e:
            st.error(f"OpenAI call failed: {e}")
