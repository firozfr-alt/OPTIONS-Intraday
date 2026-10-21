import streamlit as st
import pandas as pd
import requests
import upstox_client
from upstox_client.rest import ApiException

st.set_page_config(page_title="Auto Delta Blast Terminal", layout="wide")

# --- 1. CONFIGURATION ---
st.sidebar.header("Upstox Setup")
access_token = st.sidebar.text_input("Enter Upstox Access Token", type="password")

# Pre-defined mapping for standard indices
ASSET_MAP = {
    "NIFTY 50": {"spot": "NSE_INDEX|Nifty 50", "opt": "NSE_INDEX|Nifty 50", "step": 50},
    "BANKNIFTY": {"spot": "NSE_INDEX|Nifty Bank", "opt": "NSE_INDEX|Nifty Bank", "step": 100},
    "FINNIFTY": {"spot": "NSE_INDEX|Nifty Fin Service", "opt": "NSE_INDEX|Nifty Fin Service", "step": 50}
}

selected_asset = st.sidebar.selectbox("Select Index", list(ASSET_MAP.keys()))
asset_config = ASSET_MAP[selected_asset]

# OTM Selection Rule
strike_type = st.sidebar.radio("Strike Selection", ["ATM", "1 Strike OTM", "2 Strikes OTM"])

# Map UI selection to integer offsets
if strike_type == "ATM":
    strike_offset = 0
elif strike_type == "1 Strike OTM":
    strike_offset = 1
elif strike_type == "2 Strikes OTM":
    strike_offset = 2

if not access_token:
    st.warning("Please enter your Upstox Access Token to proceed.")
    st.stop()

# --- 2. API FUNCTIONS ---
def get_live_spot(instrument_key, token):
    """Fetches live Last Traded Price (LTP) using Upstox v3 API."""
    url = f"https://api.upstox.com/v3/market-quote/ltp?instrument_key={instrument_key}"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json().get('data', {})
            key_response = list(data.keys())[0] if data else None
            return data.get(key_response, {}).get('last_price', 0) if key_response else 0
    except:
        pass
    return 0

def get_target_instruments(inst_key, current_spot, step, token, offset):
    """Fetches the option chain and identifies the target CE and PE keys based on OTM offset."""
    configuration = upstox_client.Configuration()
    configuration.access_token = token
    api_instance = upstox_client.OptionsApi(upstox_client.ApiClient(configuration))
    
    try:
        response = api_instance.get_option_contracts(inst_key)
        options_data = response.data
        
        if not options_data:
            return None, None, None, None

        # Find nearest expiry
        expiries = sorted(list(set([opt.expiry for opt in options_data])))
        nearest_expiry = expiries[0]
        
        # Calculate base ATM strike
        atm_strike = round(current_spot / step) * step
        
        # Calculate OTM strikes
        # For Calls (CE), OTM means higher strike. For Puts (PE), OTM means lower strike.
        ce_target_strike = atm_strike + (offset * step)
        pe_target_strike = atm_strike - (offset * step)
        
        # Filter for the exact target CE and PE
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

# --- 3. EXECUTION DASHBOARD ---
st.title(f"⚡ Auto Delta Blast: {selected_asset}")

if st.button(f"Scan Live Market for {selected_asset}"):
    with st.spinner(f"Fetching Spot Price, identifying {strike_type} Strikes, and calculating Greeks..."):
        
        # 1. Get Spot Price
        spot_price = get_live_spot(asset_config['spot'], access_token)
        if spot_price == 0:
            st.error("Failed to fetch live spot price. Check token.")
            st.stop()
            
        st.metric(f"Current {selected_asset} Spot Price", f"₹ {spot_price}")
        
        # 2. Get Dynamic Target Instruments
        ce_strike, pe_strike, ce_key, pe_key = get_target_instruments(asset_config['opt'], spot_price, asset_config['step'], access_token, strike_offset)
        
        if not ce_key or not pe_key:
            st.error("Could not find exact contract keys for the calculated strikes.")
            st.stop()
            
        st.info(f"**Target Strikes ({strike_type}):** Call (CE) {ce_strike} | Put (PE) {pe_strike}")
        
        # 3. Fetch Live Greeks for those exact instruments
        greeks_data = get_live_greeks(f"{ce_key},{pe_key}", access_token)
        
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
            
            # Adjust Delta thresholds based on OTM selection
            # OTM deltas are naturally lower (e.g. 0.20-0.40). We lower the trigger threshold if OTM is selected.
            delta_threshold = 0.30 if strike_offset > 0 else 0.55
            
            if ce_delta > delta_threshold and ce_iv > 15.0:
                st.success(f"🚀 DELTA BLAST (UPSIDE): Strong Momentum. Consider buying {ce_strike} CE.")
            elif pe_delta < -delta_threshold and pe_iv > 15.0:
                st.error(f"📉 DELTA BLAST (DOWNSIDE): Strong Momentum. Consider buying {pe_strike} PE.")
            else:
                st.warning(f"⚖️ CHOPPY / LOW MOMENTUM: Wait for Delta to expand beyond ±{delta_threshold}.")
