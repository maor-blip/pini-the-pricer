
import os, requests, json
import streamlit as st

API_URL = os.getenv("PRICER_API_URL", "http://localhost:8000")

st.set_page_config(page_title="Pini the Pricer", page_icon="🧮", layout="centered")
# ---- Simple password gate ----
def require_password():
    import streamlit as st
    app_pw = st.secrets.get("APP_PASSWORD")
    if not app_pw:
        st.stop()  # no password set - refuse to load

    if not st.session_state.get("auth_ok", False):
        st.title("Pini the Pricer")
        pwd = st.text_input("Enter password", type="password")
        if st.button("Enter"):
            if pwd == app_pw:
                st.session_state["auth_ok"] = True
                st.experimental_rerun()
            else:
                st.error("Wrong password")
        st.stop()

require_password()
# ---- end password gate ----

st.markdown('''
<div style="display:flex;align-items:center;gap:12px;">
  <h2 style="margin:0;">Pini the Pricer</h2>
</div>
''', unsafe_allow_html=True)

with st.form("inputs", clear_on_submit=False):
    col1, col2 = st.columns(2)
    with col1:
        kpis = st.number_input("KPIs", min_value=0, value=1, step=1)
        channels = st.number_input("Channels", min_value=0, value=1, step=1)
    with col2:
        countries = st.number_input("Countries", min_value=0, value=1, step=1)
        users = st.number_input("Users (Admins)", min_value=0, value=1, step=1)
    license_choice = st.selectbox("Force license (optional)", options=["(auto)","SMB","Pro","Enterprise","Ultimate"])
    submitted = st.form_submit_button("Get quote")

if submitted:
    payload = {"kpis": int(kpis), "channels": int(channels), "countries": int(countries), "users": int(users)}
    if license_choice != "(auto)":
        payload["license"] = license_choice
        resp = requests.post(f"{API_URL}/quote", json=payload, timeout=30).json()
        st.subheader(f"License: {resp['license']} — Version {resp['version']}")
        st.metric("Total Monthly (USD)", f"${resp['total_monthly']:,}")
        st.write(f"License discount: {resp['license_discount_pct']*100:.0f}% → -${resp['license_discount_amount']:,}")
        st.metric("Annual (USD)", f"${resp['total_annual']:,}")
        st.divider()
        for it in resp["items"]:
            with st.expander(f"{it['key'].title()} — requested {it['requested']} (included {it['included']}) — line ${it['line_total']:,}"):
                st.json(it["progressive_breakdown"])
        st.caption("No taxes. Currency USD.")
    else:
        resp = requests.post(f"{API_URL}/quote", json=payload, timeout=30).json()
        st.subheader(f"Recommended: {resp['recommended']}")
        best = resp["quotes"][resp["recommended"]]
        st.metric("Total Monthly (USD)", f"${best['total_monthly']:,}")
        st.metric("Annual (USD)", f"${best['total_annual']:,}")
        st.divider()
        for name, q in resp["quotes"].items():
            st.write(f"### {name} — ${q['total_monthly']:,}/mo")
            for it in q["items"]:
                st.write(f"- {it['key'].title()}: {it['requested']} (incl {it['included']}) → ${it['line_total']:,}")
        st.caption("No taxes. Currency USD.")
