"""
app.py - Advanced Sci-Fi Cyber-Brutalist Command Center for BERU AI AGENT.
HIGH-TECH MISSION CONTROL INTERFACE:
  - Holographic Neon Glow & Grid Scanlines (Cyber Cyan, Neon Lime, Hazard Amber, Radical Crimson)
  - Animated Pulsing Radar Beacons & Live Hardware Progress Meters
  - 1-Click Interactive Mode Selector Deck (General, Developer, Tester, Hacker)
  - 6-Card Tactical Dispatch Launchpad with Micro-Interactions
  - Neural Matrix, Toolbelt Radar & Real-Time Telemetry HUD
Run with: streamlit run app.py
"""
import inspect
import json
import os
import time
from pathlib import Path
import psutil
import streamlit as st

from agent import run_agent
from config import PRIMARY_MODEL, GEMINI_MODEL, TRACES_DIR, WORKSPACE_DIR
from forge import ACTIVE_FORGED_TOOLS, forge_new_tool
from modes.developer import compile_to_exe, run_dev_command, run_test_suite
from modes.hacker import (
    audit_ports_and_services,
    audit_security_headers,
    deep_dns_recon,
    inspect_ssl_certificate,
)
from modes.tester import audit_code_security
from proactive_daemon import generate_system_health_briefing
from tools_registry import get_live_schemas, get_live_tools
from modes import market_analyst as market_core

