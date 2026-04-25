
import base64
import json
import os
import secrets
from pathlib import Path
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# ============================================================
# Cash Command System - Streamlit + QuickBooks Online MVP
# ============================================================
# Modes:
# 1) Demo mode: uses built-in sample AR/AP/cash assumptions.
# 2) QBO mode: OAuth connects to QuickBooks Online and pulls live data.
#
# Important:
# - Never put QBO CLIENT_SECRET in frontend HTML.
# - Store Streamlit secrets in .streamlit/secrets.toml locally
#   and Streamlit Community Cloud secrets in app settings.
# ============================================================


st.set_page_config(
    page_title="Cash Command System",
    page_icon="💧",
    layout="wide",
)


# -----------------------------
# Styling
# -----------------------------
st.markdown(
    """
    <style>
      .main .block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 1200px; }
      .metric-card {
        border: 1px solid #dbe7f0;
        border-radius: 22px;
        padding: 18px 20px;
        background: linear-gradient(135deg, #ffffff 0%, #f6fbff 100%);
        box-shadow: 0 10px 30px rgba(52, 95, 125, 0.08);
      }
      .risk-card {
        border: 1px solid #fed7aa;
        border-radius: 18px;
        padding: 16px 18px;
        background: #fff7ed;
        color: #7c2d12;
        margin-bottom: 10px;
      }
      .action-card {
        border: 1px solid #c7ddeb;
        border-radius: 18px;
        padding: 16px 18px;
        background: #f4f9fd;
        color: #244b66;
        margin-bottom: 10px;
      }
      .small-muted { color:#64748b; font-size: 0.92rem; }
      .hero {
        padding: 24px 28px;
        border: 1px solid #dbe7f0;
        border-radius: 28px;
        background: linear-gradient(135deg, #eaf3fb 0%, #ffffff 100%);
        margin-bottom: 24px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)



# -----------------------------
# Token persistence helpers
# -----------------------------
# This is for sandbox / personal demo use only.
# For production SaaS, replace this with encrypted database storage.
TOKEN_FILE = Path(".qbo_tokens.local.json")


def save_tokens(tokens: dict, realm_id: str):
    """Persist the newest token set. Intuit can rotate refresh_token, so always save latest."""
    try:
        payload = {
            "tokens": tokens,
            "realm_id": realm_id,
            "saved_at": datetime.utcnow().isoformat(),
        }
        TOKEN_FILE.write_text(json.dumps(payload, indent=2))
    except Exception as exc:
        st.warning(f"Could not persist QBO tokens locally: {exc}")


def load_tokens():
    """Load demo tokens from local file if present."""
    try:
        if TOKEN_FILE.exists():
            payload = json.loads(TOKEN_FILE.read_text())
            return payload.get("tokens"), payload.get("realm_id")
    except Exception:
        return None, None
    return None, None


def clear_saved_tokens():
    """Clear locally saved demo tokens."""
    try:
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
    except Exception:
        pass


# -----------------------------
# Config helpers
# -----------------------------
def get_secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return os.getenv(name, default)


CLIENT_ID = get_secret("QBO_CLIENT_ID")
CLIENT_SECRET = get_secret("QBO_CLIENT_SECRET")
REDIRECT_URI = get_secret("QBO_REDIRECT_URI")
ENVIRONMENT = get_secret("QBO_ENVIRONMENT", "sandbox").lower()
COMPANY_ID_OVERRIDE = get_secret("QBO_REALM_ID", "")

AUTH_BASE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
API_BASE = "https://sandbox-quickbooks.api.intuit.com" if ENVIRONMENT == "sandbox" else "https://quickbooks.api.intuit.com"

SCOPES = "com.intuit.quickbooks.accounting"


def qbo_ready() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET and REDIRECT_URI)


# -----------------------------
# OAuth helpers
# -----------------------------
def build_auth_url() -> str:
    state = secrets.token_urlsafe(24)
    st.session_state["oauth_state"] = state
    params = {
        "client_id": CLIENT_ID,
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "access_type": "offline",
        "state": state,
    }
    return f"{AUTH_BASE_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict:
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_header}",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text}")
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_header}",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    if not resp.ok:
        if "invalid_grant" in resp.text:
            clear_saved_tokens()
        raise RuntimeError(f"Refresh failed: {resp.status_code} {resp.text}")
    return resp.json()


def handle_oauth_callback():
    if st.query_params.get("error"):
       st.error(f"QBO error: {st.query_params.get('error')} — {st.query_params.get('error_description')}")if st.query_params.get("error"):
       st.error(f"QBO error: {st.query_params.get('error')} — {st.query_params.get('error_description')}")
    params = st.query_params
    code = params.get("code")
    realm_id = params.get("realmId") or COMPANY_ID_OVERRIDE
    returned_state = params.get("state")

    if code and realm_id and "qbo_tokens" not in st.session_state:
        expected_state = st.session_state.get("oauth_state")
        if expected_state and returned_state and expected_state != returned_state:
            st.error("OAuth state mismatch. Please reconnect QuickBooks.")
            return

        with st.spinner("Connecting to QuickBooks Online..."):
            tokens = exchange_code_for_tokens(code)
            st.session_state["qbo_tokens"] = tokens
            st.session_state["realm_id"] = realm_id
            save_tokens(tokens, realm_id)
            st.success("QuickBooks connected.")
            try:
                st.query_params.clear()
            except Exception:
                pass


# -----------------------------
# QBO API helpers
# -----------------------------
def qbo_headers() -> dict:
    tokens = st.session_state.get("qbo_tokens", {})
    access_token = tokens.get("access_token")
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/text",
    }


def qbo_query(sql: str) -> dict:
    realm_id = st.session_state.get("realm_id") or COMPANY_ID_OVERRIDE
    if not realm_id:
        raise RuntimeError("Missing QBO realm/company ID.")

    url = f"{API_BASE}/v3/company/{realm_id}/query"
    params = {"query": sql, "minorversion": "75"}
    resp = requests.get(url, headers=qbo_headers(), params=params, timeout=30)

    # Refresh once if access token expired.
    if resp.status_code == 401 and st.session_state.get("qbo_tokens", {}).get("refresh_token"):
        new_tokens = refresh_access_token(st.session_state["qbo_tokens"]["refresh_token"])
        st.session_state["qbo_tokens"].update(new_tokens)
        save_tokens(st.session_state["qbo_tokens"], realm_id)
        resp = requests.get(url, headers=qbo_headers(), params=params, timeout=30)

    if not resp.ok:
        raise RuntimeError(f"QBO query failed: {resp.status_code} {resp.text}")

    return resp.json()


def fetch_qbo_data():
    # Open invoices
    invoice_sql = (
        "select Id, DocNumber, TxnDate, DueDate, Balance, TotalAmt, CustomerRef "
        "from Invoice where Balance > '0' maxresults 1000"
    )
    # Open bills
    bill_sql = (
        "select Id, DocNumber, TxnDate, DueDate, Balance, TotalAmt, VendorRef "
        "from Bill where Balance > '0' maxresults 1000"
    )
    # Cash/bank accounts
    account_sql = (
        "select Id, Name, AccountType, CurrentBalance from Account "
        "where AccountType = 'Bank' maxresults 1000"
    )

    invoices_raw = qbo_query(invoice_sql).get("QueryResponse", {}).get("Invoice", [])
    bills_raw = qbo_query(bill_sql).get("QueryResponse", {}).get("Bill", [])
    accounts_raw = qbo_query(account_sql).get("QueryResponse", {}).get("Account", [])

    invoices = []
    for inv in invoices_raw:
        customer = inv.get("CustomerRef", {}).get("name", "Unknown customer")
        invoices.append({
            "type": "AR",
            "name": customer,
            "doc": inv.get("DocNumber", inv.get("Id", "")),
            "txn_date": inv.get("TxnDate"),
            "due_date": inv.get("DueDate") or inv.get("TxnDate"),
            "amount": float(inv.get("Balance", 0) or 0),
        })

    bills = []
    for bill in bills_raw:
        vendor = bill.get("VendorRef", {}).get("name", "Unknown vendor")
        bills.append({
            "type": "AP",
            "name": vendor,
            "doc": bill.get("DocNumber", bill.get("Id", "")),
            "txn_date": bill.get("TxnDate"),
            "due_date": bill.get("DueDate") or bill.get("TxnDate"),
            "amount": float(bill.get("Balance", 0) or 0),
        })

    cash_balance = sum(float(acct.get("CurrentBalance", 0) or 0) for acct in accounts_raw)

    return pd.DataFrame(invoices), pd.DataFrame(bills), cash_balance


# -----------------------------
# Demo data
# -----------------------------
def demo_data():
    today = date.today()
    invoices = pd.DataFrame([
        {"type": "AR", "name": "Customer A", "doc": "INV-1001", "txn_date": str(today - timedelta(days=35)), "due_date": str(today - timedelta(days=5)), "amount": 120000},
        {"type": "AR", "name": "Customer B", "doc": "INV-1002", "txn_date": str(today - timedelta(days=10)), "due_date": str(today + timedelta(days=20)), "amount": 85000},
        {"type": "AR", "name": "Customer C", "doc": "INV-1003", "txn_date": str(today - timedelta(days=5)), "due_date": str(today + timedelta(days=25)), "amount": 56000},
        {"type": "AR", "name": "Customer D", "doc": "INV-1004", "txn_date": str(today - timedelta(days=60)), "due_date": str(today - timedelta(days=30)), "amount": 42000},
    ])
    bills = pd.DataFrame([
        {"type": "AP", "name": "Vendor Alpha", "doc": "BILL-2001", "txn_date": str(today - timedelta(days=20)), "due_date": str(today + timedelta(days=5)), "amount": 45000},
        {"type": "AP", "name": "Vendor Beta", "doc": "BILL-2002", "txn_date": str(today - timedelta(days=12)), "due_date": str(today + timedelta(days=13)), "amount": 38000},
        {"type": "AP", "name": "Vendor Gamma", "doc": "BILL-2003", "txn_date": str(today - timedelta(days=5)), "due_date": str(today + timedelta(days=28)), "amount": 62000},
        {"type": "AP", "name": "Cloud + Software", "doc": "BILL-2004", "txn_date": str(today - timedelta(days=2)), "due_date": str(today + timedelta(days=18)), "amount": 21000},
    ])
    cash_balance = 210000.0
    return invoices, bills, cash_balance


# -----------------------------
# Forecast logic
# -----------------------------
def parse_date(s):
    if pd.isna(s) or not s:
        return date.today()
    return pd.to_datetime(s).date()


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def expected_ar_date(due_date: date, delay_days: int, collection_push_days: int) -> date:
    return due_date + timedelta(days=delay_days - collection_push_days)


def expected_ap_date(due_date: date, vendor_delay_days: int) -> date:
    return due_date + timedelta(days=vendor_delay_days)


def build_forecast(
    invoices: pd.DataFrame,
    bills: pd.DataFrame,
    starting_cash: float,
    ar_delay_days: int,
    collection_push_days: int,
    vendor_delay_days: int,
    revenue_slip_pct: int,
    payroll_amount: float,
    rent_amount: float,
):
    today = date.today()
    start_week = week_start(today)
    weeks = [start_week + timedelta(weeks=i) for i in range(13)]

    rows = []
    cash = starting_cash

    invoices = invoices.copy()
    bills = bills.copy()

    if not invoices.empty:
        invoices["due_date_parsed"] = invoices["due_date"].apply(parse_date)
        invoices["expected_date"] = invoices["due_date_parsed"].apply(
            lambda d: expected_ar_date(d, ar_delay_days, collection_push_days)
        )
        invoices["expected_week"] = invoices["expected_date"].apply(week_start)
        invoices["scenario_amount"] = invoices["amount"] * (1 - revenue_slip_pct / 100)

    if not bills.empty:
        bills["due_date_parsed"] = bills["due_date"].apply(parse_date)
        bills["expected_date"] = bills["due_date_parsed"].apply(lambda d: expected_ap_date(d, vendor_delay_days))
        bills["expected_week"] = bills["expected_date"].apply(week_start)
        bills["scenario_amount"] = bills["amount"]

    for i, wk in enumerate(weeks):
        ar_inflow = 0.0
        ap_outflow = 0.0

        if not invoices.empty:
            ar_inflow = invoices.loc[invoices["expected_week"] == wk, "scenario_amount"].sum()

        if not bills.empty:
            ap_outflow = bills.loc[bills["expected_week"] == wk, "scenario_amount"].sum()

        # Fixed costs
        payroll = payroll_amount if i in [1, 3, 5, 7, 9, 11] else 0.0
        rent = rent_amount if i in [0, 4, 8, 12] else 0.0

        starting = cash
        ending = starting + ar_inflow - ap_outflow - payroll - rent

        rows.append({
            "week": wk,
            "starting_cash": starting,
            "ar_inflow": ar_inflow,
            "ap_outflow": ap_outflow,
            "payroll": payroll,
            "rent": rent,
            "ending_cash": ending,
            "net_cash_flow": ending - starting,
        })
        cash = ending

    return pd.DataFrame(rows), invoices, bills


def runway_weeks(forecast: pd.DataFrame) -> float:
    negative = forecast[forecast["ending_cash"] < 0]
    if negative.empty:
        return 13.0
    first_negative_idx = int(negative.index[0])
    return float(first_negative_idx)


def generate_risks(forecast: pd.DataFrame, invoices: pd.DataFrame, bills: pd.DataFrame):
    risks = []
    if (forecast["ending_cash"] < 0).any():
        wk = forecast.loc[forecast["ending_cash"] < 0, "week"].iloc[0]
        risks.append(f"Cash turns negative in week of {wk.strftime('%b %d')}.")

    min_row = forecast.loc[forecast["ending_cash"].idxmin()]
    risks.append(f"Lowest projected cash balance is ${min_row['ending_cash']:,.0f} in week of {min_row['week'].strftime('%b %d')}.")

    if not invoices.empty:
        top_ar = invoices.sort_values("amount", ascending=False).iloc[0]
        risks.append(f"Largest open AR exposure: {top_ar['name']} at ${top_ar['amount']:,.0f}.")

        overdue = invoices[invoices["due_date_parsed"] < date.today()] if "due_date_parsed" in invoices else pd.DataFrame()
        if not overdue.empty:
            risks.append(f"Overdue AR totals ${overdue['amount'].sum():,.0f}; collection timing is a key forecast risk.")

    if not bills.empty:
        next_14 = date.today() + timedelta(days=14)
        due_soon = bills[bills["due_date_parsed"] <= next_14] if "due_date_parsed" in bills else pd.DataFrame()
        if not due_soon.empty:
            risks.append(f"AP due in next 14 days totals ${due_soon['amount'].sum():,.0f}.")

    return risks[:5]


def generate_actions(forecast: pd.DataFrame, invoices: pd.DataFrame, bills: pd.DataFrame):
    actions = []

    if not invoices.empty:
        top_ar = invoices.sort_values("amount", ascending=False).iloc[0]
        actions.append(f"Push {top_ar['name']} for payment this week: potential cash upside ${top_ar['amount']:,.0f}.")

    if not bills.empty:
        top_ap = bills.sort_values("amount", ascending=False).iloc[0]
        actions.append(f"Negotiate timing with {top_ap['name']}: delaying by 2 weeks could preserve ${top_ap['amount']:,.0f} near-term cash.")

    min_cash = forecast["ending_cash"].min()
    if min_cash < 100000:
        actions.append("Pause discretionary spend until projected minimum cash is above $100K.")
    else:
        actions.append("Maintain current plan, but monitor AR timing weekly.")

    actions.append("Update forecast vs actual next week and explain variance by customer/vendor timing.")
    return actions[:4]


# -----------------------------
# UI
# -----------------------------
handle_oauth_callback()

st.markdown(
    """
    <div class="hero">
      <div style="font-size:0.82rem; letter-spacing:0.12em; text-transform:uppercase; color:#3f6f93; font-weight:800;">
        Cash Command System Demo
      </div>
      <h1 style="margin:0.35rem 0 0.5rem; color:#213849;">13-week cash forecast + weekly decision engine</h1>
      <p class="small-muted" style="max-width:850px;">
        Connect QuickBooks Online sandbox/company data, project cash for 13 weeks, test scenarios,
        and generate Monday-style cash decisions: runway, risks, and recommended actions.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Connection")

    mode = st.radio(
        "Data mode",
        ["Demo data", "QuickBooks Online"],
        index=0 if "qbo_tokens" not in st.session_state else 1,
    )

    if mode == "QuickBooks Online":
        if not qbo_ready():
            st.error("Missing QBO secrets. Add QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_REDIRECT_URI, and QBO_ENVIRONMENT.")
        elif "qbo_tokens" not in st.session_state:
            auth_url = build_auth_url()
            st.link_button("Connect QuickBooks", auth_url, use_container_width=True)
            st.caption("Use your QBO sandbox app first. The redirect URI must match your Streamlit app URL.")
        else:
            st.success("QBO connected")
            if st.button("Disconnect", use_container_width=True):
                for key in ["qbo_tokens", "realm_id"]:
                    st.session_state.pop(key, None)
                clear_saved_tokens()
                st.rerun()

    st.divider()
    st.header("Scenario controls")
    ar_delay_days = st.slider("Customer payment delay assumption", 0, 60, 14, step=1)
    collection_push_days = st.slider("Collection push improvement", 0, 30, 0, step=1)
    vendor_delay_days = st.slider("Delay vendor payments", 0, 30, 0, step=1)
    revenue_slip_pct = st.slider("Revenue / collection slip", 0, 50, 0, step=5)
    payroll_amount = st.number_input("Biweekly payroll", min_value=0.0, value=72000.0, step=5000.0)
    rent_amount = st.number_input("Monthly rent / fixed facility cost", min_value=0.0, value=18000.0, step=1000.0)


# Load data
try:
    if mode == "QuickBooks Online" and "qbo_tokens" in st.session_state:
        invoices_df, bills_df, cash_balance = fetch_qbo_data()
    else:
        invoices_df, bills_df, cash_balance = demo_data()
except Exception as e:
    st.error(f"Could not load QBO data: {e}")
    st.info("Falling back to demo data so the forecast can still run.")
    invoices_df, bills_df, cash_balance = demo_data()


forecast_df, enriched_invoices, enriched_bills = build_forecast(
    invoices_df,
    bills_df,
    cash_balance,
    ar_delay_days,
    collection_push_days,
    vendor_delay_days,
    revenue_slip_pct,
    payroll_amount,
    rent_amount,
)

rw = runway_weeks(forecast_df)
min_cash = forecast_df["ending_cash"].min()
week_13_cash = forecast_df["ending_cash"].iloc[-1]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Starting cash", f"${cash_balance:,.0f}")
c2.metric("Runway", "13+ weeks" if rw >= 13 else f"{rw:.1f} weeks")
c3.metric("Lowest cash", f"${min_cash:,.0f}")
c4.metric("Week 13 cash", f"${week_13_cash:,.0f}")

st.subheader("13-week cash forecast")

chart_df = forecast_df.copy()
chart_df["week_label"] = chart_df["week"].apply(lambda d: d.strftime("%b %d"))
fig = px.line(chart_df, x="week_label", y="ending_cash", markers=True)
fig.update_layout(
    height=420,
    xaxis_title="Week",
    yaxis_title="Ending cash",
    margin=dict(l=20, r=20, t=20, b=20),
)
st.plotly_chart(fig, use_container_width=True)

display_forecast = forecast_df.copy()
display_forecast["week"] = display_forecast["week"].apply(lambda d: d.strftime("%Y-%m-%d"))
for col in ["starting_cash", "ar_inflow", "ap_outflow", "payroll", "rent", "ending_cash", "net_cash_flow"]:
    display_forecast[col] = display_forecast[col].map(lambda x: f"${x:,.0f}")
st.dataframe(display_forecast, use_container_width=True, hide_index=True)

left, right = st.columns([0.52, 0.48])

with left:
    st.subheader("AI-assisted risk flags")
    risks = generate_risks(forecast_df, enriched_invoices, enriched_bills)
    for r in risks:
        st.markdown(f'<div class="risk-card">⚠️ {r}</div>', unsafe_allow_html=True)

with right:
    st.subheader("Recommended cash decisions")
    actions = generate_actions(forecast_df, enriched_invoices, enriched_bills)
    for a in actions:
        st.markdown(f'<div class="action-card">✅ {a}</div>', unsafe_allow_html=True)

st.divider()

tab1, tab2, tab3 = st.tabs(["Open AR", "Open AP", "Weekly Decision Report"])

with tab1:
    st.dataframe(enriched_invoices.drop(columns=[c for c in ["due_date_parsed", "expected_week"] if c in enriched_invoices.columns], errors="ignore"), use_container_width=True)

with tab2:
    st.dataframe(enriched_bills.drop(columns=[c for c in ["due_date_parsed", "expected_week"] if c in enriched_bills.columns], errors="ignore"), use_container_width=True)

with tab3:
    st.markdown("## Weekly Cash Decision Report")
    st.markdown(f"**Runway:** {'13+ weeks' if rw >= 13 else f'{rw:.1f} weeks'}")
    st.markdown(f"**Lowest projected cash:** ${min_cash:,.0f}")
    st.markdown("### What changed / what matters")
    for r in risks[:3]:
        st.markdown(f"- {r}")
    st.markdown("### Recommended actions this week")
    for a in actions[:3]:
        st.markdown(f"- {a}")
    st.download_button(
        "Download report as Markdown",
        data=(
            "# Weekly Cash Decision Report\n\n"
            f"Runway: {'13+ weeks' if rw >= 13 else f'{rw:.1f} weeks'}\n\n"
            f"Lowest projected cash: ${min_cash:,.0f}\n\n"
            "## Risks\n" + "\n".join([f"- {r}" for r in risks]) + "\n\n"
            "## Actions\n" + "\n".join([f"- {a}" for a in actions])
        ),
        file_name="weekly_cash_decision_report.md",
        mime="text/markdown",
    )

st.caption(
    "MVP note: risk flags are rules-based for demo purposes. The learning layer can later use customer/vendor payment history and forecast-vs-actual variance."
)
