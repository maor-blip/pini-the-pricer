import os, json, time, urllib.parse
import requests
import streamlit as st
from openai import OpenAI, RateLimitError, APIError
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

# Cookie lib - streamlit-cookies-manager==0.2.0
try:
    from streamlit_cookies_manager import EncryptedCookieManager
except Exception:
    from cookies_manager import EncryptedCookieManager  # fallback

# ---------- Config ----------
API_URL = st.secrets.get("PRICER_API_URL") or os.getenv("PRICER_API_URL") or "http://localhost:8000"
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
GOOGLE_CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET")
ALLOWED_DOMAIN = (st.secrets.get("ALLOWED_DOMAIN") or "incrmntal.com").strip().lower()
APP_URL = (st.secrets.get("APP_URL") or "").rstrip("/")
COOKIE_SECRET = st.secrets.get("COOKIE_SECRET") or os.getenv("COOKIE_SECRET") or "dev-secret-change-me"

st.set_page_config(page_title="Pini the Pricer", page_icon="🧮", layout="wide")

if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not APP_URL:
    st.error("Auth not configured. Set APP_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET in Secrets.")
    st.stop()

OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ---------- Cookies: persistent login ----------
# API in 0.2.0:
# - cookies.ready() must be True before use
# - get: cookies.get(name)
# - set: cookies[name] = value; cookies.save()
# - delete: del cookies[name]; cookies.save()
cookies = EncryptedCookieManager(prefix="pti_", password=COOKIE_SECRET)
if not cookies.ready():
    st.write("Setting up secure session...")
    st.markdown('<meta http-equiv="refresh" content="0.5">', unsafe_allow_html=True)
    st.stop()

COOKIE_NAME = "auth"
COOKIE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

def set_login_cookie(email: str, name: str = "", picture: str = ""):
    payload = json.dumps({"email": email, "name": name, "picture": picture, "ts": int(time.time())})
    cookies[COOKIE_NAME] = payload
    cookies.save()

def get_login_cookie():
    raw = cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if int(time.time()) - int(data.get("ts", 0)) > COOKIE_TTL_SECONDS:
            return None
        return data
    except Exception:
        return None

def clear_login_cookie():
    try:
        del cookies[COOKIE_NAME]
    except Exception:
        cookies[COOKIE_NAME] = ""
    cookies.save()

# ---------- Hard logout handler ----------
def handle_forced_logout():
    params = {k: (v[0] if isinstance(v, list) else v) for k, v in dict(st.query_params).items()}
    if params.get("logout") == "1":
        st.session_state.pop("user", None)
        clear_login_cookie()
        try:
            st.cache_data.clear()
            st.cache_resource.clear()
        except Exception:
            pass
        st.query_params.clear()
        st.success("Logged out. Please sign in again.")
        st.stop()
handle_forced_logout()

# ---------- Google login with silent SSO + cookie resume ----------
def require_google_login():
    # Resume from cookie first
    if not st.session_state.get("user"):
        cached = get_login_cookie()
        if cached and isinstance(cached, dict):
            email = (cached.get("email") or "").strip().lower()
            if email.endswith(f"@{ALLOWED_DOMAIN}"):
                st.session_state["user"] = {
                    "email": email,
                    "name": cached.get("name", ""),
                    "picture": cached.get("picture", ""),
                }
                return

    if st.session_state.get("user"):
        return

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [APP_URL],
            "javascript_origins": [APP_URL],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=OAUTH_SCOPES, redirect_uri=APP_URL)

    # Normalize query params ONCE so we don't miss errors and spin
    params = {k: (v[0] if isinstance(v, list) else v) for k, v in dict(st.query_params).items()}

    # If Google redirected back with an auth code -> finish login
    if "code" in params:
        qs = urllib.parse.urlencode(params, doseq=False)
        authorization_response = f"{APP_URL}?{qs}" if qs else APP_URL
        try:
            flow.fetch_token(authorization_response=authorization_response)
        except OAuth2Error as e:
            st.error(f"Google OAuth failed: {getattr(e,'error','oauth_error')} - {getattr(e,'description','')}")
            st.stop()
        except Exception as e:
            st.error(f"Token exchange failed: {e}")
            st.stop()

        creds = flow.credentials
        info = id_token.verify_oauth2_token(creds.id_token, google_requests.Request(), GOOGLE_CLIENT_ID)
        email = (info.get("email") or "").strip().lower()
        hd = (info.get("hd") or "").strip().lower()

        if (hd and hd != ALLOWED_DOMAIN) or not email.endswith(f"@{ALLOWED_DOMAIN}"):
            st.error(f"Access denied - use your {ALLOWED_DOMAIN} account.")
            st.stop()

        st.session_state["user"] = {"email": email, "name": info.get("name",""), "picture": info.get("picture","")}
        set_login_cookie(email, info.get("name",""), info.get("picture",""))
        st.query_params.clear()
        st.rerun()

    # If Google responded with any error at all -> show button, do NOT silent redirect again
    err = params.get("error", "")
    if err:
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="select_account",
            hd=ALLOWED_DOMAIN,
        )
        st.title("Pini the Pricer")
        st.write(f"Sign in with your {ALLOWED_DOMAIN} Google account.")
        st.link_button("Continue with Google", auth_url)
        st.stop()

    # First visit or returning user with active Google session -> try silent redirect ONCE
    # We only attempt it when there is no code and no error in the URL.
    auth_url_silent, _ = flow.authorization_url(
        access_type="online",
        include_granted_scopes="true",
        prompt="none",
        hd=ALLOWED_DOMAIN,
    )
    # meta refresh instead of st.experimental_rerun to avoid rerun storms
    st.markdown(f'<meta http-equiv="refresh" content="0; url={auth_url_silent}">', unsafe_allow_html=True)
    st.write("Redirecting to Google...")
    st.stop()

