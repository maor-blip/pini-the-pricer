import os
import requests
import streamlit as st


# ----------------------------
# Config
# ----------------------------
PRICER_API_URL = os.getenv("PRICER_API_URL", "http://localhost:8000").rstrip("/")
APP_TITLE = "Pini the Pricer"

IMAGE_URL = "https://incrmntal-website.s3.amazonaws.com/Pinilogo_efa5df4e90.png?updated_at=2025-09-09T08:07:49.998Z"


# ----------------------------
# Header
# ----------------------------
def render_header():
    user = st.session_state.get("user", {})

    st.markdown(
        f"""
<div style="display:flex; align-items:center; justify-content:space-between; padding:4px 0 8px 0;">
  <div style="display:flex; align-items:center; gap:12px;">
    <h1 style="margin:0;">{APP_TITLE}</h1>
    <div style="font-size:0.9rem; opacity:0.8;">{user.get('email','')}</div>
  </div>
  <img src="{IMAGE_URL}" alt="INCRMNTAL" style="height:100px; max-height:100px; object-fit:contain;" />
</div>
""",
        unsafe_allow_html=True,
    )
    st.caption(f"API: {PRICER_API_URL}")


# ----------------------------
# Auth
# ----------------------------
def _get_access_key() -> str:
    candidates = [
        os.getenv("PRICER_ACCESS_KEY", ""),
        os.getenv("APP_ACCESS_KEY", ""),
        os.getenv("APP_PASSWORD", ""),
        os.getenv("STREAMLIT_PASSWORD", ""),
    ]
    for v in candidates:
        if v and v.strip():
            return v.strip()

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

    if not access_key:
        st.warning(
            "Auth is NOT configured. This app is publicly accessible.\n\n"
            "Set one of these secrets/env vars: PRICER_ACCESS_KEY, APP_ACCESS_KEY, APP_PASSWORD, STREAMLIT_PASSWORD."
        )
        return

    if st.session_state.get("authed"):
        return

    render_header()

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


def unit_number_label(item: dict) -> int:
    requested = int(item.get("requested", 0) or 0)
    return max(1, requested)


def last_unit_cost_display(item: dict) -> float:
    """
    - If there are no add-ons priced (requested <= included OR line_total == 0),
      show the base unit_price (from unit cost table).

    - If there ARE add-ons (requested > included AND line_total > 0),
      show the cost of the last add-on unit.
      Prefer progressive_breakdown if present, otherwise derive from line_total.
    """
    requested = int(item.get("requested", 0) or 0)
    included = int(item.get("included", 0) or 0)

    base_unit = item.get("unit_price")
    if not isinstance(base_unit, (int, float)):
        base_unit = 0.0
    base_unit = float(base_unit)

    line_total = item.get("line_total", 0.0)
    if not isinstance(line_total, (int, float)):
        line_total = 0.0
    line_total = float(line_total)

    # No add-ons => show base unit
    if requested <= included or line_total <= 0:
        return base_unit if base_unit > 0 else 0.0

    # Add-ons exist => show last add-on unit cost
    target_unit = max(1, requested)
    pb = item.get("progressive_breakdown")

    if isinstance(pb, list) and pb:
        for row in pb:
            if not isinstance(row, dict):
                continue

            unit_n = row.get("unit_number") or row.get("unit") or row.get("n") or row.get("index")
            try:
                unit_n = int(unit_n)
            except Exception:
                unit_n = None

            if unit_n == target_unit:
                for k in ["price_after_discount", "net_unit_price", "addon_unit_price", "unit_price_after_discount"]:
                    v = row.get(k)
                    if isinstance(v, (int, float)) and float(v) > 0:
                        return float(v)

        last_row = pb[-1]
        if isinstance(last_row, dict):
            for k in ["price_after_discount", "net_unit_price", "addon_unit_price", "unit_price_after_discount"]:
                v = last_row.get(k)
                if isinstance(v, (int, float)) and float(v) > 0:
                    return float(v)

    addon_units = requested - included
    if addon_units > 0:
        return line_total / float(addon_units)

    return 0.0


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
        price = last_unit_cost_display(item)
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

render_header()

tab_quote, tab_sales = st.tabs(["Quote", "Sales assistant"])

with tab_quote:
    st.subheader("Inputs")

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

            with st.expander("Debug: raw payload", expanded=False):
                st.json(result)

        else:
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
                    {"role": "system", "content": "You are a crisp, helpful pricing sales assistant. Keep it short and practical."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
            )
            out = resp.choices[0].message.content
            st.write(out)
        except Exception as e:
            st.error(f"OpenAI call failed: {e}")
