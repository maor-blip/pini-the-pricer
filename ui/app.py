import os, re, json, requests
import streamlit as st
from openai import OpenAI

# Config
API_URL = st.secrets.get("PRICER_API_URL") or os.getenv("PRICER_API_URL") or "http://localhost:8000"
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(page_title="Pini the Pricer", page_icon="🧮", layout="wide")

# ---------- Password gate ----------
def require_password():
    app_pw = st.secrets.get("APP_PASSWORD")
    if not app_pw:
        st.stop()
    if not st.session_state.get("auth_ok", False):
        st.title("Pini the Pricer")
        pwd = st.text_input("Enter password", type="password")
        if st.button("Enter"):
            if pwd == app_pw:
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Wrong password")
        st.stop()
require_password()
# ---------- end password gate ----------

# Helpers
def post_json(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            st.error("API returned non-JSON response")
            st.code(r.text)
            st.stop()
    except requests.exceptions.RequestException as e:
        st.error(f"Request failed: {e}")
        st.stop()

def chat_with_playbook(messages):
    if not client:
        st.error("Missing OPENAI_API_KEY in secrets")
        st.stop()
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        messages=messages,
    )
    return resp.choices[0].message.content

# UI
st.caption(f"API: {API_URL}")

tab1, tab2 = st.tabs(["Quote", "Sales assistant"])

# ---------- Tab 1: Quote ----------
with tab1:
    st.subheader("Get a price quote")
    with st.form("inputs", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            kpis = st.number_input("KPIs", min_value=0, value=1, step=1)
            channels = st.number_input("Channels", min_value=0, value=1, step=1)
        with col2:
            countries = st.number_input("Countries", min_value=0, value=1, step=1)
            users = st.number_input("Users (Admins)", min_value=0, value=1, step=1)
        license_choice = st.selectbox("Force license (optional)", options=["(auto)", "SMB", "Pro", "Enterprise", "Ultimate"])
        submitted = st.form_submit_button("Get quote")

    if submitted:
        payload = {
            "kpis": int(kpis),
            "channels": int(channels),
            "countries": int(countries),
            "users": int(users)
        }
        if license_choice != "(auto)":
            payload["license"] = license_choice
            resp = post_json(f"{API_URL}/quote", payload)

            st.subheader(f"License: {resp['license']} - Version {resp['version']}")
            st.metric("Total Monthly (USD)", f"${resp['total_monthly']:,}")
            st.write(f"License discount: {resp.get('license_discount_pct', 0)*100:.0f}% -> -${resp.get('license_discount_amount', 0):,}")
            st.metric("Annual (USD)", f"${resp['total_annual']:,}")
            st.divider()
            for it in resp["items"]:
                with st.expander(f"{it['key'].title()} - requested {it['requested']} (included {it['included']}) - line ${it['line_total']:,}"):
                    st.json(it["progressive_breakdown"])
            st.caption("No taxes. Currency USD.")

            # Save for assistant tab
            st.session_state["last_inputs"] = payload
            st.session_state["last_quote"] = resp

        else:
            resp = post_json(f"{API_URL}/quote", payload)

            st.subheader(f"Recommended: {resp['recommended']}")
            best = resp["quotes"][resp['recommended']]
            st.metric("Total Monthly (USD)", f"${best['total_monthly']:,}")
            st.write(f"License discount: {best.get('license_discount_pct', 0)*100:.0f}% -> -${best.get('license_discount_amount', 0):,}")
            st.metric("Annual (USD)", f"${best['total_annual']:,}")
            st.divider()
            for name, q in resp["quotes"].items():
                st.write(f"### {name} - ${q['total_monthly']:,}/mo")
                for it in q["items"]:
                    st.write(f"- {it['key'].title()}: {it['requested']} (incl {it['included']}) -> ${it['line_total']:,}")
            st.caption("No taxes. Currency USD.")

            st.session_state["last_inputs"] = payload
            st.session_state["last_quote"] = best

# ---------- Tab 2: Sales assistant ----------
with tab2:
    st.subheader("INCRMNTAL Sales Playbook")
    if "chat" not in st.session_state:
        st.session_state["chat"] = [
            {"role": "system", "content": (
                "You are the INCRMNTAL Sales Playbook. Be concise, helpful, confident. "
                "Tone - practical, high signal, no fluff. Use short bullets when helpful. "
                "Skills - pricing explanation, handling objections, ROI framing, competitor comparisons, next-step planning. "
                "If the user asks for a quote, either request the needed numbers or tell them to press the Insert latest quote button."
            )}
        ]

    # Show history
    for m in st.session_state["chat"]:
        if m["role"] == "system":
            continue
        st.chat_message(m["role"]).write(m["content"])

    # Utilities row
    colA, colB = st.columns(2)
    with colA:
        if st.button("Insert latest quote into chat"):
            q = st.session_state.get("last_quote")
            inp = st.session_state.get("last_inputs")
            if not q or not inp:
                st.warning("No quote yet. Go to the Quote tab, generate a quote, then try again.")
            else:
                quote_text = [
                    "Latest quote summary:",
                    f"- Inputs: KPIs {inp.get('kpis')}, Channels {inp.get('channels')}, Countries {inp.get('countries')}, Users {inp.get('users')}",
                    f"- License: {q.get('license','recommended')}",
                    f"- Total monthly: ${q.get('total_monthly'):,}",
                    f"- Total annual: ${q.get('total_annual'):,}",
                ]
                st.session_state["chat"].append({"role":"user","content":"\n".join(quote_text)})
                st.rerun()
    with colB:
        if st.button("Create proposal draft"):
            q = st.session_state.get("last_quote")
            inp = st.session_state.get("last_inputs")
            if not client:
                st.error("Missing OPENAI_API_KEY")
            elif not q or not inp:
                st.warning("No quote yet. Generate a quote first.")
            else:
                prompt = (
                    "Write a concise proposal for INCRMNTAL. "
                    "Audience - senior marketing decision maker. "
                    "Sections: Summary, Package and pricing, What you get, Why INCRMNTAL, Next steps. "
                    "Use short paragraphs and bullets. No flowery language. "
                    f"Pricing context: {json.dumps(q)} "
                    "State prices in USD monthly and annual as provided. Do not invent features we did not quote."
                )
                content = chat_with_playbook([
                    {"role":"system","content":"You write clean, concise sales proposals for INCRMNTAL. Straight talk, short bullets, crisp value."},
                    {"role":"user","content": prompt}
                ])
                st.session_state["proposal_md"] = content
                st.success("Proposal draft ready below.")

    # Chat input
    user_msg = st.chat_input("Ask anything - pricing, objections, next steps")
    if user_msg:
        st.session_state["chat"].append({"role":"user","content": user_msg})
        reply = chat_with_playbook(st.session_state["chat"])
        st.session_state["chat"].append({"role":"assistant","content": reply})
        st.rerun()

    # Proposal download if available
    if st.session_state.get("proposal_md"):
        st.markdown("### Proposal draft")
        st.markdown(st.session_state["proposal_md"])
        st.download_button("Download proposal.md", st.session_state["proposal_md"].encode("utf-8"), "proposal.md", "text/markdown")

# Sidebar logout
if st.sidebar.button("Log out"):
    st.session_state["auth_ok"] = False
    st.rerun()