# Gate before any UI
require_google_login()
# ---------- end Google login ----------

# ---------- Helpers ----------
def money(x, decimals: int = 0) -> str:
    try:
        return f"${float(x):,.{decimals}f}"
    except Exception:
        return str(x)

def post_json(url, payload, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=60)
            r.raise_for_status()
            try:
                return r.json()
            except Exception:
                st.error("API returned non-JSON response"); st.code(r.text); st.stop()
        except requests.exceptions.RequestException as e:
            if attempt < retries:
                time.sleep(2); continue
            st.error(f"Request failed: {e}"); st.stop()

def chat_with_playbook(messages):
    if not client:
        st.error("Missing OPENAI_API_KEY in secrets"); st.stop()
    max_retries, backoff = 4, 2
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini", temperature=0.3, messages=messages,
            )
            return resp.choices[0].message.content
        except (RateLimitError, APIError) as e:
            if attempt < max_retries - 1:
                time.sleep(backoff); backoff *= 2; continue
            st.error(f"OpenAI error: {e}"); st.stop()
        except Exception as e:
            st.error(f"Unexpected error: {e}"); st.stop()

# ---------- Header ----------
IMAGE_URL = "https://incrmntal-website.s3.amazonaws.com/Pinilogo_efa5df4e90.png?updated_at=2025-09-09T08:07:49.998Z"
user = st.session_state.get("user", {})
st.markdown(f"""
<div style="display:flex; align-items:center; justify-content:space-between; padding:4px 0 8px 0;">
  <div style="display:flex; align-items:center; gap:12px;">
    <h2 style="margin:0;">Pini the Pricer</h2>
    <div style="font-size:0.9rem; opacity:0.8;">{user.get('email','')}</div>
  </div>
  <img src="{IMAGE_URL}" alt="INCRMNTAL" style="height:40px; max-height:40px; object-fit:contain;" />
</div>
""", unsafe_allow_html=True)
st.caption(f"API: {API_URL}")

# ---------- Tabs ----------
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
        payload = {"kpis": int(kpis), "channels": int(channels), "countries": int(countries), "users": int(users)}

        if license_choice != "(auto)":
            payload["license"] = license_choice
            resp = post_json(f"{API_URL}/quote", payload)
            st.subheader(f"License: {resp['license']} - Version {resp['version']}")
            st.metric("Total Monthly (USD)", money(resp['total_monthly']))
            st.write(f"License discount: {int(round(resp.get('license_discount_pct', 0)*100))}% -> -{money(resp.get('license_discount_amount', 0))}")
            st.metric("Annual (USD)", money(resp['total_annual']))
            st.divider()
            for it in resp["items"]:
                with st.expander(f"{it['key'].title()} - requested {it['requested']} (included {it['included']}) - line {money(it['line_total'])}"):
                    st.json(it["progressive_breakdown"])
            st.caption("No taxes. Currency USD.")
            st.session_state["last_inputs"] = payload
            st.session_state["last_quote"] = resp
        else:
            resp = post_json(f"{API_URL}/quote", payload)
            st.subheader(f"Recommended: {resp['recommended']}")
            best = resp["quotes"][resp['recommended']]
            st.metric("Total Monthly (USD)", money(best['total_monthly']))
            st.write(f"License discount: {int(round(best.get('license_discount_pct', 0)*100))}% -> -{money(best.get('license_discount_amount', 0))}")
            st.metric("Annual (USD)", money(best['total_annual']))
            st.divider()
            for name, q in resp["quotes"].items():
                st.write(f"### {name} - {money(q['total_monthly'])}/mo")
                for it in q["items"]:
                    st.write(f"- {it['key'].title()}: {it['requested']} (incl {it['included']}) -> {money(it['line_total'])}")
            st.caption("No taxes. Currency USD.")
            st.session_state["last_inputs"] = payload
            st.session_state["last_quote"] = best

