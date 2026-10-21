import streamlit as st
import requests
import urllib.parse

# -----------------------------------------
# 1. UPSTOX API CONFIGURATION
# -----------------------------------------
# Ensure you have a .streamlit/secrets.toml file with these keys
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
    # Upstox Instrument Keys for Indices
    keys = {
        "Nifty 50": "NSE_INDEX|Nifty 50",
        "Bank Nifty": "NSE_INDEX|Nifty Bank"
    }
    instrument_key = keys.get(index_name)
    
    url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={instrument_key}"
    headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        try:
            return data['data'][instrument_key]['last_price']
        except KeyError:
            return None
    return None

def calculate_atm_strike(spot_price, index_name):
    # Nifty strike intervals are 50, Bank Nifty are 100
    interval = 50 if index_name == "Nifty 50" else 100
    return round(spot_price / interval) * interval

# -----------------------------------------
# 4. STREAMLIT UI DASHBOARD
# -----------------------------------------
st.set_page_config(page_title="Upstox Options Terminal", page_icon="📈", layout="centered")

# Initialize session state for the token
if 'access_token' not in st.session_state:
    st.session_state['access_token'] = None

# Step 1: Check for authorization code in the URL (Redirect from Upstox)
query_params = st.query_params
if 'code' in query_params and not st.session_state['access_token']:
    auth_code = query_params['code']
    with st.spinner("Exchanging authorization code for Access Token..."):
        token = exchange_code_for_token(auth_code)
        if token:
            st.session_state['access_token'] = token
            # Clear the URL parameters to keep it clean
            st.query_params.clear()
            st.rerun()

# Step 2: Render Login Screen if not authenticated
if not st.session_state['access_token']:
    st.title("🔐 Upstox API Login")
    st.write("You must authorize the application to fetch live options data.")
    
    # FIX APPLIED HERE: Replaced st.markdown HTML with native st.link_button
    login_url = get_login_url()
    st.link_button("Login with Upstox", login_url, type="primary")
    st.stop()

# Step 3: Render Main Options Dashboard if authenticated
st.title("🎯 Intraday Options Setup Scanner")
st.success("✅ Successfully connected to Upstox API")

if st.button("Log Out"):
    st.session_state['access_token'] = None
    st.rerun()

st.divider()

col1, col2 = st.columns(2)
with col1:
    selected_index = st.radio("Select Index", ["Nifty 50", "Bank Nifty"])

with col2:
    strategy_type = st.selectbox("Select Intraday Strategy", ["Delta-Neutral (Short Straddle)", "Directional (Long Call/Put)"])

if st.button("Fetch Live Setup"):
    with st.spinner(f"Fetching live spot price for {selected_index}..."):
        spot_price = get_index_spot_price(st.session_state['access_token'], selected_index)
        
        if spot_price:
            atm_strike = calculate_atm_strike(spot_price, selected_index)
            
            st.metric(label=f"{selected_index} Spot Price", value=f"₹{spot_price:,.2f}")
            st.info(f"**Current ATM Strike:** {atm_strike}")
            
            st.subheader("Actionable Options Setup")
            
            if strategy_type == "Delta-Neutral (Short Straddle)":
                st.write("Sell the ATM Call and ATM Put simultaneously to capture premium decay (Theta) in a sideways market.")
                st.markdown(f"- **SELL:** {atm_strike} CE")
                st.markdown(f"- **SELL:** {atm_strike} PE")
                st.warning("Ensure strict stop-losses on both legs to protect against sudden intraday spikes.")
                
            elif strategy_type == "Directional (Long Call/Put)":
                st.write("Buy the ATM option based on your intraday trend analysis.")
                st.markdown(f"- **If Bullish:** BUY {atm_strike} CE")
                st.markdown(f"- **If Bearish:** BUY {atm_strike} PE")
        else:
            st.error("Failed to fetch market quote. Please check your API limits or token validity.")
