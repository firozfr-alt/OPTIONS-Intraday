import streamlit as st
import requests
import urllib.parse
import pandas as pd

# -----------------------------------------
# 1. UPSTOX API CONFIGURATION
# -----------------------------------------
try:
    API_KEY = st.secrets["UPSTOX_API_KEY"]
    API_SECRET = st.secrets["UPSTOX_API_SECRET"]
    REDIRECT_URI = st.secrets["UPSTOX_REDIRECT_URI"]
except KeyError:
    st.error("⚠️ Missing Upstox credentials. Please configure `.streamlit/secrets.toml`.")
    st.stop()

# -----------------------------------------
# 2. AUTHENTICATION ENGINE
# -----------------------------------------
def get_login_url():
    params = {
        'response_type': 'code',
        'client_id': API_KEY,
        'redirect_uri': REDIRECT_URI
    }
    return f"https://api.upstox.com/v2/login/authorization/dialog?{urllib.parse.urlencode(params)}"

def exchange_code_for_token(auth_code):
    url = "https://api.upstox.com/v2/login/authorization/token"
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    data = {
        'code': auth_code,
        'client_id': API_KEY,
        'client_secret': API_SECRET,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code'
    }
    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        st.error(f"Failed to get token: {response.text}")
        return None

# -----------------------------------------
# 3. MARKET DATA & OPTIONS LOGIC
# -----------------------------------------
def get_index_spot_price(access_token, index_name="Nifty 50"):
    keys = {
        "Nifty 50": "NSE_INDEX|Nifty 50",
        "Bank Nifty": "NSE_INDEX|Nifty Bank",
        "FinNifty (Financials)": "NSE_INDEX|Nifty Fin Service",
        "Midcap Nifty": "NSE_INDEX|NIFTY MID SELECT"
    }
    instrument_key = keys.get(index_name)
    url = "https://api.upstox.com/v2/market-quote/quotes"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    params = {'instrument_key': instrument_key}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            response_key = instrument_key.replace('|', ':')
            if 'data' in data and response_key in data['data']:
                return data['data'][response_key]['last_price']
        return None
    except Exception:
        return None

def get_strike_interval(index_name):
    intervals = {
        "Nifty 50": 50,
        "Bank Nifty": 100,
        "FinNifty (Financials)": 50,
        "Midcap Nifty": 25
    }
    return intervals.get(index_name, 50)

def calculate_atm_strike(spot_price, index_name):
    interval = get_strike_interval(index_name)
    return round(spot_price / interval) * interval

def generate_option_chain_ladder(atm_strike, interval):
    """Generates the ITM, ATM, and OTM strikes for CE and PE"""
    return {
        "CE": {
            "ITM (+1)": atm_strike - interval,
            "ATM": atm_strike,
            "OTM (+1)": atm_strike + interval
        },
        "PE": {
            "ITM (+1)": atm_strike + interval,
            "ATM": atm_strike,
            "OTM (+1)": atm_strike - interval
        }
    }

# -----------------------------------------
# 4. STREAMLIT UI DASHBOARD
# -----------------------------------------
st.set_page_config(page_title="Upstox Options Terminal", page_icon="📈", layout="wide")

if 'access_token' not in st.session_state:
    st.session_state['access_token'] = None

query_params = st.query_params
if 'code' in query_params and not st.session_state['access_token']:
    auth_code = query_params['code']
    with st.spinner("Exchanging authorization code for Access Token..."):
        token = exchange_code_for_token(auth_code)
        if token:
            st.session_state['access_token'] = token
            st.query_params.clear()
            st.rerun()

if not st.session_state['access_token']:
    st.title("🔐 Upstox API Login")
    st.write("Authorize the application to fetch live options data.")
    st.link_button("Login with Upstox", get_login_url(), type="primary")
    st.stop()

st.title("🎯 Intraday Options Setup Scanner")
st.success("✅ Connected to Upstox API")

col1, col2 = st.columns(2)
with col1:
    selected_index = st.radio("Select Index Sector", ["Nifty 50", "Bank Nifty", "FinNifty (Financials)", "Midcap Nifty"])
with col2:
    strategy_type = st.selectbox("Select Intraday Strategy", [
        "Delta-Neutral (Short Straddle)", 
        "Directional (Long Call/Put)", 
        "Delta Blast (Momentum Breakout)"
    ])

if st.button("Fetch Live Setup", type="primary"):
    with st.spinner(f"Fetching live spot price for {selected_index}..."):
        spot_price = get_index_spot_price(st.session_state['access_token'], selected_index)
        
        if spot_price:
            interval = get_strike_interval(selected_index)
            atm_strike = calculate_atm_strike(spot_price, selected_index)
            ladder = generate_option_chain_ladder(atm_strike, interval)
            
            st.metric(label=f"{selected_index} Spot Price", value=f"₹{spot_price:,.2f}")
            
            # --- DISPLAY STRIKE LADDER ---
            st.subheader("📊 Options Strike Map")
            
            df_chain = pd.DataFrame({
                "Moneyness": ["ITM (+1)", "ATM", "OTM (+1)"],
                "Call (CE) Strike": [ladder["CE"]["ITM (+1)"], ladder["CE"]["ATM"], ladder["CE"]["OTM (+1)"]],
                "Put (PE) Strike": [ladder["PE"]["ITM (+1)"], ladder["PE"]["ATM"], ladder["PE"]["OTM (+1)"]]
            })
            st.dataframe(df_chain, hide_index=True, use_container_width=True)

            # --- STRATEGY EXECUTION ---
            st.subheader("⚡ Actionable Strategy Execution")
            
            if strategy_type == "Delta-Neutral (Short Straddle)":
                st.write("Sell the ATM Call and ATM Put simultaneously to capture premium decay (Theta).")
                st.markdown(f"- **SELL:** {ladder['CE']['ATM']} CE")
                st.markdown(f"- **SELL:** {ladder['PE']['ATM']} PE")
                
            elif strategy_type == "Directional (Long Call/Put)":
                st.write("Buy options based on trend. Use ITM for higher delta, OTM for lower capital.")
                st.markdown(f"**Bullish Setup:**")
                st.markdown(f"- Aggressive (High Delta): BUY {ladder['CE']['ITM (+1)']} CE (ITM)")
                st.markdown(f"- Balanced: BUY {ladder['CE']['ATM']} CE (ATM)")
                st.markdown(f"**Bearish Setup:**")
                st.markdown(f"- Aggressive (High Delta): BUY {ladder['PE']['ITM (+1)']} PE (ITM)")
                st.markdown(f"- Balanced: BUY {ladder['PE']['ATM']} PE (ATM)")

            elif strategy_type == "Delta Blast (Momentum Breakout)":
                st.write("Explosive momentum strategy. Buy during high-volume price breakouts.")
                st.markdown(f"- **Upside Breakout:** BUY {ladder['CE']['ATM']} CE or {ladder['CE']['OTM (+1)']} CE")
                st.markdown(f"- **Downside Breakout:** BUY {ladder['PE']['ATM']} PE or {ladder['PE']['OTM (+1)']} PE")
                st.error("🚨 Exit if the breakout stalls for more than 2-3 candles to avoid Theta decay.")
                
        else:
            st.error("Failed to fetch market quote. Check API limits or token validity.")
