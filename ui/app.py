import os
import json
import requests
import streamlit as st


# ----------------------------
# Config
# ----------------------------
PRICER_API_URL = os.getenv("PRICER_API_URL", "http://localhost:8000").rstrip("/")
APP_TITLE = os.getenv("PRICER_APP_TITLE", "Get a price quote")

# Optional lightweight access gate
# If PRICER_ACCESS_KEY is set, users must enter it once per session.
PRICER_ACCESS_KEY = os.getenv("PRICER_ACCESS_KEY", "").strip()


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


def normalize_unit_prices_from_quote(quote_dict: dict) -> dict:
    """
    Build a fallback unit price map from the quote payload itself.
    Keys are: kpis, channels, countries, users
    """
    out = {}
    for item in quote_dict.get("items", []):
        k = item.get("key")
        v = item.get("unit_price")
        if isinstance(k, str) and isinstance(v, (int, float)) and v > 0:
            out[k.strip().lower()] = float(v)
    return out


def last_unit_list_price(item: dict, fallback_unit_prices: dict | None = None) -> float:
    """
    Returns the LIST price of the 'last' unit (not what they pay after inclusions).
    Always returns a price for at least unit #1.

    Fixes your issue:
    - If there are no add-ons defined (trail is empty) the UI should still show the unit cost.
    - We must not "accept" a 0 from progressive structures and stop early.

    Primary source of truth is item['unit_price'] (your backend includes it per license).
    Secondary: progressive breakdown if it has meaningful list/base price.
    Final: fallback_unit_prices map.
    """
    requested = int(item.get("requested", 0) or 0)
    target_unit = max(1, requested)

    def pick_positive(d: dict, keys: list[str]) -> float | None:
        for k in keys:
            v = d.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
        return None

    # 1) Direct item prices (backend sends unit_price always)
    direct = pick_positive(item, ["unit_price", "base_unit_price", "list_unit_price"])
    if direct is not None:
        return direct

    # 2) progressive_breakdown can be list or dict, try to locate a unit and read a positive price
    pb = item.get("progressive_breakdown")

    if isinstance(pb, dict):
        entry = pb.get(str(target_unit)) or pb.get(target_unit)
        if isinstance(entry, dict):
            picked = pick_positive(entry, ["unit_price", "list_unit_price", "base_unit_price"])
            if picked is not None:
                return picked

    if isinstance(pb, list) and pb:
        # Try to match by unit index keys
        for row in pb:
            if not isinstance(row, dict):
                continue
            unit_idx = row.get("unit") or row.get("unit_number") or row.get("n") or row.get("index") or row.get("idx")
            try:
                unit_idx = int(unit_idx)
            except Exception:
                unit_idx = None

            if unit_idx == target_unit:
                picked = pick_positive(row, ["unit_price", "list_unit_price", "base_unit_price"])
                if picked is not None:
                    return picked

        # last row fallback
        last_row = pb[-1]
        if isinstance(last_row, dict):
            picked = pick_positive(last_row, ["unit_price", "list_unit_price", "base_unit_price"])
            if picked is not None:
                return picked

    # 3) Final fallback: provided unit_prices map
    if isinstance(fallback_unit_prices, dict):
        key = item.get("key") or item.get("code") or item.get("slug") or item.get("name")
        if isinstance(key, str):
            v = fallback_unit_prices.get(key.strip().lower())
            if isinstance(v, (int, float)) and v > 0:
                return float(v)

    return 0.0


def unit_number_label(item: dict) -> int:
    requested = int(item.get("requested", 0) or 0)
    return max(1, requested)


def require_access_key_if_configured():
    """
    Simple, reliable gate:
    - If PRICER_ACCESS_KEY is empty: no gate.
    - If set: show a sign-in box and block the app until correct.
    """
    if not PRICER_ACCESS_KEY:
        return

    if st.session_state.get("authed", False):
        return

    st.title(APP_TITLE)
    st.caption(f"API: {PRICER_API_URL}")

    st.subheader("Sign in")
    st.write("Enter the access key to continue.")
    key = st.text_input("Access key", type="password")

    cols = st.columns([1, 3])
    with cols[0]:
        if st.button("Sign in", use_container_width=True):
            if key.strip() == PRICER_ACCESS_KEY:
                st.session_state["authed"] = True
                st.rerun()
            else:
                st.error("Nope. Wrong key.")

    st.stop()


# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
require_access_key_if_configured()

st.title(APP_TITLE)
st.caption(f"API: {PRICER_API_URL}")

tab_quote, tab_sales = st.tabs(["Quote", "Sales assistant"])

with tab_quote:
    left, right = st.columns(2)

    with left:
        st.subheader("Inputs")

        kpis = st.number_input("KPIs", min_value=0, value=1, step=1)
        channels = st.number_input("Channels", min_value=0, value=1, step=1)

    with right:
        countries = st.number_input("Countries", min_value=0, value=1, step=1)
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

        # Two possible shapes:
        # 1) recommendation: {"recommended": "...", "quotes": {...}}
        # 2) direct quote: {"license": "...", "items": [...], ...}
        if "recommended" in result and "quotes" in result:
            recommended = result.get("recommended")
            st.subheader(f"Recommended: {recommended}")

            q = result["quotes"].get(recommended)
            if not q:
                st.error("Recommendation returned, but recommended quote missing. That should not happen.")
                st.json(result)
                st.stop()

            quote_obj = q
        else:
            quote_obj = result
            st.subheader(f"Selected: {quote_obj.get('license', '(unknown)')}")

        total_monthly = quote_obj.get("total_monthly", 0.0)
        total_annual = quote_obj.get("total_annual", 0.0)
        lic_disc_pct = quote_obj.get("license_discount_pct", 0.0)
        lic_disc_amt = quote_obj.get("license_discount_amount", 0.0)

        st.write("**Total Monthly (USD)**")
        st.write(f"### {money(total_monthly)}")

        st.write(f"License discount: {int(float(lic_disc_pct) * 100)}% -> {money(lic_disc_amt)}")
        st.write("")
        st.write("**Annual (USD)**")
        st.write(f"### {money(total_annual)}")

        st.divider()

        # Unit costs (last unit)
        st.subheader("Unit cost (last unit)")

        fallback_unit_prices = normalize_unit_prices_from_quote(quote_obj)
        items = quote_obj.get("items", [])

        if not items:
            st.info("No items returned.")
        else:
            lines = []
            for item in items:
                key = (item.get("key") or "").strip().lower()
                unit_n = unit_number_label(item)
                price = last_unit_list_price(item, fallback_unit_prices=fallback_unit_prices)

                # This is the exact behavior you want:
                # SMB with no add-ons still shows KPI #1 = 999, channels #1 = 199, etc.
                lines.append(f"- {key} #{unit_n}: {money(price)}/mo")

            st.markdown("\n".join(lines))

        st.divider()

        # Show details table
        st.subheader("Line items")
        for item in items:
            key = item.get("key", "")
            req = item.get("requested", 0)
            inc = item.get("included", 0)
            unit_price = item.get("unit_price", 0.0)
            line_total = item.get("line_total", 0.0)

            with st.expander(f"{key} (requested {req}, included {inc})"):
                st.write(f"Unit price: {money(unit_price)}/unit")
                st.write(f"Add-on total: {money(line_total)}/mo")

                trail = item.get("progressive_breakdown", [])
                if trail:
                    st.write("Progressive breakdown")
                    st.json(trail)
                else:
                    st.caption("No add-ons for this item (requested within included).")

        st.divider()

        st.subheader("Raw quote payload")
        st.json(quote_obj)


with tab_sales:
    st.subheader("Sales assistant")
    st.caption("Optional. Requires OPENAI_API_KEY in the environment. If missing, this will just show a friendly error.")

    prompt = st.text_area(
        "What do you want to say to the prospect?",
        value="Write a short explanation of the quote and why this package fits.",
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
