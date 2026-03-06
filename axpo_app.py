import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go

# --- Configuration & Setup ---
st.set_page_config(page_title="Producer Hedging Manager", layout="wide")


# Load the local basis data
@st.cache_data
def load_basis_data():
    df = pd.read_csv("basis_axpo.csv")
    df['date'] = pd.to_datetime(df['date'])
    return df


# Fetch latest NG=F price
@st.cache_data(ttl=3600)
def get_ng_price():
    try:
        ticker = yf.Ticker("NG=F")
        hist = ticker.history(period="1d")
        if not hist.empty:
            return hist['Close'].iloc[-1]
    except:
        pass
    return 2.50  # Fallback


# --- Main Dashboard Header & Core Inputs ---
st.title("Producer Position & Scenario Manager")
st.markdown("Select your primary parameters below:")

basis_df = load_basis_data()
locations = [col for col in basis_df.columns if col.lower() != 'date']

core_c1, core_c2, core_c3 = st.columns(3)
with core_c1:
    location = st.selectbox("Pricing Location (Basis)", locations)
with core_c2:
    daily_volume = st.number_input("Total Production (MMBtu/d)", min_value=0, value=10000, step=1000)
with core_c3:
    st.info("💡 Open the left sidebar to run 'What-If' scenarios!")

st.divider()

# --- Interactive "What-If" Sidebar ---
st.sidebar.title("What-If Scenarios")
st.sidebar.markdown("Use these tools to stress-test your position.")

st.sidebar.subheader("1. Market Shock")
price_shock_pct = st.sidebar.slider("NYMEX Price Change (%)", min_value=-50, max_value=50, value=0, step=5)

st.sidebar.subheader("2. Existing Portfolio")
hedged_volume = st.sidebar.number_input("Existing Hedged Volume", min_value=0, max_value=int(daily_volume), value=3000,
                                        step=1000)
hedged_price = st.sidebar.number_input("Average Hedge Price ($)", min_value=0.0, value=3.25, step=0.10)

st.sidebar.subheader("3. Proposed New Trade")
st.sidebar.caption("Simulate adding a new hedge right now.")
max_new_hedge = int(daily_volume) - int(hedged_volume)
proposed_volume = st.sidebar.number_input("Proposed Volume to Hedge", min_value=0, max_value=max(0, max_new_hedge),
                                          value=2000, step=1000)
proposed_price = st.sidebar.number_input("Proposed Strike Price ($)", min_value=0.0, value=2.75, step=0.10)

# --- Calculations ---
raw_ng_price = get_ng_price()
shocked_ng_price = raw_ng_price * (1 + (price_shock_pct / 100))

# Base Dataframe
df = basis_df[['date', location]].copy()
df.rename(columns={location: 'Basis'}, inplace=True)
df['NYMEX_Curve'] = shocked_ng_price

# Market & Bid Side Pricing
df['Market Price'] = df['NYMEX_Curve'] + df['Basis']
df['Bid Side'] = df['Market Price'] - 0.05

# Volume Math (Monthly)
days_in_month = 30.417
df['Total Volume'] = daily_volume * days_in_month
df['Existing Hedged'] = hedged_volume * days_in_month
df['Proposed Hedged'] = proposed_volume * days_in_month
df['Unhedged Volume'] = df['Total Volume'] - df['Existing Hedged'] - df['Proposed Hedged']

# Financial Math
df['Existing Rev'] = df['Existing Hedged'] * hedged_price
df['Proposed Rev'] = df['Proposed Hedged'] * proposed_price
df['Unhedged Rev'] = df['Unhedged Volume'] * df['Bid Side']
df['Total Revenue'] = df['Existing Rev'] + df['Proposed Rev'] + df['Unhedged Rev']

# Blended Price
df['Blended Price'] = df['Total Revenue'] / df['Total Volume']

# --- Top Level Metrics ---
st.markdown(
    f"**Current NYMEX Base:** ${raw_ng_price:.3f} | **Shocked NYMEX (-/+ {price_shock_pct}%):** ${shocked_ng_price:.3f}")

avg_bid = df['Bid Side'].mean()
avg_blended = df['Blended Price'].mean()
total_term_revenue = df['Total Revenue'].sum()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Avg Market Bid (Shocked)", f"${avg_bid:.3f}")
m2.metric("Avg Blended Price", f"${avg_blended:.3f}", delta=f"${avg_blended - avg_bid:.3f} vs Market")
m3.metric("Total % Hedged",
          f"{((hedged_volume + proposed_volume) / daily_volume * 100) if daily_volume > 0 else 0:.0f}%")
