import streamlit as st
import pandas as pd
import requests
import upstox_client
from upstox_client.rest import ApiException
import urllib.parse

st.set_page_config(page_title="Auto Delta Blast Terminal", layout="wide")

# --- 1. OAUTH 2.0 LOGIN & CONFIGURATION ---
st.sidebar.header("Upstox Setup")

# Input fields for API credentials
api_key = st.sidebar.text_input("API Key (client_id)")
api_secret = st.sidebar.text_input("API Secret (client_secret)", type="password")
redirect_uri = st.sidebar.text_input("Redirect URI (Exact Streamlit App URL)")

# Session state to hold the token so it doesn't reset on every button click
if 'access_token' not in st.session_state:
    st.session_state.access_token = None

# --- OAuth Step 2 & 3: Capture Code and Generate Token ---
# Check if we just returned from Upstox with an auth code in the URL
if "code" in st.query_params and not st.session_state.access_token:
    auth_code = st.query_params["code"]
    
    # Exchange auth code for access token
    token_url = 'https://api.upstox.com/v2/login/authorization/token'
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    data = {
        'code': auth_code,
        'client_id': api_key,
        'client_secret': api_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }
    
    response = requests.post(token_url, headers=headers, data=data) #
    
    if response.status_code == 200:
        # Save token to session state
        st.session_state.access_token = response.json().get("access_token")
        # Clear the query params from the URL to clean it up
        st.query_params.clear()
        st.rerun()
    else:
        st.sidebar.error(f"Failed to fetch token: {response.text}")

# --- OAuth Step 1: Login UI ---
# If no token is present, show the login button and stop rendering the rest of the app
if not st.session_state.access_token:
    st.title("🔒 Login Required")
    st.write("Please enter your API Key, Secret, and Redirect URI in the sidebar to authenticate with Upstox.")
    
    if api_key and redirect_uri:
        # Generate the Upstox login dialog URL
        encoded_redirect = urllib.parse.quote(redirect_uri, safe='')
        login_url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={api_key}&redirect_uri={encoded_redirect}"
        
        st.markdown(f'<a href="{login_url}" target="_self"><button style="background-color:#4CAF50; color:white; padding:14px 20px; margin:8px 0; border:none; cursor:pointer; width:100%;">Click Here to Login via Upstox</button></a>', unsafe_allow_html=True)
    st.stop()

# --- 2. ASSET MAPPING & UI CONFIG ---
st.sidebar.success("✅ Authenticated Successfully!")
if st.sidebar.button("Logout"):
    st.session_state.access_token = None
    st.rerun()

st.sidebar.markdown("---")
ASSET_MAP = {
    "NIFTY 50": {"spot": "NSE_INDEX|Nifty 50", "opt": "NSE_INDEX|Nifty 50", "step": 50},
    "BANKNIFTY": {"spot": "NSE_INDEX|Nifty Bank", "opt": "NSE_INDEX|Nifty Bank", "step": 100},
    "FINNIFTY": {"spot": "NSE_INDEX|Nifty Fin Service", "opt": "NSE_INDEX|Nifty Fin Service", "step": 50}
}

selected_asset = st.sidebar.selectbox("Select Index", list(ASSET_MAP.keys()))
asset_config = ASSET_MAP[selected_asset]

strike_type = st.sidebar.radio("Strike Selection", ["ATM", "1 Strike OTM", "2 Strikes OTM"])

if strike_type == "ATM":
    strike_offset = 0
elif strike_type == "1 Strike OTM":
    strike_offset = 1
elif strike_type == "2 Strikes OTM":
    strike_offset = 2

# --- 3. API FUNCTIONS ---
def get_live_spot(instrument_key, token):
    """Fetches live Last Traded Price (LTP) using Upstox v2 API."""
    url = f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={instrument_key}"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json().get('data', {})
            key_response = list(data.keys())[0] if data else None
            return data.get(key_response, {}).get('last_price', 0) if key_response else 0
        else:
            st.error(f"Upstox API Error: {response.status_code} - {response.text}")
            return 0
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return 0

