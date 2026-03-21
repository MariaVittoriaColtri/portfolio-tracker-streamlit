import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# page config
st.set_page_config(page_title="Portfolio Dashboard", layout="wide", page_icon="📊")

# custom CSS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;500;700&display=swap');
html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
.stApp { background-color: #0a0c0f; }
h1, h2, h3 { font-family: 'Syne', sans-serif !important; color: #e8e4dc !important; }
.agent-card {
    background: #0d1017;
    border: 0.5px solid #1e2530;
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 8px;
}
[data-testid="stDataFrame"] { background: #111318 !important; }
div[data-testid="stRadio"] > div { gap: 4px !important; flex-direction: row !important; }
div[data-testid="stRadio"] label {
    background: #111318 !important;
    border: 0.5px solid #1e2530 !important;
    border-radius: 6px !important;
    padding: 4px 12px !important;
    color: #5a6070 !important;
    font-family: 'DM Mono', monospace !important;
    font-size: 11px !important;
    cursor: pointer !important;
}
div[data-testid="stRadio"] label[data-checked="true"] {
    border-color: #00d68f !important;
    color: #00d68f !important;
    background: #0d1a12 !important;
}
</style>
""", unsafe_allow_html=True)

# title
last_update = datetime.now().strftime("%d %b %Y — %H:%M")
st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:20px;">
    <div>
        <h1 style="font-size:24px;font-weight:700;margin:0;color:#e8e4dc;">Portfolio Dashboard</h1>
        <p style="color:#5a6070;font-family:'DM Mono',monospace;font-size:11px;margin:4px 0 0;">Not financial advice — data refreshes every hour</p>
    </div>
    <p style="color:#5a6070;font-family:'DM Mono',monospace;font-size:11px;margin:0;">Updated {last_update}</p>
</div>
""", unsafe_allow_html=True)

# STEP 1: load financial ledger
df_ledger = pd.read_csv("financial_ledger.csv", parse_dates=["Date"])
tickers_list = df_ledger["Ticker"].unique().tolist()

# STEP 2: download historical price data — cache 1 hour
@st.cache_data(ttl=3600)
def load_price_data(tickers):
    df = yf.download(tickers, period="5y", auto_adjust=True)["Close"]
    df = df.reset_index()
    return df

with st.spinner("Loading market data..."):
    df_prices = load_price_data(tickers_list)

# STEP 3: calculate returns and volatility
df_prices_long = df_prices.melt(id_vars="Date", var_name="Ticker", value_name="Close")
df_prices_long["Close"] = df_prices_long.groupby("Ticker")["Close"].ffill()
df_prices_long["Date"] = pd.to_datetime(df_prices_long["Date"]).dt.tz_localize(None)
df_ledger["Date"] = pd.to_datetime(df_ledger["Date"]).dt.tz_localize(None)
df_prices_long = df_prices_long.sort_values(["Ticker", "Date"])

df_prices_long["Daily_Return_%"] = (
    df_prices_long.groupby("Ticker")["Close"].pct_change() * 100
).round(2)

df_prices_long["Volatility_30d"] = df_prices_long.groupby("Ticker")["Daily_Return_%"].transform(
    lambda x: x.rolling(window=30).std()
)
df_prices_long["Volatility_Ann_%"] = (df_prices_long["Volatility_30d"] * np.sqrt(252)).round(2)

# STEP 4: calculate market value and exposure
df_investments = df_ledger.groupby("Ticker")["Quantity"].sum().reset_index()
df_merged = pd.merge(df_prices_long, df_investments, on="Ticker", how="left")
df_merged["Market_Value"] = df_merged["Quantity"] * df_merged["Close"]
df_merged["total_daily_val"] = df_merged.groupby("Date")["Market_Value"].transform("sum")
df_merged["Exposure_%"] = (df_merged["Market_Value"] / df_merged["total_daily_val"] * 100).round(2)

# STEP 5: calculate ROI, Unrealized Profit, DoD, MoM, YoY
today = df_prices_long["Date"].max()

purchase_list = []
for ticker in tickers_list:
    df_t_prices = df_prices_long[df_prices_long["Ticker"] == ticker].sort_values("Date")
    df_t_ledger = df_ledger[df_ledger["Ticker"] == ticker].sort_values("Date")
    if df_t_prices.empty or df_t_ledger.empty:
        continue
    merged = pd.merge_asof(df_t_ledger, df_t_prices, on="Date", direction="nearest")
    merged["Ticker"] = ticker
    merged = merged.rename(columns={"Close": "Purchase_Price"})
    merged = merged[["Ticker", "Date", "Quantity", "Purchase_Price"]]
    purchase_list.append(merged)

purchase_data = pd.concat(purchase_list, ignore_index=True)
purchase_data["Initial_Investment"] = purchase_data["Purchase_Price"] * purchase_data["Quantity"]

initial = purchase_data.groupby("Ticker").agg(
    Initial_Investment=("Initial_Investment", "sum"),
    Total_Quantity=("Quantity", "sum")
).reset_index()

latest_prices = df_prices_long.sort_values("Date").groupby("Ticker").last()[["Close"]].reset_index().rename(columns={"Close": "Latest_Price"})

summary = initial.merge(latest_prices, on="Ticker")
summary["Total_Investment"] = (summary["Latest_Price"] * summary["Total_Quantity"]).round(2)
summary["Unrealized Profit ($)"] = (summary["Total_Investment"] - summary["Initial_Investment"]).round(2)

summary["ROI (%)"] = summary.apply(
    lambda r: round((r["Unrealized Profit ($)"] / r["Initial_Investment"]) * 100, 2)
    if r["Initial_Investment"] > 0 else None, axis=1
)

def get_price_on(days_ago):
    target = today - pd.Timedelta(days=days_ago)
    result = df_prices_long.groupby("Ticker").apply(
        lambda x: x[x["Date"] <= target]["Close"].iloc[-1] if not x[x["Date"] <= target].empty else None
    ).reset_index()
    result.columns = ["Ticker", f"Price_{days_ago}d"]
    return result

summary = summary.merge(get_price_on(1), on="Ticker")
summary = summary.merge(get_price_on(30), on="Ticker")
summary = summary.merge(get_price_on(365), on="Ticker")

summary["DoD (%)"] = ((summary["Latest_Price"] - summary["Price_1d"]) / summary["Price_1d"] * 100).round(2)
summary["MoM (%)"] = ((summary["Latest_Price"] - summary["Price_30d"]) / summary["Price_30d"] * 100).round(2)
summary["YoY (%)"] = summary.apply(
    lambda r: round(((r["Latest_Price"] - r["Price_365d"]) / r["Price_365d"]) * 100, 2)
    if pd.notna(r["Price_365d"]) and r["Price_365d"] > 0 else None, axis=1
)

latest_vol = df_merged[df_merged["Date"] == today][["Ticker", "Volatility_Ann_%", "Exposure_%"]]
summary = summary.merge(latest_vol, on="Ticker", how="left")

summary = summary.rename(columns={
    "Volatility_Ann_%": "Ann. Volatility (%)",
    "Exposure_%": "Portfolio Weight (%)"
})

# agent input — aggregated summary with readable numbers
cutoff_date = today - pd.Timedelta(days=30)
df_last_30d = df_merged[df_merged["Date"] > cutoff_date].copy().sort_values(["Ticker", "Date"])
agent_summary = df_last_30d.groupby("Ticker").agg(
    Avg_Exposure=("Exposure_%", "mean"),
    Volatility=("Volatility_Ann_%", "last"),
    Price_Change_30d=("Close", lambda x: round((x.iloc[-1] - x.iloc[0]) / x.iloc[0] * 100, 2))
).reset_index()
agent_summary = agent_summary.merge(summary[["Ticker", "ROI (%)"]], on="Ticker")
agent_summary["Avg_Exposure"] = agent_summary["Avg_Exposure"].round(1)
agent_summary["Volatility"] = agent_summary["Volatility"].round(1)

# METRIC CARDS
total_capital = summary["Total_Investment"].sum()
unrealized = summary["Unrealized Profit ($)"].sum()
mom_avg = summary["MoM (%)"].mean()
mom_color = "#00d68f" if mom_avg >= 0 else "#ff5050"
mom_sign = "+" if mom_avg >= 0 else ""
total_roi = round((unrealized / (total_capital - unrealized)) * 100, 2) if (total_capital - unrealized) > 0 else 0

st.markdown(f"""
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">
    <div style="background:#111318;border:0.5px solid #1e2530;border-radius:10px;padding:16px 18px;">
        <div style="font-size:10px;color:#5a6070;letter-spacing:1.5px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:8px;">Total Capital</div>
        <div style="font-size:26px;font-weight:700;color:#00d68f;font-family:'DM Mono',monospace;letter-spacing:-1px;">${total_capital:,.0f}</div>
        <div style="font-size:10px;color:#5a6070;font-family:'DM Mono',monospace;margin-top:4px;">current value</div>
    </div>
    <div style="background:#111318;border:0.5px solid #1e2530;border-radius:10px;padding:16px 18px;">
        <div style="font-size:10px;color:#5a6070;letter-spacing:1.5px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:8px;">Unrealized Profit</div>
        <div style="font-size:26px;font-weight:700;color:#00d68f;font-family:'DM Mono',monospace;letter-spacing:-1px;">+${unrealized:,.0f}</div>
        <div style="font-size:10px;color:#5a6070;font-family:'DM Mono',monospace;margin-top:4px;">gain since purchase</div>
    </div>
    <div style="background:#111318;border:0.5px solid #1e2530;border-radius:10px;padding:16px 18px;">
        <div style="font-size:10px;color:#5a6070;letter-spacing:1.5px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:8px;">Total ROI</div>
        <div style="font-size:26px;font-weight:700;color:#00d68f;font-family:'DM Mono',monospace;letter-spacing:-1px;">+{total_roi:.2f}%</div>
        <div style="font-size:10px;color:#5a6070;font-family:'DM Mono',monospace;margin-top:4px;">all-time return</div>
    </div>
    <div style="background:#111318;border:0.5px solid #1e2530;border-radius:10px;padding:16px 18px;">
        <div style="font-size:10px;color:#5a6070;letter-spacing:1.5px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:8px;">MoM Change</div>
        <div style="font-size:26px;font-weight:700;color:{mom_color};font-family:'DM Mono',monospace;letter-spacing:-1px;">{mom_sign}{mom_avg:.2f}%</div>
        <div style="font-size:10px;color:#5a6070;font-family:'DM Mono',monospace;margin-top:4px;">last 30 days avg</div>
    </div>
</div>
""", unsafe_allow_html=True)

# LAYOUT
col1, col2 = st.columns([1.2, 1.8])

# LEFT COLUMN: portfolio table
with col1:
    title_col, btn_col = st.columns([2, 1])
    with title_col:
        st.markdown("<p style='font-size:13px;font-weight:500;color:#e8e4dc;margin-bottom:8px;font-family:Syne,sans-serif;'>Holdings</p>", unsafe_allow_html=True)
    with btn_col:
        csv = summary.to_csv(index=False).encode("utf-8")
        st.download_button("↓ Export", csv, "portfolio_summary.csv", "text/csv")

    cols_to_show = ["Ticker", "ROI (%)", "Unrealized Profit ($)", "MoM (%)", "YoY (%)", "Ann. Volatility (%)", "Portfolio Weight (%)"]
    st.dataframe(
        summary[cols_to_show].style.format({
            "ROI (%)": lambda v: f"+{v:.2f}%" if isinstance(v, float) and v > 0 else (f"{v:.2f}%" if isinstance(v, float) else "—"),
            "Unrealized Profit ($)": lambda v: f"+${v:,.0f}" if isinstance(v, float) and v > 0 else (f"-${abs(v):,.0f}" if isinstance(v, float) else "—"),
            "MoM (%)": lambda v: f"+{v:.2f}%" if isinstance(v, float) and v > 0 else (f"{v:.2f}%" if isinstance(v, float) else "—"),
            "YoY (%)": lambda v: f"+{v:.2f}%" if isinstance(v, float) and v > 0 else (f"{v:.2f}%" if isinstance(v, float) else "—"),
            "Ann. Volatility (%)": lambda v: f"{v:.2f}%" if isinstance(v, float) else "—",
            "Portfolio Weight (%)": lambda v: f"{v:.2f}%" if isinstance(v, float) else "—",
        }).applymap(
            lambda v: "color: #00d68f" if isinstance(v, float) and v > 0 else "color: #ff5050" if isinstance(v, float) and v < 0 else "",
            subset=["ROI (%)", "MoM (%)", "YoY (%)"]
        ),
        use_container_width=True,
        height=260
    )

# RIGHT COLUMN: time series
with col2:
    st.markdown("<p style='font-size:13px;font-weight:500;color:#e8e4dc;margin-bottom:4px;font-family:Syne,sans-serif;'>Price Performance</p>", unsafe_allow_html=True)
    st.markdown("<p style='color:#5a6070;font-size:10px;font-family:DM Mono,monospace;margin-bottom:8px;'>% return from start of selected period — select one asset to see absolute price</p>", unsafe_allow_html=True)

    periods = {"1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "MAX": 1825}
    selected_period = st.radio("", list(periods.keys()), index=4, horizontal=True, label_visibility="collapsed")
    days = periods[selected_period]

    impactful = ["GC=F", "NVDA", "BTC-USD"]
    selected = st.multiselect("Compare assets:", tickers_list, default=[t for t in impactful if t in tickers_list])

    cutoff = today - pd.Timedelta(days=days)
    df_chart = df_prices_long[
        (df_prices_long["Ticker"].isin(selected)) &
        (df_prices_long["Date"] >= cutoff)
    ]

    colors = {"GC=F": "#00d68f", "NVDA": "#648cff", "SPY": "#f0a830", "BTC-USD": "#ff5050", "AGG": "#a0b0c8"}

    fig = go.Figure()
    for ticker in selected:
        df_t = df_chart[df_chart["Ticker"] == ticker].copy()
        if df_t.empty:
            continue
        if len(selected) == 1:
            fig.add_trace(go.Scatter(
                x=df_t["Date"], y=df_t["Close"],
                name=ticker,
                line=dict(color=colors.get(ticker, "#e8e4dc"), width=2),
                mode="lines",
                fill="tozeroy",
                fillcolor="rgba(0,214,143,0.06)",
                hovertemplate=f"<b>{ticker}</b><br>${{y:,.2f}}<extra></extra>"
            ))
            fig.update_layout(yaxis_tickprefix="$")
        else:
            base = df_t["Close"].iloc[0]
            df_t["Normalized"] = ((df_t["Close"] - base) / base * 100).round(2)
            fig.add_trace(go.Scatter(
                x=df_t["Date"], y=df_t["Normalized"],
                name=ticker,
                line=dict(color=colors.get(ticker, "#e8e4dc"), width=2),
                mode="lines",
                hovertemplate=f"<b>{ticker}</b><br>%{{y:.2f}}%<extra></extra>"
            ))
            fig.update_layout(yaxis_ticksuffix="%", yaxis_zeroline=True, yaxis_zerolinecolor="#2a3040")

    fig.update_layout(
        paper_bgcolor="#111318",
        plot_bgcolor="#111318",
        font=dict(family="DM Mono", color="#5a6070", size=11),
        xaxis=dict(gridcolor="#1e2530", showline=False, zeroline=False),
        yaxis=dict(gridcolor="#1e2530", showline=False),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#e8e4dc"), orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=0, r=0, t=28, b=0),
        height=310,
        hovermode="x unified"
    )
    st.plotly_chart(fig, use_container_width=True)

# BOTTOM: strategy agent
st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
st.markdown("<p style='font-size:13px;font-weight:500;color:#e8e4dc;margin-bottom:4px;font-family:Syne,sans-serif;'>Strategy Agent — AI</p>", unsafe_allow_html=True)
st.markdown("<p style='color:#5a6070;font-size:10px;font-family:DM Mono,monospace;margin-bottom:10px;'>AI-powered BUY / SELL / HOLD / REBALANCE based on volatility, concentration risk and momentum</p>", unsafe_allow_html=True)

if st.button("Run Analysis"):
    with st.spinner("Analysing portfolio..."):
        from google.adk.agents import Agent
        from google.adk.models.google_llm import Gemini
        from google.adk.runners import InMemoryRunner
        from google.genai import types

        retry_config = types.HttpRetryOptions(
            attempts=5, exp_base=7, initial_delay=1,
            http_status_codes=[429, 500, 503, 504]
        )

        analyst_agent = Agent(
            name="StrategyAgent",
            model=Gemini(model="gemini-2.5-flash-lite", retry_options=retry_config),
            instruction=f"""
You are a Senior Portfolio Manager giving clear, direct advice to a retail investor.

Here is the portfolio data for the last 30 days:
{agent_summary.to_string()}

Columns:
- Avg_Exposure: % of total portfolio this asset represents
- Volatility: annualized volatility %
- Price_Change_30d: % price change over last 30 days
- ROI: total return since purchase %

Decision rules (apply in order):
1. SELL if ROI > 500% AND Avg_Exposure > 20%
2. REBALANCE if Avg_Exposure > 30%
3. SELL if Volatility > 40 AND Price_Change_30d < -5
4. BUY if Volatility < 15 AND Price_Change_30d > 0 AND Avg_Exposure < 10%
5. HOLD otherwise

For each ticker write ONE line in this exact format:
TICKER | ACTION | Plain English explanation with the actual numbers, e.g. "Gold holds 47% of your portfolio — too concentrated, consider selling some to rebalance" or "NVDA is down 12% this month with 29% volatility — momentum is weakening, consider reducing" or "AGG is stable with only 3% portfolio weight and positive momentum — good entry point"

No intro, no summary, no extra text. One line per ticker only.
            """,
        )

        runner = InMemoryRunner(agent=analyst_agent)
        response = asyncio.run(runner.run_debug(
            "Provide concise strategic advice for my portfolio holdings."
        ))

        output = ""
        for event in response:
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        output += part.text + "\n"

        action_colors = {"BUY": "#00d68f", "SELL": "#ff5050", "HOLD": "#f0a830", "REBALANCE": "#648cff"}
        action_icons = {"BUY": "↑ BUY", "SELL": "↓ SELL", "HOLD": "— HOLD", "REBALANCE": "⇄ REBALANCE"}

        st.markdown(f"<p style='color:#5a6070;font-size:10px;font-family:DM Mono,monospace;margin-bottom:8px;'>Analysis at {datetime.now().strftime('%H:%M')} — Not financial advice</p>", unsafe_allow_html=True)

        agent_cols = st.columns(len(tickers_list))
        lines = [l.strip() for l in output.strip().split("\n") if "|" in l]

        for i, line in enumerate(lines[:len(tickers_list)]):
            parts = [p.strip() for p in line.split("|", 2)]
            if len(parts) >= 2:
                ticker = parts[0].strip()
                action = parts[1].strip().upper()
                reason = parts[2].strip() if len(parts) > 2 else ""
                color = action_colors.get(action, "#e8e4dc")
                label = action_icons.get(action, action)
                with agent_cols[i % len(agent_cols)]:
                    st.markdown(f"""
                    <div class="agent-card">
                        <div style="font-size:12px;color:#8a9ab0;font-family:'DM Mono',monospace;margin-bottom:6px;">{ticker}</div>
                        <div style="font-size:17px;font-weight:700;color:{color};font-family:'DM Mono',monospace;margin-bottom:10px;">{label}</div>
                        <div style="font-size:12px;color:#a0b4c8;line-height:1.7;">{reason}</div>
                    </div>""", unsafe_allow_html=True)