m4.metric("Total Projected Revenue", f"${total_term_revenue:,.0f}")

# --- Visualizations ---
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Price Overlay & Blended Average")
    fig_price = go.Figure()

    # Market Bid
    fig_price.add_trace(go.Scatter(x=df['date'], y=df['Bid Side'], mode='lines+markers', name='Market Bid Side',
                                   line=dict(color='red', dash='dash')))

    # Existing Hedge Strike
    if hedged_volume > 0:
        fig_price.add_trace(
            go.Scatter(x=df['date'], y=[hedged_price] * len(df), mode='lines', name='Existing Hedge Strike',
                       line=dict(color='gray', dash='dot')))

    # Realized Blended Price
    fig_price.add_trace(
        go.Scatter(x=df['date'], y=df['Blended Price'], mode='lines+markers', name='Actual Blended Price',
                   line=dict(color='green', width=3)))

    fig_price.update_layout(template="plotly_white",
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                            yaxis_title="Price ($/MMBtu)")
    st.plotly_chart(fig_price, use_container_width=True, key="price_chart2")

with chart_col2:
    st.subheader("Volume Layering (Hedge Profile)")
    fig_vol = go.Figure()

    # Stacked Bars: Existing -> Proposed -> Floating
    if hedged_volume > 0:
        fig_vol.add_trace(
            go.Bar(x=df['date'], y=df['Existing Hedged'], name='Existing Hedges', marker_color='forestgreen'))
    if proposed_volume > 0:
        fig_vol.add_trace(
            go.Bar(x=df['date'], y=df['Proposed Hedged'], name='Proposed New Trade', marker_color='dodgerblue'))

    fig_vol.add_trace(
        go.Bar(x=df['date'], y=df['Unhedged Volume'], name='Unhedged (Floating)', marker_color='lightcoral'))

    fig_vol.update_layout(barmode='stack', template="plotly_white",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                          yaxis_title="Volume (MMBtu)")
    st.plotly_chart(fig_vol, use_container_width=True, key="vol_chart2")

# --- Data Schedule ---
st.subheader("Monthly Position Schedule")

display_df = df[['date', 'Basis', 'Bid Side', 'Blended Price', 'Total Volume', 'Existing Hedged', 'Proposed Hedged',
                 'Unhedged Volume']].copy()
display_df['date'] = display_df['date'].dt.strftime('%Y-%m')

for col in ['Basis', 'Bid Side', 'Blended Price']:
    display_df[col] = display_df[col].apply(lambda x: f"${x:.3f}")
for col in ['Total Volume', 'Existing Hedged', 'Proposed Hedged', 'Unhedged Volume']:
    display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f}")

st.dataframe(display_df, use_container_width=True, hide_index=True)


#################################################################
########################### Version 1.0 #########################
#################################################################