# ---------- Tab 2: Sales assistant ----------
with tab2:
    st.subheader("INCRMNTAL Sales Playbook")
    if "chat" not in st.session_state:
        st.session_state["chat"] = [{
            "role": "system",
            "content": ("You are the INCRMNTAL Sales Playbook. Be concise and practical. "
                        "Tone - direct, helpful, confident. "
                        "Skills - pricing explanation, handling objections, ROI framing, competitor comparisons, next-step planning. "
                        "When asked for a quote, either request the missing numbers or ask the user to insert the latest quote.")
        }]

    for m in st.session_state["chat"]:
        if m["role"] != "system":
            st.chat_message(m["role"]).write(m["content"])

    colA, colB = st.columns(2)
    with colA:
        if st.button("Insert latest quote into chat"):
            q = st.session_state.get("last_quote"); inp = st.session_state.get("last_inputs")
            if not q or not inp:
                st.warning("No quote yet. Go to the Quote tab, generate a quote, then try again.")
            else:
                lines = [
                    "Latest quote summary:",
                    f"- Inputs: KPIs {inp.get('kpis')}, Channels {inp.get('channels')}, Countries {inp.get('countries')}, Users {inp.get('users')}",
                    f"- License: {q.get('license','recommended')}",
                    f"- Total monthly: {money(q.get('total_monthly'))}",
                    f"- Total annual: {money(q.get('total_annual'))}",
                ]
                st.session_state["chat"].append({"role": "user", "content": "\n".join(lines)})
                st.rerun()
    with colB:
        if st.button("Create proposal draft"):
            q = st.session_state.get("last_quote"); inp = st.session_state.get("last_inputs")
            if not client:
                st.error("Missing OPENAI_API_KEY in secrets")
            elif not q or not inp:
                st.warning("No quote yet. Generate a quote first.")
            else:
                pricing_blurb = (
                    f"License: {q.get('license','recommended')}\n"
                    f"Total monthly: {money(q.get('total_monthly'))}\n"
                    f"Total annual: {money(q.get('total_annual'))}\n"
                )
                prompt = (
                    "Write a concise proposal for INCRMNTAL.\n"
                    "Audience - senior marketing decision maker.\n"
                    "Sections: Summary, Package and pricing, What you get, Why INCRMNTAL, Next steps.\n"
                    "Use short paragraphs and bullets. No fluff.\n"
                    f"Pricing context:\n{pricing_blurb}\n"
                    "State prices in USD monthly and annual exactly as provided above."
                )
                content = chat_with_playbook([
                    {"role": "system", "content": "You write clean, concise sales proposals for INCRMNTAL. Short bullets and straight talk."},
                    {"role": "user", "content": prompt}
                ])
                st.session_state["proposal_md"] = content
                st.success("Proposal draft ready below.")

    user_msg = st.chat_input("Ask anything - pricing, objections, next steps")
    if user_msg:
        st.session_state["chat"].append({"role": "user", "content": user_msg})
        reply = chat_with_playbook(st.session_state["chat"])
        st.session_state["chat"].append({"role": "assistant", "content": reply})
        st.rerun()

    if st.session_state.get("proposal_md"):
        st.markdown("### Proposal draft")
        st.markdown(st.session_state["proposal_md"])
        st.download_button("Download proposal.md", st.session_state["proposal_md"].encode("utf-8"), "proposal.md", "text/markdown")

# ---------- Sidebar ----------
with st.sidebar:
    st.write(f"Signed in as: {user.get('email','') or 'unknown'}")
    if st.button("Log out"):
        st.session_state.pop("user", None)
        clear_login_cookie()
        st.query_params["logout"] = "1"
        st.rerun()