# --------------------------------------------------------------------------- #
# PAGE CONFIGURATION
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="BERU // QUANTUM_MISSION_CONTROL",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
# ADVANCED SCI-FI CYBER-BRUTALIST STYLESHEET
# --------------------------------------------------------------------------- #
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700;800;900&family=JetBrains+Mono:wght@400;500;700;800&family=Orbitron:wght@700;900&display=swap');

    /* Global Theme & Grid Texture */
    * {
        border-radius: 0px !important;
        font-family: 'JetBrains Mono', monospace !important;
        box-sizing: border-box;
    }

    html, body, .stApp {
        background-color: #06080D !important;
        background-image: 
            radial-gradient(rgba(0, 240, 255, 0.05) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(6, 8, 13, 0.95), rgba(6, 8, 13, 0.98)) !important;
        background-size: 24px 24px, 100% 100% !important;
        color: #E2E8F0 !important;
    }

    /* Headings with Glowing Gradient Text */
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Chakra Petch', 'Orbitron', sans-serif !important;
        font-weight: 800 !important;
        text-transform: uppercase !important;
        letter-spacing: 1px !important;
    }

    /* Glowing Pulsing Beacon Animation */
    @keyframes pulse-glow {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(0, 255, 102, 0.7); }
        70% { transform: scale(1.05); box-shadow: 0 0 0 8px rgba(0, 255, 102, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(0, 255, 102, 0); }
    }
    .live-beacon {
        display: inline-block;
        width: 10px;
        height: 10px;
        background-color: #00FF66;
        border-radius: 50% !important;
        box-shadow: 0 0 10px #00FF66;
        animation: pulse-glow 2s infinite;
        margin-right: 6px;
    }

    /* Top Hero Header Container */
    .hero-container {
        border: 2px solid #00F0FF;
        background: linear-gradient(135deg, rgba(0, 240, 255, 0.08) 0%, rgba(11, 17, 29, 0.95) 100%);
        padding: 20px 24px;
        margin-bottom: 20px;
        box-shadow: 0 0 25px rgba(0, 240, 255, 0.2), inset 0 0 15px rgba(0, 240, 255, 0.05);
        position: relative;
    }
    .hero-container::before {
        content: "QUANTUM_OS // SYS_V2";
        position: absolute;
        top: -10px;
        right: 20px;
        background: #00F0FF;
        color: #000;
        font-size: 0.65rem;
        font-weight: 900;
        padding: 2px 8px;
        letter-spacing: 1px;
    }

    /* Tactical HUD Card */
    .hud-card {
        background: #0B0F17;
        border: 1px solid #1E293B;
        border-left: 3px solid #00F0FF;
        padding: 14px 16px;
        margin-bottom: 14px;
        transition: all 0.15s ease-in-out;
        position: relative;
    }
    .hud-card:hover {
        border-color: #00F0FF;
        box-shadow: 0 0 15px rgba(0, 240, 255, 0.15);
        transform: translateY(-2px);
    }
    .hud-title {
        font-family: 'Chakra Petch', sans-serif;
        font-weight: 800;
        font-size: 0.8rem;
        color: #94A3B8;
        display: flex;
        justify-content: space-between;
        margin-bottom: 6px;
    }
    .hud-val {
        font-size: 1.5rem;
        font-weight: 900;
        color: #FFFFFF;
        font-family: 'Orbitron', 'Chakra Petch', sans-serif;
    }

    /* Neon Progress Bars */
    .neon-bar-bg {
        background: #141C2B;
        height: 8px;
        width: 100%;
        margin-top: 8px;
        overflow: hidden;
        border: 1px solid #1E293B;
    }
    .neon-bar-fill-cyan {
        height: 100%;
        background: linear-gradient(90deg, #00A3FF, #00F0FF);
        box-shadow: 0 0 8px #00F0FF;
    }
    .neon-bar-fill-lime {
        height: 100%;
        background: linear-gradient(90deg, #00CC44, #00FF66);
        box-shadow: 0 0 8px #00FF66;
    }
    .neon-bar-fill-amber {
        height: 100%;
        background: linear-gradient(90deg, #FF8800, #FFB800);
        box-shadow: 0 0 8px #FFB800;
    }

    /* High-Impact Mode Selector Deck */
    .mode-card {
        background: #0A0E17;
        border: 2px solid #1E293B;
        padding: 12px;
        text-align: center;
        cursor: pointer;
        transition: all 0.15s ease;
    }
    .mode-card:hover {
        border-color: #00F0FF;
        box-shadow: 0 0 12px rgba(0, 240, 255, 0.3);
    }
    .mode-card-active {
        background: linear-gradient(180deg, rgba(0, 240, 255, 0.15) 0%, rgba(10, 14, 23, 0.95) 100%);
        border: 2px solid #00F0FF !important;
        box-shadow: 0 0 15px rgba(0, 240, 255, 0.4);
    }

    /* Sci-Fi Action Launchpad Grid */
    .launch-btn {
        background: #0B101A;
        border: 1px solid #1E293B;
        border-left: 3px solid #00F0FF;
        padding: 10px 14px;
        margin-bottom: 8px;
        cursor: pointer;
        transition: all 0.12s ease;
    }
    .launch-btn:hover {
        background: #111A2B;
        border-color: #00F0FF;
        transform: translateX(3px);
    }

    /* Streamlit Tabs Customization */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px !important;
        border-bottom: 2px solid #1E293B !important;
        background: #07090E !important;
        padding-bottom: 4px !important;
    }
    .stTabs [data-baseweb="tab"] {
        background: #0C121D !important;
        border: 1px solid #1E293B !important;
        border-top: 3px solid #334155 !important;
        color: #94A3B8 !important;
        font-family: 'Chakra Petch', sans-serif !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        padding: 10px 20px !important;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: #00F0FF !important;
        border-top-color: #00F0FF !important;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(180deg, #131E30 0%, #0C121D 100%) !important;
        color: #00F0FF !important;
        border: 1px solid #00F0FF !important;
        border-top: 3px solid #00F0FF !important;
        box-shadow: 0 0 15px rgba(0, 240, 255, 0.2) !important;
    }

    /* Buttons */
    .stButton > button, button[kind="primary"], button[kind="secondary"] {
        background: linear-gradient(180deg, #0F172A 0%, #0B111D 100%) !important;
        color: #00F0FF !important;
        border: 2px solid #00F0FF !important;
        font-family: 'Chakra Petch', sans-serif !important;
        font-weight: 800 !important;
        text-transform: uppercase !important;
        letter-spacing: 1px !important;
        padding: 10px 20px !important;
        box-shadow: 0 0 12px rgba(0, 240, 255, 0.25) !important;
        transition: all 0.1s ease !important;
    }
    .stButton > button:hover {
        background: #00F0FF !important;
        color: #000000 !important;
        box-shadow: 0 0 20px #00F0FF !important;
        transform: translateY(-2px);
    }
    .stButton > button:active {
        transform: translateY(1px);
    }

    /* Chat Messages */
    [data-testid="stChatMessage"] {
        border: 1px solid #1E293B !important;
        background: #0A0E17 !important;
        padding: 16px 20px !important;
        margin-bottom: 12px !important;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        border-left: 4px solid #00F0FF !important;
        background: #08111D !important;
    }
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
        border-left: 4px solid #00FF66 !important;
        background: #06120D !important;
    }

    /* Chat Input Bar */
    [data-testid="stChatInput"] {
        border: 2px solid #00F0FF !important;
        background: #0A0F1A !important;
        box-shadow: 0 0 15px rgba(0, 240, 255, 0.25) !important;
    }
    [data-testid="stChatInput"] textarea {
        color: #FFFFFF !important;
        background: #0A0F1A !important;
    }

    /* Code Blocks */
    code, pre {
        background-color: #05070B !important;
        border: 1px solid #1E293B !important;
        color: #00FF66 !important;
    }

    /* FIX FOR STREAMLIT ICON GLITCH */
    /* 1. Force the Material Icon font back so arrows render correctly instead of text */
    span[data-testid="stIconMaterial"], 
    .material-symbols-rounded {
        font-family: 'Material Symbols Rounded', sans-serif !important;
    }

    /* 2. Fix the Expander header layout */
    div[data-testid="stExpander"] summary {
        display: flex !important;
        flex-direction: row-reverse !important;
        justify-content: space-between !important;
        align-items: center !important;
        padding: 10px 15px !important;
    }
    
    /* Ensure the expander label text is visible and uses the cyber font */
    div[data-testid="stExpander"] summary p {
        font-family: 'JetBrains Mono', monospace !important;
        color: #00F0FF !important;
        font-weight: 700 !important;
        margin: 0 !important;
    }
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# SESSION STATE INITIALIZATION
# --------------------------------------------------------------------------- #
if "messages" not in st.session_state:
    st.session_state.messages = []
if "mode" not in st.session_state:
    st.session_state.mode = "General"
if "quick_prompt" not in st.session_state:
    st.session_state.quick_prompt = ""

# --------------------------------------------------------------------------- #
# REAL-TIME SYSTEM SENSORS
# --------------------------------------------------------------------------- #
def get_hardware_telemetry():
    cpu = psutil.cpu_percent()
    cpu_cores = psutil.cpu_count(logical=True)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    net = psutil.net_io_counters()
    net_tx_mb = net.bytes_sent / (1024 * 1024)
    net_rx_mb = net.bytes_recv / (1024 * 1024)
    pids_count = len(psutil.pids())
    uptime_hours = int((time.time() - psutil.boot_time()) // 3600)
    return {
        "cpu": cpu,
        "cpu_cores": cpu_cores,
        "ram": ram,
        "disk": disk,
        "net_tx_mb": net_tx_mb,
        "net_rx_mb": net_rx_mb,
        "pids": pids_count,
        "uptime": uptime_hours,
    }


telemetry = get_hardware_telemetry()

# --------------------------------------------------------------------------- #
# SIDEBAR: ADVANCED TACTICAL RACK
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown("""
    <div style="border: 2px solid #00F0FF; background: #0A0E18; padding: 14px; box-shadow: 0 0 15px rgba(0, 240, 255, 0.2); margin-bottom: 16px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <div style="font-family: 'Orbitron', 'Chakra Petch', sans-serif; font-size: 1.3rem; font-weight: 900; color: #FFF;">
                ⚡ BERU // CORE
            </div>
            <div style="font-size: 0.65rem; background: #00F0FF; color: #000; font-weight: 900; padding: 2px 6px;">
                V2.0
            </div>
        </div>
        <div style="font-size: 0.75rem; color: #94A3B8; margin-top: 4px;">
            SOVEREIGN AUTONOMOUS AGENT
        </div>
        <div style="display: flex; gap: 6px; margin-top: 8px;">
            <span style="font-size: 0.65rem; border: 1px solid #00FF66; color: #00FF66; padding: 1px 6px;">● STREAM: ACTIVE</span>
            <span style="font-size: 0.65rem; border: 1px solid #38BDF8; color: #38BDF8; padding: 1px 6px;">UIA_V2</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### // TACTICAL MODE SELECTION")
    mode_options = {
        "General": "⚡ GENERAL (Daily Ops & Web)",
        "Developer": "💻 DEVELOPER (Code, Git & Exe)",
        "Tester": "🛡️ TESTER (Security & QA)",
        "Hacker": "🕵️ HACKER (Ethical OSINT)",
    }
    mode_selection = st.radio(
        "OPERATIONAL_PROFILE:",
        ["General", "Developer", "Tester", "Hacker"],
        format_func=lambda x: mode_options[x],
        index=["General", "Developer", "Tester", "Hacker"].index(st.session_state.mode),
        label_visibility="collapsed",
    )
    st.session_state.mode = mode_selection

    st.markdown("---")
    st.markdown("### // LIVE TELEMETRY SENSORS")

    # Metric 1: CPU with Glowing Progress Bar
    st.markdown(f"""
    <div class="hud-card">
        <div class="hud-title">
            <span>CPU CORE USAGE</span>
            <span style="color: #00F0FF;">{telemetry['cpu_cores']} THREADS</span>
        </div>
        <div class="hud-val">{telemetry['cpu']}%</div>
        <div class="neon-bar-bg">
            <div class="neon-bar-fill-cyan" style="width: {min(100, max(5, telemetry['cpu']))}%;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Metric 2: RAM with Glowing Progress Bar
    st.markdown(f"""
    <div class="hud-card">
        <div class="hud-title">
            <span>RAM MEMORY ALLOCATED</span>
            <span style="color: #00FF66;">{telemetry['ram'].used // (1024**3)} / {telemetry['ram'].total // (1024**3)} GB</span>
        </div>
        <div class="hud-val">{telemetry['ram'].percent}%</div>
        <div class="neon-bar-bg">
            <div class="neon-bar-fill-lime" style="width: {min(100, max(5, telemetry['ram'].percent))}%;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Metric 3: Disk with Glowing Progress Bar
    st.markdown(f"""
    <div class="hud-card">
        <div class="hud-title">
            <span>DRIVE C: CAPACITY</span>
            <span style="color: #FFB800;">{telemetry['disk'].free / (1024**3):.1f} GB FREE</span>
        </div>
        <div class="hud-val">{telemetry['disk'].percent}%</div>
        <div class="neon-bar-bg">
            <div class="neon-bar-fill-amber" style="width: {min(100, max(5, telemetry['disk'].percent))}%;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Metric 4: Network & I/O
    st.markdown(f"""
    <div class="hud-card">
        <div class="hud-title">
            <span>SYSTEM I/O & RUNTIME</span>
            <span style="color: #A855F7;">MONITORED</span>
        </div>
        <div style="font-size: 0.75rem; color: #CBD5E1; line-height: 1.6;">
            • NETWORK TX: <b>{telemetry['net_tx_mb']:.1f} MB</b><br>
            • NETWORK RX: <b>{telemetry['net_rx_mb']:.1f} MB</b><br>
            • PROCESSES: <b>{telemetry['pids']} RUNNING</b><br>
            • UPTIME: <b>{telemetry['uptime']} HOURS</b>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    if st.button("[ PURGE_SESSION_LOG ]", use_container_width=True):
        st.session_state.messages = []
        st.session_state.quick_prompt = ""
        st.rerun()

# --------------------------------------------------------------------------- #
# TOP HOLOGRAPHIC HERO CENTERPIECE
# --------------------------------------------------------------------------- #
mode_glow_colors = {
    "General": "#00FF66",
    "Developer": "#00F0FF",
    "Tester": "#FFB800",
    "Hacker": "#FF0055",
}
curr_color = mode_glow_colors.get(st.session_state.mode, "#00F0FF")

st.markdown(f"""
<div class="hero-container" style="border-color: {curr_color}; box-shadow: 0 0 25px {curr_color}33;">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
        <div>
            <div style="font-family: 'Orbitron', 'Chakra Petch', sans-serif; font-size: 1.8rem; font-weight: 900; color: #FFFFFF; letter-spacing: -0.5px;">
                ⚡ BERU AI AGENT :: MISSION CONTROL
            </div>
            <div style="font-size: 0.85rem; color: #94A3B8; margin-top: 4px;">
                <span class="live-beacon"></span>
                <span>NEURAL ENGINE: <b>{PRIMARY_MODEL}</b></span> | 
                <span>FAILOVER: <b>{GEMINI_MODEL.upper()}</b></span> | 
                <span>SUBSYSTEM: <b>WINDOWS UIA ACCESSIBILITY TREE</b></span>
            </div>
        </div>
        <div style="margin-top: 10px;">
            <div style="border: 2px solid {curr_color}; background: #0A0E17; padding: 6px 14px; box-shadow: 0 0 12px {curr_color}66;">
                <span style="font-size: 0.75rem; color: #94A3B8; font-weight: 800;">ACTIVE PROFILE:</span> 
                <span style="font-size: 0.9rem; font-weight: 900; color: {curr_color}; font-family: 'Chakra Petch';">{st.session_state.mode.upper()}</span>
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# MAIN NAVIGATION TABS
# --------------------------------------------------------------------------- #
tab_chat, tab_market, tab_forge, tab_dev, tab_hacker, tab_traces, tab_workbench= st.tabs([
    "💬 [01_COMMAND_FEED]",
    "📈 [02_MARKET_LAB]",
    "🛠️ [03_TOOL_FORGE_LAB]",
    "💻 [04_DEV_WORKBENCH]",
    "🕵️ [05_HACKER_RECON]",
    "📜 [06_AUDIT_TRACES]",
    "🏗️ [07_WORKBENCH]",
])

# --------------------------------------------------------------------------- #
# TAB 2: MARKET LAB (READ-ONLY OHLCV CANDLES)
# --------------------------------------------------------------------------- #
with tab_market:
    st.header("Stock Market Lab")
    st.caption("Interactive OHLCV candles for India and US listings. Data comes from the configured provider or local CSV files; this panel never places orders.")
    market_col, exchange_col, symbol_col, interval_col = st.columns([1, 1, 1.3, 1])
    with market_col:
        chart_market = st.selectbox("Market", ["India", "US"], key="market_lab_market")
    with exchange_col:
        chart_exchange = st.selectbox("Exchange", ["NSE", "BSE"] if chart_market == "India" else ["NASDAQ", "NYSE", "AMEX"], key="market_lab_exchange")
    with symbol_col:
        chart_symbol = st.text_input("Ticker symbol", placeholder="RELIANCE or MSFT", key="market_lab_symbol")
    with interval_col:
        chart_interval = st.selectbox("Candle interval", ["1d", "1wk", "5m", "15m", "1h"], key="market_lab_interval")
    chart_horizon = "intraday" if chart_interval in {"5m", "15m", "1h"} else ("long_term" if chart_interval == "1wk" else "swing")
    if st.button("Load stock chart", type="primary", key="market_lab_load"):
        if not chart_symbol.strip():
            st.warning("Enter a ticker symbol.")
        else:
            try:
                normalized = market_core._normalize_inputs(chart_market, chart_exchange, chart_symbol, chart_interval, chart_horizon)
                candles, source = market_core._provider.load_candles(*normalized[:4])
                if not candles:
                    st.warning("The data source returned no candles.")
                else:
                    st.caption(f"Source: {source} · {len(candles)} candles · latest: {candles[-1].timestamp.isoformat()}")
                    try:
                        import plotly.graph_objects as go
                    except ImportError:
                        st.error("Interactive candlestick charts need Plotly. Install project requirements with: pip install -r requirements.txt")
                    else:
                        figure = go.Figure(data=[go.Candlestick(
                            x=[c.timestamp for c in candles],
                            open=[c.open for c in candles], high=[c.high for c in candles],
                            low=[c.low for c in candles], close=[c.close for c in candles],
                            name=normalized[2],
                        )])
                        figure.update_layout(
                            title=f"{normalized[0].upper()} {normalized[1]}:{normalized[2]} · {normalized[3]}",
                            xaxis_title="Time", yaxis_title="Price", template="plotly_dark",
                            height=560, margin=dict(l=20, r=20, t=55, b=20),
                            xaxis_rangeslider_visible=False,
                        )
                        st.plotly_chart(figure, use_container_width=True)
                        with st.expander("Technical evidence and scenario analysis"):
                            st.text(market_core.analyze_stock_market(
                                normalized[2], chart_market, chart_exchange, chart_horizon, chart_interval))
            except market_core.MarketDataError as exc:
                st.error(f"Market data unavailable: {exc}")
            except Exception as exc:
                st.error(f"Could not render market data ({type(exc).__name__}).")

# --------------------------------------------------------------------------- #
# TAB 1: COMMAND FEED (HIGH DENSITY DISPATCH + INTERACTIVE STREAM)
# --------------------------------------------------------------------------- #
with tab_chat:
    # 1. SIX-CARD TACTICAL ACTION MATRIX (Always fills the page with attractive controls)
    st.markdown("""
    <div style="font-family: 'Chakra Petch', sans-serif; font-size: 0.85rem; font-weight: 800; color: #00F0FF; margin-bottom: 8px;">
        ⚡ TACTICAL DIRECTIVE LAUNCHPAD (1-CLICK EXECUTION)
    </div>
    """, unsafe_allow_html=True)

    quick_cols = st.columns(4)
    with quick_cols[0]:
        if st.button("🩺 SYSTEM DIAGNOSTIC", use_container_width=True):
            st.session_state.quick_prompt = "Run full system diagnostic: check CPU, memory, disk, and active processes."
    with quick_cols[1]:
        if st.button("🛡️ AUDIT DEV SECURITY", use_container_width=True):
            st.session_state.quick_prompt = "Perform comprehensive static security audit on modes/developer.py."
    with quick_cols[2]:
        if st.button("🌐 RECON NMAP HOST", use_container_width=True):
            st.session_state.quick_prompt = "Perform complete ethical OSINT recon on scanme.nmap.org (DNS, SSL, and ports)."
    with quick_cols[3]:
        if st.button("📈 STOCK DATA ANALYSIS", use_container_width=True):
            st.session_state.quick_prompt = (
                "Use BERU's market_data_status, then ask only for the company/stock name (unless the user already gave it). "
                "Call analyze_stock_by_name to resolve one company and fetch daily candles (plus 5-minute candles only if the configured provider supports them), or call screen_stock_watchlist to compare a user-provided list of up to 20 tickers using transparent daily technical evidence. If a name maps to multiple listings, show matches and ask which one. "
                "If market_data_status reports Alpha Vantage, explain it provides daily/weekly history here and no free intraday feed; if no provider is configured, explain CSV fallback. "
                "If the user gives an as-of date or asks for a historical forecast test, pass that date to as_of on analyze_stock_by_name or analyze_stock_market so later candles are excluded. Label historical analog frequencies as uncalibrated sample frequencies, not reliable probabilities. Give a constructive/mixed/weak setup summary and evidence, never a personalized buy/sell instruction. Do not invent current prices or participant counts."
            )

    # 2. THREE HIGH-TECH STATUS PANELS
    col_a, col_b, col_c = st.columns([1, 1, 1])

    with col_a:
        st.markdown(f"""
        <div class="hud-card" style="border-left-color: #00F0FF;">
            <div class="hud-title">
                <span>🧠 4-TIER NEURAL GATEWAY</span>
                <span style="color: #00FF66;">ALL ARMED</span>
            </div>
            <div style="font-size: 0.75rem; color: #CBD5E1; line-height: 1.6;">
                • <b>PRIMARY:</b> <span style="color: #00FF66;">ONLINE</span> ({PRIMARY_MODEL})<br>
                • <b>FALLBACK:</b> <span style="color: #00FF66;">ARMED</span> ({GEMINI_MODEL})<br>
                • <b>TERTIARY:</b> <span style="color: #38BDF8;">STANDBY</span> (OpenRouter gpt-4o-mini)<br>
                • <b>SEMANTIC REPAIR:</b> <span style="color: #FFB800;">ACTIVE</span> (Auto-recovers malformed args)
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col_b:
        live_tools_count = len(get_live_tools())
        forged_count = len(ACTIVE_FORGED_TOOLS)
        st.markdown(f"""
        <div class="hud-card" style="border-left-color: #00FF66;">
            <div class="hud-title">
                <span>🛠️ ACTIVE TOOLBELT RADAR</span>
                <span style="color: #00FF66;">{live_tools_count} LIVE</span>
            </div>
            <div style="font-size: 0.75rem; color: #CBD5E1; line-height: 1.6;">
                • <b>SYSTEM & UIA:</b> 8 Direct Windows OS Controls<br>
                • <b>DEV & TEST SUITE:</b> 9 High-Limit Dev/QA Tools<br>
                • <b>ETHICAL OSINT:</b> 4 Deep Recon Probers<br>
                • <b>AUTONOMOUS FORGE:</b> {forged_count} Self-Evolved Tools Hot-Loaded
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col_c:
        ws_files = list(WORKSPACE_DIR.glob("*"))
        trace_count = len(list(TRACES_DIR.glob("*.jsonl")))
        st.markdown(f"""
        <div class="hud-card" style="border-left-color: #A855F7;">
            <div class="hud-title">
                <span>📁 WORKSPACE REPOSITORY</span>
                <span style="color: #A855F7;">SANDBOX READY</span>
            </div>
            <div style="font-size: 0.75rem; color: #CBD5E1; line-height: 1.6;">
                • <b>STORAGE ARTIFACTS:</b> {len(ws_files)} Files in Workspace<br>
                • <b>RECORDED SESSIONS:</b> {trace_count} Audit Traces<br>
                • <b>SAFETY BOUNDARY:</b> Strict Path Isolation<br>
                • <b>GUARDIAN DAEMON:</b> Background Heartbeat Active
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 3. CHAT TRANSCRIPT FEED
    st.markdown("""
    <div style="border-top: 1px solid #1E293B; margin: 16px 0 12px 0;"></div>
    <div style="font-family: 'Chakra Petch', sans-serif; font-size: 0.9rem; font-weight: 800; color: #FFFFFF; margin-bottom: 8px;">
        // INTERACTIVE TELEMETRY & AGENT STREAM
    </div>
    """, unsafe_allow_html=True)

    if not st.session_state.messages:
        st.markdown("""
        <div style="border: 1px dashed #334155; padding: 20px; text-align: center; background: #080C14; margin-bottom: 16px;">
            <div style="color: #94A3B8; font-size: 0.85rem; font-weight: 700;">
                AWAITING OPERATIONAL DIRECTIVES. CLICK A TACTICAL CHIP ABOVE OR ENTER INSTRUCTION BELOW.
            </div>
        </div>
        """, unsafe_allow_html=True)

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            prefix = ">> [USER_PROMPT]" if msg["role"] == "user" else ">> [BERU_AGENTIC_RESPONSE]"
            st.markdown(f"**{prefix}**")
            st.markdown(msg["content"])

    # 4. CHAT INPUT DISPATCH
    target_prompt = ""
    if st.session_state.quick_prompt:
        target_prompt = st.session_state.quick_prompt
        st.session_state.quick_prompt = ""

    user_input = st.chat_input("ENTER SYSTEM INSTRUCTION (e.g. 'Build an API', 'Run security audit')...")
    final_prompt = user_input or target_prompt

    if final_prompt:
        st.session_state.messages.append({"role": "user", "content": final_prompt})
        with st.chat_message("user"):
            st.markdown(f"**>> [USER_PROMPT]**\n\n{final_prompt}")

        with st.chat_message("assistant"):
            thought_container = st.empty()
            tools_container = st.empty()

            thoughts_list = []
            tools_list = []

            def on_th(t):
                thoughts_list.append(t)
                thought_container.markdown(f"""
                <div style="border: 1px solid #FFB800; background: #0D0F17; padding: 10px 14px; margin-bottom: 10px; box-shadow: 0 0 10px rgba(255, 184, 0, 0.2);">
                    <div style="color: #FFB800; font-weight: 900; font-size: 0.75rem; font-family: 'Chakra Petch', monospace;">// COGNITIVE_REASONING</div>
                    <div style="color: #CBD5E1; font-size: 0.85rem; margin-top: 4px;">{'<br>'.join(thoughts_list[-2:])}</div>
                </div>
                """, unsafe_allow_html=True)

            def on_call(name, args):
                tools_list.append(f">> EXEC_TOOL: <b>{name}</b>({args})")
                tools_container.markdown(f"""
                <div style="border: 1px solid #00F0FF; background: #0A131F; padding: 10px 14px; margin-bottom: 10px; box-shadow: 0 0 10px rgba(0, 240, 255, 0.2);">
                    <div style="color: #00F0FF; font-weight: 900; font-size: 0.75rem; font-family: 'Chakra Petch', monospace;">// TOOL_EXECUTION_STREAM</div>
                    <div style="color: #E2E8F0; font-size: 0.8rem; font-family: monospace; margin-top: 4px;">{'<br>'.join(tools_list[-3:])}</div>
                </div>
                """, unsafe_allow_html=True)

            with st.spinner("[DISPATCHING_SOVEREIGN_AGENTIC_CYCLE...]"):
                response = run_agent(
                    final_prompt,
                    mode=st.session_state.mode,
                    history=st.session_state.messages[:-1],
                    on_thought=on_th,
                    on_tool_call=on_call,
                )

            st.markdown(f"**>> [BERU_AGENTIC_RESPONSE]**\n\n{response}")
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.rerun()

# --------------------------------------------------------------------------- #
# TAB 2: TOOL FORGE STUDIO
# --------------------------------------------------------------------------- #
with tab_forge:
    st.markdown("""
    <div class="hud-card" style="border-left-color: #00F0FF;">
        <div class="hud-title">
            <span>🛠️ AUTONOMOUS TOOL FORGE STUDIO</span>
            <span style="color: #00FF66;">LIVE HOT-LOADING ACTIVE</span>
        </div>
        <div style="font-size: 0.85rem; color: #94A3B8;">
            Synthesize, smoke-test, self-repair, and hot-load Python tools on the fly without rebooting.
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("#### [ SYNTHESIZE NEW TOOL ARTIFACT ]")
        f_name = st.text_input("IDENTIFIER (snake_case):", "generate_qr_code")
        f_desc = st.text_area("CAPABILITY DESCRIPTION:", "Generates a QR code image URL and returns access link.")
        f_code = st.text_area(
            "PYTHON IMPLEMENTATION (DEF FN):",
            """import urllib.parse
def generate_qr_code(text: str, filename: str = "qr.png") -> str:
    url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(text)}"
    return f"QR Code generated! Access at: {url}"
""",
            height=200,
        )
        if st.button("🚀 EXECUTE TOOL SYNTHESIS", use_container_width=True):
            with st.spinner("[COMPILING_AND_SMOKE_TESTING...]"):
                res = forge_new_tool(
                    name=f_name,
                    description=f_desc,
                    code=f_code,
                    parameters_schema={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                    sample_input={"text": "Beru AI AGENT"},
                )
                st.success(res)
                st.rerun()

    with col2:
        st.markdown(f"#### [ ACTIVE DYNAMIC REGISTRY ({len(ACTIVE_FORGED_TOOLS)}) ]")
        if not ACTIVE_FORGED_TOOLS:
            st.markdown("""
            <div style="border: 1px dashed #334155; padding: 24px; text-align: center; background: #0A0D15;">
                NO USER_FORGED ARTIFACTS LOADED YET. FORGE A TOOL ON THE LEFT OR LET BERU FORGE TOOLS AUTONOMOUSLY.
            </div>
            """, unsafe_allow_html=True)
        else:
            for name, fn in ACTIVE_FORGED_TOOLS.items():
                # We use the actual name as the label, and style it via Markdown
                with st.expander(f"🔧 {name.upper()}"):
                    st.markdown(f"### Tool: `{name}`")
                    st.write(fn.__doc__ or "NO DOCSTRING PROVIDED.")
                    st.code(inspect.getsource(fn) if hasattr(fn, "__code__") else "(compiled)")



# --------------------------------------------------------------------------- #
# TAB 3: DEVELOPER WORKBENCH
# --------------------------------------------------------------------------- #
with tab_dev:
    st.markdown("""
    <div class="hud-card" style="border-left-color: #38BDF8;">
        <div class="hud-title">
            <span>💻 DEVELOPER WORKBENCH & PYINSTALLER COMPILER</span>
            <span style="color: #38BDF8;">MAXIMUM POWER ACTIVE</span>
        </div>
        <div style="font-size: 0.85rem; color: #94A3B8;">
            Inspect workspace source files, run AST vulnerability scans, and compile standalone Windows binaries.
        </div>
    </div>
    """, unsafe_allow_html=True)

    dev_col1, dev_col2 = st.columns([1, 1])
    with dev_col1:
        st.markdown("#### [ WORKSPACE REPOSITORY ]")
        files = list(WORKSPACE_DIR.glob("*"))
        if files:
            for f in files:
                st.markdown(f"""
                <div style="border: 1px solid #1E293B; background: #0A0D15; padding: 8px 12px; margin-bottom: 6px; font-size: 0.85rem;">
                    📄 <b>{f.name}</b> <span style="float: right; color: #64748B;">{f.stat().st_size} BYTES</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("WORKSPACE CONTAINS ZERO ARTIFACTS.")

        st.markdown("#### [ PORTABLE BINARY BUILDER (PYINSTALLER) ]")
        script_to_compile = st.text_input("TARGET PYTHON SCRIPT:", "app.py")
        if st.button("🔨 COMPILE STANDALONE EXE", use_container_width=True):
            with st.spinner("[COMPILING_STANDALONE_BINARY...]"):
                res = compile_to_exe(script_to_compile)
                st.code(res)

    with dev_col2:
        st.markdown("#### [ STATIC AST SECURITY & QA HARNESS ]")
        target_to_audit = st.text_input("AUDIT TARGET (DIRECTORY OR FILE):", "modes")
        if st.button("🛡️ DISPATCH SECURITY AUDIT", use_container_width=True):
            with st.spinner("[PARSING_AST_NODES_AND_OWASP_RULES...]"):
                report = audit_code_security(target_to_audit)
                st.markdown(report)

# --------------------------------------------------------------------------- #
# TAB 4: HACKER RECON MATRIX
# --------------------------------------------------------------------------- #
with tab_hacker:
    st.markdown("""
    <div class="hud-card" style="border-left-color: #EF4444;">
        <div class="hud-title">
            <span>🕵️ OFFENSIVE & DEFENSIVE SECURITY RECON MATRIX</span>
            <span style="color: #EF4444;">ETHICAL OSINT SUITE</span>
        </div>
        <div style="font-size: 0.85rem; color: #94A3B8;">
            DNS enumeration via DoH, multi-threaded port & service scanner, HTTP security headers, and SSL/TLS inspector.
        </div>
    </div>
    """, unsafe_allow_html=True)

    target_host = st.text_input("TARGET HOSTNAME OR IP ADDRESS:", "scanme.nmap.org")

    h_col1, h_col2 = st.columns([1, 1])
    with h_col1:
        if st.button("🌐 DEEP DNS RECON (DoH)", use_container_width=True):
            with st.spinner("[RESOLVING_DNS_RECORDS...]"):
                st.code(deep_dns_recon(target_host))

        if st.button("🔒 AUDIT TLS CERTIFICATES", use_container_width=True):
            with st.spinner("[INTERROGATING_X509_CERTIFICATE...]"):
                st.code(inspect_ssl_certificate(target_host))

    with h_col2:
        if st.button("🔌 PROBE COMMON TCP PORTS", use_container_width=True):
            with st.spinner("[PROBING_SOCKET_VECTORS...]"):
                st.code(audit_ports_and_services(target_host))

        if st.button("🛡️ AUDIT SECURITY HEADERS", use_container_width=True):
            with st.spinner("[EVALUATING_HTTP_POLICIES...]"):
                st.code(audit_security_headers(target_host))

# --------------------------------------------------------------------------- #
# TAB 5: AUDIT LOGS & TRACES
# --------------------------------------------------------------------------- #
with tab_traces:
    st.markdown("""
    <div class="hud-card" style="border-left-color: #A855F7;">
        <div class="hud-title">
            <span>📜 TELEMETRY & EXECUTION AUDIT LOGS</span>
            <span style="color: #38BDF8;">TRANSACTION REPLAY</span>
        </div>
        <div style="font-size: 0.85rem; color: #94A3B8;">
            Inspect low-level JSONL session transcripts, tool execution timings, and reasoning tokens.
        </div>
    </div>
    """, unsafe_allow_html=True)

    trace_files = sorted(TRACES_DIR.glob("*.jsonl"), key=os.path.getmtime, reverse=True)
    if not trace_files:
        st.info("ZERO LOGGED SESSIONS IN TRACE DIRECTORY.")
    else:
        selected_trace = st.selectbox("SELECT LOGGED SESSION:", [f.name for f in trace_files])
        trace_path = TRACES_DIR / selected_trace
        lines = [json.loads(l) for l in trace_path.read_text(encoding="utf-8").splitlines() if l.strip()]

        for entry in lines:
            t_type = entry.get("type", "UNKNOWN")
            t_time = entry.get("time", "00:00:00")
            t_data = entry.get("data", {})
            
            # Use the time and type as the native label so it's always visible
            with st.expander(f"⏱️ [{t_time}] {t_type.upper()}"):
                st.json(t_data)