# import streamlit as st
# import pandas as pd
# import yfinance as yf
# import plotly.graph_objects as go
#
# # --- Configuration & Setup ---
# st.set_page_config(page_title="Producer Position Manager", layout="wide")
#
#
# # Load the local basis data
# @st.cache_data
# def load_basis_data():
#     df = pd.read_csv("https://robotamp.pythonanywhere.com/playground/basis_axpo.csv")
#     df['date'] = pd.to_datetime(df['date'])
#     return df
#
#
# # Fetch latest NG=F price
# @st.cache_data(ttl=3600)
# def get_ng_price():
#     try:
#         ticker = yf.Ticker("NG=F")
#         hist = ticker.history(period="1d")
#         if not hist.empty:
#             return hist['Close'].iloc[-1]
#     except:
#         pass
#     return 2.50  # Fallback if yfinance fails
#
#
# # --- Sidebar Inputs (Minimal Space) ---
# st.sidebar.title("Position Controls")
# st.sidebar.markdown("Configure your production and hedging parameters.")
#
# basis_df = load_basis_data()
# locations = [col for col in basis_df.columns if col.lower() != 'date']
#
# location = st.sidebar.selectbox("Pricing Location", locations)
#
# st.sidebar.subheader("Production Volume")
# daily_volume = st.sidebar.number_input("Total Production (MMBtu/d)", min_value=0, value=10000, step=1000)
#
# st.sidebar.subheader("Existing Hedges")
# hedged_volume = st.sidebar.number_input("Hedged Volume (MMBtu/d)", min_value=0, max_value=int(daily_volume), value=5000,
#                                         step=1000)
# hedged_price = st.sidebar.number_input("Average Hedge Price ($/MMBtu)", min_value=0.0, value=3.00, step=0.10)
#
# # --- Calculations ---
# ng_base_price = get_ng_price()
#
# # Base Dataframe
# df = basis_df[['date', location]].copy()
# df.rename(columns={location: 'Basis'}, inplace=True)
# df['NYMEX_Curve'] = ng_base_price
#
# # Market & Bid Side Pricing (Producer sells on the Bid)
# df['Market Price'] = df['NYMEX_Curve'] + df['Basis']
# df['Bid Side'] = df['Market Price'] - 0.05
#
# # Volume Math (Monthly)
# days_in_month = 30.417
# df['Total Volume'] = daily_volume * days_in_month
# df['Hedged Volume'] = hedged_volume * days_in_month
# df['Unhedged Volume'] = df['Total Volume'] - df['Hedged Volume']
#
# # Financial Math & Blended Average Price
# df['Hedged Revenue'] = df['Hedged Volume'] * hedged_price
# df['Unhedged Revenue'] = df['Unhedged Volume'] * df['Bid Side']
# df['Total Revenue'] = df['Hedged Revenue'] + df['Unhedged Revenue']
#
# # Blended Price = Total Revenue / Total Volume
# df['Blended Price'] = df['Total Revenue'] / df['Total Volume']
#
# # --- Main Dashboard (Maximal View) ---
# st.title("Producer Position & Hedging Manager")
# st.markdown(f"**Location:** {location} | **NYMEX NG=F Base:** ${ng_base_price:.3f} | **Target Pricing:** Bid Side")
#
# # --- Top Level Metrics ---
# avg_bid = df['Bid Side'].mean()
# avg_blended = df['Blended Price'].mean()
# hedge_pct = (hedged_volume / daily_volume) * 100 if daily_volume > 0 else 0
# total_term_revenue = df['Total Revenue'].sum()
#
# m1, m2, m3, m4 = st.columns(4)
# m1.metric("Average Market Bid", f"${avg_bid:.3f}")
# m2.metric("Average Blended Price", f"${avg_blended:.3f}", delta=f"${avg_blended - avg_bid:.3f} vs Market")
# m3.metric("Hedged Position", f"{hedge_pct:.0f}%")
# m4.metric("Total Projected Revenue", f"${total_term_revenue:,.0f}")
#
# st.divider()
#
# # --- Visualizations ---
# chart_col1, chart_col2 = st.columns(2)
#
# with chart_col1:
#     st.subheader("Pricing & Blended Average Curve")
#     fig_price = go.Figure()
#
#     # Current Market Bid
#     fig_price.add_trace(go.Scatter(x=df['date'], y=df['Bid Side'], mode='lines+markers', name='Market Bid Side',
#                                    line=dict(color='red', dash='dash')))
#
#     # Flat Hedged Price Line
#     fig_price.add_trace(go.Scatter(x=df['date'], y=[hedged_price] * len(df), mode='lines', name='Hedge Strike Price',
#                                    line=dict(color='gray', dash='dot')))
#
#     # Realized Blended Price
#     fig_price.add_trace(
#         go.Scatter(x=df['date'], y=df['Blended Price'], mode='lines+markers', name='Actual Blended Price',
#                    line=dict(color='green', width=3)))
#
#     fig_price.update_layout(template="plotly_white",
#                             legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
#                             yaxis_title="Price ($/MMBtu)")
#     st.plotly_chart(fig_price, use_container_width=True, key="price_chart")
#
# with chart_col2:
#     st.subheader("Volume Hedging Profile")
#     fig_vol = go.Figure()
#
#     # Stacked Bars: Fixed vs Floating
#     fig_vol.add_trace(go.Bar(x=df['date'], y=df['Hedged Volume'], name='Hedged Volume (Fixed)', marker_color='green'))
#     fig_vol.add_trace(
#         go.Bar(x=df['date'], y=df['Unhedged Volume'], name='Unhedged Volume (Floating)', marker_color='lightcoral'))
#
#     fig_vol.update_layout(barmode='stack', template="plotly_white",
#                           legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
#                           yaxis_title="Volume (MMBtu/Month)")
#     st.plotly_chart(fig_vol, use_container_width=True, key="vol_chart")
#
# # --- Data Schedule ---
# st.subheader("Monthly Position Schedule")
#
# # Formatting for display
# display_df = df[['date', 'Basis', 'Bid Side', 'Blended Price', 'Total Volume', 'Hedged Volume', 'Unhedged Volume',
#                  'Total Revenue']].copy()
# display_df['date'] = display_df['date'].dt.strftime('%Y-%m')
#
# for col in ['Basis', 'Bid Side', 'Blended Price']:
#     display_df[col] = display_df[col].apply(lambda x: f"${x:.3f}")
# for col in ['Total Volume', 'Hedged Volume', 'Unhedged Volume']:
#     display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f}")
# display_df['Total Revenue'] = display_df['Total Revenue'].apply(lambda x: f"${x:,.2f}")
#
# st.dataframe(display_df, use_container_width=True, hide_index=True)