def get_target_instruments(inst_key, current_spot, step, token, offset):
    """Fetches the option chain and identifies the target CE and PE keys."""
    configuration = upstox_client.Configuration()
    configuration.access_token = token
    api_instance = upstox_client.OptionsApi(upstox_client.ApiClient(configuration))
    
    try:
        response = api_instance.get_option_contracts(inst_key)
        options_data = response.data
        
        if not options_data:
            return None, None, None, None

        expiries = sorted(list(set([opt.expiry for opt in options_data])))
        nearest_expiry = expiries[0]
        
        atm_strike = round(current_spot / step) * step
        ce_target_strike = atm_strike + (offset * step)
        pe_target_strike = atm_strike - (offset * step)
        
        ce_instrument = next((opt for opt in options_data if opt.expiry == nearest_expiry and opt.strike == ce_target_strike and opt.instrument_type == 'CE'), None)
        pe_instrument = next((opt for opt in options_data if opt.expiry == nearest_expiry and opt.strike == pe_target_strike and opt.instrument_type == 'PE'), None)
        
        ce_key = ce_instrument.instrument_key if ce_instrument else None
        pe_key = pe_instrument.instrument_key if pe_instrument else None
        
        return ce_target_strike, pe_target_strike, ce_key, pe_key
    except ApiException as e:
        st.error(f"Error fetching option chain: {e}")
        return None, None, None, None

def get_live_greeks(keys_csv, token):
    """Fetches live Delta, Gamma, Theta, and Vega using Upstox v3 API."""
    url = f"https://api.upstox.com/v3/market-quote/option-greek?instrument_key={keys_csv}"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('data', {})
    except:
        pass
    return {}

# --- 4. EXECUTION DASHBOARD ---
st.title(f"⚡ Auto Delta Blast: {selected_asset}")

if st.button(f"Scan Live Market for {selected_asset}"):
    with st.spinner(f"Fetching Spot Price, identifying {strike_type} Strikes, and calculating Greeks..."):
        
        # Use token from session state
        active_token = st.session_state.access_token
        
        spot_price = get_live_spot(asset_config['spot'], active_token)
        if spot_price == 0:
            st.stop()
            
        st.metric(f"Current {selected_asset} Spot Price", f"₹ {spot_price}")
        
        ce_strike, pe_strike, ce_key, pe_key = get_target_instruments(asset_config['opt'], spot_price, asset_config['step'], active_token, strike_offset)
        
        if not ce_key or not pe_key:
            st.error("Could not find exact contract keys for the calculated strikes.")
            st.stop()
            
        st.info(f"**Target Strikes ({strike_type}):** Call (CE) {ce_strike} | Put (PE) {pe_strike}")
        
        greeks_data = get_live_greeks(f"{ce_key},{pe_key}", active_token)
        
        if greeks_data:
            ce_data = greeks_data.get(ce_key, {})
            pe_data = greeks_data.get(pe_key, {})
            
            ce_delta = ce_data.get('delta', 0)
            ce_gamma = ce_data.get('gamma', 0)
            ce_iv = ce_data.get('implied_volatility', 0)
            
            pe_delta = pe_data.get('delta', 0)
            pe_gamma = pe_data.get('gamma', 0)
            pe_iv = pe_data.get('implied_volatility', 0)
            
            st.markdown("---")
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader(f"🟢 {ce_strike} CE (Call)")
                st.metric("Delta", round(ce_delta, 3))
                st.metric("Gamma", round(ce_gamma, 4))
                st.metric("Implied Volatility (IV)", f"{round(ce_iv, 2)}%")
                
            with col2:
                st.subheader(f"🔴 {pe_strike} PE (Put)")
                st.metric("Delta", round(pe_delta, 3))
                st.metric("Gamma", round(pe_gamma, 4))
                st.metric("Implied Volatility (IV)", f"{round(pe_iv, 2)}%")
                
            st.markdown("---")
            st.subheader("Live Strategy Signal")
            
            delta_threshold = 0.30 if strike_offset > 0 else 0.55
            
            if ce_delta > delta_threshold and ce_iv > 15.0:
                st.success(f"🚀 DELTA BLAST (UPSIDE): Strong Momentum. Consider buying {ce_strike} CE.")
            elif pe_delta < -delta_threshold and pe_iv > 15.0:
                st.error(f"📉 DELTA BLAST (DOWNSIDE): Strong Momentum. Consider buying {pe_strike} PE.")
            else:
                st.warning(f"⚖️ CHOPPY / LOW MOMENTUM: Wait for Delta to expand beyond ±{delta_threshold}.")