#################################################################
########################### OLD APP #############################
#################################################################

# import streamlit as st
# import pandas as pd
# import yfinance as yf
# import plotly.express as px
#
# # --- Configuration & Setup ---
# st.set_page_config(page_title="Natural Gas Pricing Tool", layout="wide")
# st.title("Natural Gas Pricing Portal")
#
# # Load the local basis data
# @st.cache_data
# def load_basis_data():
#     df = pd.read_csv("https://robotamp.pythonanywhere.com/playground/basis_axpo.csv")
#     df['date'] = pd.to_datetime(df['date'])
#     return df
#
# # Fetch latest NG=F price
# @st.cache_data(ttl=3600)
# def get_ng_price():
#     try:
#         ticker = yf.Ticker("NG=F")
#         hist = ticker.history(period="1d")
#         if not hist.empty:
#             return hist['Close'].iloc[-1]
#     except:
#         pass
#     return 2.50 # Fallback if yfinance fails or blocks the request
#
# # --- Main Page Inputs ---
# st.markdown("### Please select your parameters below:")
#
# # Organize inputs into columns for a clean look
# input_col1, input_col2, input_col3 = st.columns(3)
#
# with input_col1:
#     user_type = st.selectbox("Customer Type", ["Producer", "End User"])
#
# basis_df = load_basis_data()
# locations = [col for col in basis_df.columns if col.lower() != 'date']
#
# with input_col2:
#     location = st.selectbox("Location", locations)
#
# with input_col3:
#     daily_volume = st.number_input("Volume (MMBtu/d)", min_value=0, value=10000, step=1000)
#
# st.divider() # Add a horizontal line to separate inputs from results
#
# # --- Calculations ---
# # 1. Base NG Price
# ng_base_price = get_ng_price()
# st.caption(f"*Latest NYMEX NG=F Price: ${ng_base_price:.3f}*")
#
# # 2 & 3. Map to Dataframe
# df = basis_df[['date', location]].copy()
# df.rename(columns={location: 'Basis'}, inplace=True)
# df['NYMEX_Curve'] = ng_base_price
#
# # 4. Calculate Market Price
# df['Market Price'] = df['NYMEX_Curve'] + df['Basis']
#
# # 5. Add Bid / Offer Sides
# df['Bid Side'] = df['Market Price'] - 0.05
# df['Offer Side'] = df['Market Price'] + 0.05
#
# # Calculate Monthly Volume
# monthly_volume = daily_volume * 30.417
#
# # --- Role-Based Rendering ---
# st.header(f"Pricing Analysis for {user_type}")
#
# if user_type == "Producer":
#     target_price_col = "Bid Side"
#     st.info(f"**Action:** Selling Natural Gas | **Pricing Basis:** {target_price_col} price curve")
# else:
#     target_price_col = "Offer Side"
#     st.info(f"**Action:** Buying Natural Gas | **Pricing Basis:** {target_price_col} price curve")
#
# # Prepare Display Dataframe
# display_df = df[['date', 'Basis', 'Market Price', target_price_col]].copy()
# display_df['Monthly Volume'] = monthly_volume
# display_df['Total Value ($)'] = display_df[target_price_col] * display_df['Monthly Volume']
#
# # # Visualizations
# # chart_col1, chart_col2 = st.columns(2)
# #
# # with chart_col1:
# #     st.subheader(f"Forward Curve ({target_price_col}) at {location}")
# #     fig = px.line(display_df, x='date', y=target_price_col, markers=True,
# #                   labels={"date": "Month", target_price_col: "Price ($/MMBtu)"},
# #                   template="plotly_white")
# #     st.plotly_chart(fig, use_container_width=True)
# #
# # with chart_col2:
# #     st.subheader("Monthly Volume vs Total Value")
# #     fig2 = px.bar(display_df, x='date', y='Total Value ($)',
# #                   labels={"date": "Month", "Total Value ($)": "Total Value ($)"},
# #                   template="plotly_white")
# #     st.plotly_chart(fig2, use_container_width=True)
#
#
# # Visualizations
# chart_col1, chart_col2 = st.columns(2)
#
# with chart_col1:
#     st.subheader(f"Forward Curve ({target_price_col}) at {location}")
#     fig = px.line(display_df, x='date', y=target_price_col, markers=True,
#                   labels={"date": "Month", target_price_col: "Price ($/MMBtu)"},
#                   template="plotly_white")
#     # ADDED: key="curve_chart"
#     st.plotly_chart(fig, use_container_width=True, key="curve_chart")
#
# with chart_col2:
#     st.subheader("Monthly Volume vs Total Value")
#     fig2 = px.bar(display_df, x='date', y='Total Value ($)',
#                   labels={"date": "Month", "Total Value ($)": "Total Value ($)"},
#                   template="plotly_white")
#     # ADDED: key="bar_chart"
#     st.plotly_chart(fig2, use_container_width=True, key="bar_chart")
#
#
#
# # Data Grid & Aggregations
# st.subheader("Pricing Schedule")
#
# # Calculate averages for the top line summary
# average_price = display_df[target_price_col].mean()
# total_volume = display_df['Monthly Volume'].sum()
# total_value = display_df['Total Value ($)'].sum()
#
# metrics_c1, metrics_c2, metrics_c3 = st.columns(3)
# metrics_c1.metric("Average Term Price ($/MMBtu)", f"${average_price:.3f}")
# metrics_c2.metric("Total Term Volume", f"{total_volume:,.0f}")
# metrics_c3.metric("Total Term Value", f"${total_value:,.2f}")
#
# # Format the dataframe for cleaner display
# formatted_df = display_df.copy()
# formatted_df['date'] = formatted_df['date'].dt.strftime('%Y-%m')
# for col in ['Basis', 'Market Price', target_price_col]:
#     formatted_df[col] = formatted_df[col].apply(lambda x: f"${x:.3f}")
# formatted_df['Monthly Volume'] = formatted_df['Monthly Volume'].apply(lambda x: f"{x:,.0f}")
# formatted_df['Total Value ($)'] = formatted_df['Total Value ($)'].apply(lambda x: f"${x:,.2f}")
#
# st.dataframe(formatted_df, use_container_width=True, hide_index=True)
# col1, col2 = st.columns(2)
#
# with col1:
#     st.subheader(f"Forward Curve ({target_price_col}) at {location}")
#     fig = px.line(display_df, x='date', y=target_price_col, markers=True,
#                   labels={"date": "Month", target_price_col: "Price ($/MMBtu)"},
#                   template="plotly_white")
#     st.plotly_chart(fig, use_container_width=True)
#
# with col2:
#     st.subheader("Monthly Volume vs Price")
#     # Bar chart for volume, line chart for price is ideal, but a simple bar of total value also works well
#     fig2 = px.bar(display_df, x='date', y='Total Value ($)',
#                   labels={"date": "Month", "Total Value ($)": "Total Value ($)"},
#                   template="plotly_white")
#     st.plotly_chart(fig2, use_container_width=True)
#
# # Data Grid & Aggregations
# st.subheader("Pricing Schedule")
#
# # Calculate averages for the top line summary
# average_price = display_df[target_price_col].mean()
# total_volume = display_df['Monthly Volume'].sum()
# total_value = display_df['Total Value ($)'].sum()
#
# metrics_c1, metrics_c2, metrics_c3 = st.columns(3)
# metrics_c1.metric("Average Term Price ($/MMBtu)", f"${average_price:.3f}")
# metrics_c2.metric("Total Term Volume", f"{total_volume:,.0f}")
# metrics_c3.metric("Total Term Value", f"${total_value:,.2f}")
#
# # Format the dataframe for cleaner display
# formatted_df = display_df.copy()
# formatted_df['date'] = formatted_df['date'].dt.strftime('%Y-%m')
# for col in ['Basis', 'Market Price', target_price_col]:
#     formatted_df[col] = formatted_df[col].apply(lambda x: f"${x:.3f}")
# formatted_df['Monthly Volume'] = formatted_df['Monthly Volume'].apply(lambda x: f"{x:,.0f}")
# formatted_df['Total Value ($)'] = formatted_df['Total Value ($)'].apply(lambda x: f"${x:,.2f}")
#
# st.dataframe(formatted_df, use_container_width=True, hide_index=True)