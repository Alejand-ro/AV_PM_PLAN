from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import gspread
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.oauth2 import service_account

from av_common import (
    APP_NAME,
    DIVISION_COLORS,
    DIVISIONS,
    REQUIRED_COLUMNS,
    annotate_attendance_streaks,
    flags_to_text,
    metric_weights_text,
    today_monday,
    week_label,
)

st.set_page_config(page_title="AV Admin Command", page_icon="⌖", layout="wide")

COLOR_MAP = DIVISION_COLORS
STATUS_COLORS = {"Healthy": "#22c55e", "Watch": "#eab308", "Critical": "#ef4444"}

# --- GOOGLE SHEETS CONFIGURATION ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_COLUMNS = [
    "timestamp", "competition", "week_start", "division", "pm_name", "member_name",
    "role", "tasks_assigned", "hours_invested", "tasks_completed", "tasks_on_time",
    "tasks_late", "blocked_tasks", "avg_quality_1_to_5", "meetings_required",
    "meetings_attended", "pm_confidence_1_to_5", "communication_score", "notes",
    "report_id", "record_id", "created_at", "iso_year", "iso_week", "completion_score",
    "quality_score", "delivery_score", "attendance_score", "confidence_score",
    "performance_score", "performance_pct", "status", "flags",
]

PLANNED_HEADERS = ["task", "start_date", "start_offset", "duration", "end_date", "phase"]
ACTUAL_HEADERS = ["task", "actual_start_date", "actual_end_date", "percent_complete", "status", "owner", "notes", "last_updated"]

CONTENT_CAL_COLUMNS = [
    "content_id", "mission", "cycle", "month", "planned_date", "platform",
    "content_title", "description", "content_type", "owner", "status",
    "actual_posted_date", "marked_done_at", "notes", "created_at", "updated_at"
]

PLATFORM_COLORS = {
    "No post day": "#ef4444", 
    "Outreach Activity": "#f97316",
    "LinkedIn": "#eab308", 
    "Email": "#22c55e", 
    "X": "#2dd4bf",
    "TikTok": "#38bdf8", 
    "Facebook": "#c084fc", 
    "YouTube": "#f43f5e",
    "Instagram": "#d946ef", 
    "Other": "#94a3b8"
}

STATUS_SYMBOLS = {
    "Planned": "◌", 
    "In Progress": "◐", 
    "Posted": "●",
    "Missed": "⚠", 
    "Cancelled": "×", 
    "Rescheduled": "↷"
}

STATUS_CHART_COLORS = {
    "Posted": "#22c55e", "Planned": "#3b82f6", "In Progress": "#eab308",
    "Missed": "#ef4444", "Cancelled": "#94a3b8", "Rescheduled": "#a855f7"
}

# --- DYNAMIC YEARLY CYCLES ---
_cy = date.today().year
DYNAMIC_CYCLES = [
    f"{_cy-1}-{_cy}",
    f"{_cy}-{_cy+1}",
    f"{_cy+1}-{_cy+2}"
]
MONTHS_LIST = list(calendar.month_name)[1:]

def google_sheet_ready() -> tuple[bool, str]:
    missing = []
    if "gcp_service_account" not in st.secrets:
        missing.append("[gcp_service_account]")
    if not st.secrets.get("SHEET_NAME") and not st.secrets.get("SHEET_ID"):
        missing.append("SHEET_NAME or SHEET_ID")
    if missing:
        return False, "Missing Streamlit secrets: " + ", ".join(missing)
    return True, "Google Sheets connection is configured."

@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    if "gcp_service_account" not in st.secrets:
        raise RuntimeError("Missing [gcp_service_account] in Streamlit Secrets.")

    service_info = dict(st.secrets["gcp_service_account"])
    creds = service_account.Credentials.from_service_account_info(service_info, scopes=SCOPES)
    client = gspread.authorize(creds)

    sheet_id = st.secrets.get("SHEET_ID", "").strip() if st.secrets.get("SHEET_ID") else ""
    sheet_name = st.secrets.get("SHEET_NAME", "AV PM Reports Database")
    return client.open_by_key(sheet_id) if sheet_id else client.open(sheet_name)

@st.cache_data(ttl=600, show_spinner=False)
def load_reports_from_google_sheets(_client, worksheet_name, force_refresh_token=0) -> tuple[pd.DataFrame, list]:
    warnings_list = []
    try:
        worksheet = _client.worksheet(worksheet_name)
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=SHEET_COLUMNS), warnings_list
        
        df = pd.DataFrame(records)
        
        if "competition" not in df.columns:
            df["competition"] = "Mars"
        else:
            df["competition"] = df["competition"].replace(r'^\s*$', "Mars", regex=True).fillna("Mars")
            
        if "communication_score" not in df.columns:
            df["communication_score"] = 3.0
        else:
            df["communication_score"] = pd.to_numeric(df["communication_score"], errors='coerce').fillna(3.0)
            
        numeric_cols = ["performance_pct", "blocked_tasks", "tasks_completed", "avg_quality_1_to_5"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        if "week_start" in df.columns:
            df["week_start_dt"] = pd.to_datetime(df["week_start"], errors="coerce")
        else:
            df["week_start_dt"] = pd.NaT
            
        ordered = list(REQUIRED_COLUMNS) + ["week_start_dt"]
        for extra in list(SHEET_COLUMNS) + ["competition", "communication_score", "hours_invested"]:
            if extra not in ordered and extra in df.columns:
                ordered.append(extra)

        for col in ordered:
            if col not in df.columns:
                df[col] = ""

        return df[ordered], warnings_list
        
    except gspread.WorksheetNotFound:
        warnings_list.append(f"Worksheet {worksheet_name} not found.")
        return pd.DataFrame(columns=SHEET_COLUMNS), warnings_list
    except Exception as e:
        st.error(f"Error loading data from Google Sheets: {e}")
        warnings_list.append(str(e))
        return pd.DataFrame(columns=SHEET_COLUMNS), warnings_list

# --- SCHEDULE & GANTT HELPER FUNCTIONS ---
def get_schedule_tab_name(mission: str, cycle: str, kind: str) -> str:
    m = "Mars" if mission == "Mars" else "Luna"
    return f"{kind}_schedule_{m}_{cycle}"

@st.cache_data(ttl=600, show_spinner=False)
def load_schedule_sheet(_client, worksheet_name: str, required_headers: list[str], force_refresh_token=0) -> pd.DataFrame:
    try:
        ws = _client.worksheet(worksheet_name)
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=required_headers)
        
        df = pd.DataFrame(records)
        for h in required_headers:
            if h not in df.columns:
                df[h] = ""
        return df
    except gspread.WorksheetNotFound:
        return pd.DataFrame(columns=required_headers)
    except Exception as e:
        return pd.DataFrame(columns=required_headers)

def save_schedule_sheet(_client, worksheet_name: str, df: pd.DataFrame, headers: list[str]):
    try:
        ws = _client.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = _client.add_worksheet(title=worksheet_name, rows=200, cols=len(headers))
        ws.update("1:1", [headers])
    
    existing = ws.row_values(1)
    if not existing:
        ws.update("1:1", [headers])
        
    save_df = df.copy()
    
    for col in save_df.columns:
        if pd.api.types.is_datetime64_any_dtype(save_df[col]):
            save_df[col] = save_df[col].dt.strftime('%Y-%m-%d')
            
    save_df = save_df.astype(str).replace(["NaT", "nan", "None", "<NA>"], "")
    
    data = save_df[headers].values.tolist()
    ws.clear()
    ws.append_rows([headers] + data, value_input_option="USER_ENTERED")

def load_planned_schedule(mission: str, cycle: str, client, refresh_token) -> pd.DataFrame:
    sheet_name = get_schedule_tab_name(mission, cycle, "planned")
    df = load_schedule_sheet(client, sheet_name, PLANNED_HEADERS, refresh_token)
    if not df.empty:
        df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
        df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
        df = df.dropna(subset=["task", "start_date"]).sort_values("start_date")
    return df

def load_actual_schedule(mission: str, cycle: str, client, refresh_token) -> pd.DataFrame:
    sheet_name = get_schedule_tab_name(mission, cycle, "actual")
    df = load_schedule_sheet(client, sheet_name, ACTUAL_HEADERS, refresh_token)
    if not df.empty:
        df["actual_start_date"] = pd.to_datetime(df["actual_start_date"], errors="coerce")
        df["actual_end_date"] = pd.to_datetime(df["actual_end_date"], errors="coerce")
        df["percent_complete"] = pd.to_numeric(df["percent_complete"], errors="coerce").fillna(0)
    return df

def sync_actual_with_planned(planned_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    if planned_df.empty:
        return actual_df
    p_tasks = planned_df[["task"]].drop_duplicates()
    if actual_df.empty:
        df = p_tasks.copy()
        for c in ACTUAL_HEADERS:
            if c != "task":
                df[c] = ""
        return df
    
    df = pd.merge(p_tasks, actual_df, on="task", how="left")
    
    for col in ACTUAL_HEADERS:
        if col not in df.columns:
            df[col] = ""
            
    df = df.fillna("")
    return df[ACTUAL_HEADERS]

def build_plan_vs_actual_dataframe(planned_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    if planned_df.empty:
        return pd.DataFrame()
        
    if actual_df.empty:
        df = planned_df.copy()
        df["schedule_status"] = "Not Updated"
        for col in ACTUAL_HEADERS:
            if col not in df.columns and col != "task":
                df[col] = None
        df["actual_start_variance_days"] = np.nan
        df["actual_end_variance_days"] = np.nan
        return df
        
    df = pd.merge(planned_df, actual_df, on="task", how="left")
    
    for col in ACTUAL_HEADERS:
        if col not in df.columns:
            df[col] = pd.NaT if "date" in col else ""
            
    if pd.api.types.is_datetime64_any_dtype(df.get("actual_start_date")) and pd.api.types.is_datetime64_any_dtype(df.get("start_date")):
        df["actual_start_variance_days"] = (df["actual_start_date"] - df["start_date"]).dt.days
    else:
        df["actual_start_variance_days"] = np.nan
        
    if pd.api.types.is_datetime64_any_dtype(df.get("actual_end_date")) and pd.api.types.is_datetime64_any_dtype(df.get("end_date")):
        df["actual_end_variance_days"] = (df["actual_end_date"] - df["end_date"]).dt.days
    else:
        df["actual_end_variance_days"] = np.nan
    
    def calculate_status(row):
        if pd.isna(row.get("actual_start_date")):
            return "Not Updated"
            
        if pd.notna(row.get("actual_end_date")):
            if pd.notna(row.get("end_date")) and row["actual_end_date"] > row["end_date"]:
                return "Delayed"
            return "Complete"
            
        if pd.notna(row.get("end_date")):
            today = pd.Timestamp.now().normalize()
            if today > row["end_date"]:
                return "Delayed"
                
        status_override = str(row.get("status", "")).strip()
        if status_override and status_override.lower() not in ["none", "nan", ""]:
            return status_override
            
        return "In Progress"

    df["schedule_status"] = df.apply(calculate_status, axis=1)
    return df

# --- CONTENT CALENDAR HELPER FUNCTIONS ---
@st.cache_data(ttl=600, show_spinner=False)
def load_content_calendar(_client, force_refresh_token=0) -> pd.DataFrame:
    worksheet_name = "content_calendar"
    try:
        worksheet = _client.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = _client.add_worksheet(title=worksheet_name, rows=1000, cols=len(CONTENT_CAL_COLUMNS))
        worksheet.update("1:1", [CONTENT_CAL_COLUMNS])
        return pd.DataFrame(columns=CONTENT_CAL_COLUMNS)
        
    records = worksheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=CONTENT_CAL_COLUMNS)
        
    df = pd.DataFrame(records)
    for col in CONTENT_CAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
            
    df["planned_date_dt"] = pd.to_datetime(df["planned_date"], errors="coerce")
    df["actual_posted_date_dt"] = pd.to_datetime(df["actual_posted_date"], errors="coerce")
    return df

# -----------------------------------------------------------------------------
# COMPETITION STATE INITIALIZATION
# -----------------------------------------------------------------------------
if "competition" not in st.session_state:
    st.session_state.competition = "All"

competition = st.session_state.competition

# -----------------------------------------------------------------------------
# DYNAMIC THEME ENGINE
# -----------------------------------------------------------------------------
if competition == "Mars":
    bg_top = "#1e293b"
    bg_bot = "#000000"
    side_top = "#1e293b"
    side_bot = "#111827"
    panel_bg = "rgba(30, 41, 59, 0.45)"
    panel_light = "rgba(51, 65, 85, 0.35)"
    primary = "#ef4444"
    primary_hover = "#dc2626"
    primary_text = "#ffffff"
    primary_shadow = "rgba(239, 68, 68, 0.25)"
    
    logo_a_color = "#ef4444"
    logo_a_shadow = "#7f1d1d"
    logo_v_color = "#ffffff"
    logo_v_shadow = "#94a3b8"
    mode_text = "Mars Mission Command"
    
elif competition == "Luna":
    bg_top = "#334155"      
    bg_bot = "#0f172a"      
    side_top = "#334155"
    side_bot = "#1e293b"
    panel_bg = "rgba(71, 85, 105, 0.40)"    
    panel_light = "rgba(100, 116, 139, 0.30)"
    primary = "#f8fafc"     
    primary_hover = "#e2e8f0"
    primary_text = "#1e3a8a" 
    primary_shadow = "rgba(255, 255, 255, 0.20)"
    
    logo_a_color = "#f8fafc"
    logo_a_shadow = "#64748b"
    logo_v_color = "#3b82f6"
    logo_v_shadow = "#1e3a8a"
    mode_text = "Luna Mission Command"
else:
    bg_top = "#1e293b"
    bg_bot = "#000000"
    side_top = "#1e293b"
    side_bot = "#111827"
    panel_bg = "rgba(30, 41, 59, 0.45)"
    panel_light = "rgba(51, 65, 85, 0.35)"
    primary = "#3b82f6" 
    primary_hover = "#2563eb"
    primary_text = "#ffffff"
    primary_shadow = "rgba(59, 130, 246, 0.25)"
    
    logo_a_color = "#ef4444"
    logo_a_shadow = "#7f1d1d"
    logo_v_color = "#3b82f6"
    logo_v_shadow = "#1e3a8a"
    mode_text = "All Missions Command"

st.markdown(
    f"""
<style>
    :root {{
        --bg-top: {bg_top};
        --bg-bot: {bg_bot};
        --side-top: {side_top};
        --side-bot: {side_bot};
        --panel: {panel_bg};
        --panel-light: {panel_light};
        --primary: {primary};
        --primary-hover: {primary_hover};
        --primary-text: {primary_text};
        --primary-shadow: {primary_shadow};
        
        --logo-a-color: {logo_a_color};
        --logo-a-shadow: {logo_a_shadow};
        --logo-v-color: {logo_v_color};
        --logo-v-shadow: {logo_v_shadow};
        
        --ink: #f8fafc;
        --line: rgba(255, 255, 255, 0.15);
        --shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
    }}
    
    [data-testid="stAppViewContainer"],
    [data-testid="stSidebar"],
    .hero, .glass, button, button *, .av-logo .a, .av-logo .v, div[data-baseweb="tab-highlight"], 
    .stButton > button, [data-testid="stFormSubmitButton"] > button {{
        transition: all 0.7s ease-in-out !important;
    }}
    
    [data-testid="stAppViewContainer"] {{
        background: radial-gradient(circle at top, var(--bg-top) 0%, var(--bg-bot) 100%);
        background-attachment: fixed;
        color: var(--ink);
    }}
    
    [data-testid="stHeader"] {{ background: rgba(0,0,0,0); }}
    
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, var(--side-top) 0%, var(--side-bot) 100%);
        border-right: 1px solid var(--line);
        backdrop-filter: blur(28px);
        -webkit-backdrop-filter: blur(28px);
    }}
    
    .block-container {{ max-width: 1560px; padding-top: 2.5rem; padding-bottom: 4rem; }}
    
    .hero {{
        position:relative;
        overflow:hidden;
        border-radius: 24px;
        padding: 48px 52px; 
        margin-bottom: 24px; 
        background: var(--panel);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
        color: var(--ink);
    }}
    
    .av-logo-container {{ display:flex; align-items:center; gap:20px; margin-bottom: 10px;}}
    .av-logo {{ font-family: 'Arial Black', sans-serif; font-size: 72px; letter-spacing: -14px; font-style: italic; line-height: 1; user-select: none; }}
    .av-logo .a {{ color: var(--logo-a-color); text-shadow: 3px 3px 0px var(--logo-a-shadow); }}
    .av-logo .v {{ color: var(--logo-v-color); text-shadow: 3px 3px 0px var(--logo-v-shadow); mix-blend-mode: normal; }}
    
    .hero-content {{ position:relative; z-index:2; max-width: 1040px; }}
    .eyebrow {{ color:#bfdbfe; font-size:13px; letter-spacing:.18em; text-transform:uppercase; font-weight:900; }}
    
    .title {{ 
        font-size: clamp(42px, 5.5vw, 84px); 
        line-height:.90; 
        letter-spacing:-.04em; 
        font-weight:950; 
        color:white; 
        margin: 15px 0; 
        display: flex;
        align-items: center;
        gap: 20px;
        flex-wrap: wrap;
    }}
    
    .admin-title {{
        background: rgba(255, 255, 255, 0.25); 
        backdrop-filter: blur(24px); 
        -webkit-backdrop-filter: blur(24px);
        color: #ffffff;
        padding: 10px 24px; 
        border-radius: 999px; 
        font-size: 0.38em; 
        font-weight: 900;
        letter-spacing: 0.15em;
        border: 1px solid rgba(255, 255, 255, 0.50); 
        box-shadow: 0 8px 24px rgba(0,0,0,0.30), inset 0 2px 4px rgba(255,255,255,0.30); 
        text-transform: uppercase;
        display: inline-block;
        transform: translateY(-4px); 
    }}

    .subtitle {{ color:#cbd5e1; font-size:18px; line-height:1.58; max-width:940px; margin-top: 15px;}}
    
    .panel {{
        background: var(--panel);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
        color: var(--ink);
        padding: 32px 36px; 
        border-radius: 16px; 
        margin-bottom: 32px; 
    }}
    
    .kpi {{ 
        padding: 28px; 
        border-radius: 16px; 
        min-height: 160px; 
        position:relative; 
        overflow:hidden; 
        background: var(--panel-light); 
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid var(--line); 
        box-shadow: 0 8px 20px rgba(0,0,0,.20);
        margin-bottom: 24px;
    }}
    
    .kpi:before {{ content:""; position:absolute; width:170px; height:160px; right:-58px; top:-62px; background: var(--glow); border-radius:999px; filter: blur(25px); opacity:.08; }}
    
    .kpi-label {{ color:#94a3b8; font-size:12px; font-weight:900; letter-spacing:.12em; text-transform:uppercase; position:relative; z-index:2; }}
    .kpi-value {{ color:#ffffff; font-size:48px; font-weight:950; letter-spacing:-.06em; margin-top:8px; position:relative; z-index:2; }}
    .kpi-sub {{ color:#cbd5e1; font-size:14px; margin-top:6px; position:relative; z-index:2; }}
    
    div.row-widget.stRadio > div {{
        display: flex;
        flex-direction: row;
        align-items: center;
        justify-content: center;
        gap: 16px;
        background: rgba(255,255,255,0.05);
        padding: 8px 16px;
        border-radius: 100px;
        border: 1px solid var(--line);
        width: fit-content;
        margin: 0 auto;
    }}
    
    button[data-baseweb="tab"] {{
        color: #cbd5e1 !important;
        font-weight: 700 !important;
        font-size: 16px !important;
        padding: 10px 20px !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: #ffffff !important;
    }}
    div[data-baseweb="tab-highlight"] {{
        background-color: var(--primary) !important;
        height: 3px !important;
    }}

    .stButton > button {{
        background: rgba(255,255,255,0.1) !important; 
        color: #ffffff !important;
        border: 1px solid rgba(255,255,255,0.2) !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
    }}
    .stButton > button * {{ color: #ffffff !important; }}
    
    button[kind="primary"], [data-testid="stFormSubmitButton"] > button, .stDownloadButton > button {{
        background: var(--primary) !important;
        color: var(--primary-text) !important;
        box-shadow: 0 8px 20px var(--primary-shadow) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
    }}
    
    button[kind="primary"] *, [data-testid="stFormSubmitButton"] > button *, .stDownloadButton > button * {{
        color: var(--primary-text) !important;
    }}
    
    button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button:hover, .stDownloadButton > button:hover {{ 
        background: var(--primary-hover) !important; 
        transform: translateY(-1px); 
    }}
    
    h1, h2, h3, p, li {{ color: var(--ink) !important; }}
    .chart-desc {{ font-size: 14px; color: #94a3b8; margin-top: -10px; margin-bottom: 20px; border-left: 3px solid var(--primary); padding-left: 12px;}}
    
    /* Calendar Cell Styling */
    .cal-day {{
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px;
        min-height: 130px;
        padding: 8px;
        background: rgba(0,0,0,0.2);
        margin-bottom: 10px;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }}
    .cal-day.empty {{ background: transparent; border: 1px dashed rgba(255,255,255,0.05); }}
    .cal-date {{ font-weight: 800; color: #cbd5e1; font-size: 14px; margin-bottom: 4px; }}
    .cal-badge {{
        font-size: 11px;
        padding: 4px 6px;
        border-radius: 4px;
        color: #000000;
        font-weight: 700;
        line-height: 1.2;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }}
</style>
""",
    unsafe_allow_html=True,
)

def plotly_theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#f8fafc"),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(255,255,255,.10)", borderwidth=1),
        margin=dict(l=20, r=20, t=40, b=20),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,.05)", zerolinecolor="rgba(255,255,255,.10)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,.05)", zerolinecolor="rgba(255,255,255,.10)")
    return fig

def kpi_card(label: str, value: str, sub: str, glow: str) -> str:
    return f"""
    <div class="kpi" style="--glow:{glow}">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>
    """

def metric_delta_text(current: float | None, previous: float | None) -> str:
    if current is None or previous is None:
        return "No previous week comparison yet"
    delta = current - previous
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.1f} pts vs previous week"

# -----------------------------------------------------------------------------
# SIDEBAR / NAVIGATION
# -----------------------------------------------------------------------------
st.sidebar.header("⌖ Navigation")
current_page = st.sidebar.radio("Go to", ["▦ Dashboard Overview", "◷ Mission Schedule", "⌖ Gantt Management", "▦ Content Calendar"])

sheet_ok, sheet_msg = google_sheet_ready()

if "force_refresh" not in st.session_state:
    st.session_state.force_refresh = 0

with st.sidebar:
    st.divider()
    st.header("⌖ Data Sync")
    if st.button("↻ Force Refresh Google Sheets", use_container_width=True):
        st.session_state.force_refresh += 1
        st.cache_data.clear()
        st.rerun()
    if sheet_ok:
        st.caption(f"Status: {sheet_msg}")
    else:
        st.error(sheet_msg)
        st.stop()

client = get_spreadsheet()

# -----------------------------------------------------------------------------
# PAGE: GANTT MANAGEMENT
# -----------------------------------------------------------------------------
def render_gantt_charts(plan_df: pd.DataFrame, act_df: pd.DataFrame, render_mission: str):
    if plan_df.empty:
        st.info(f"ⓘ No planned schedule data found for {render_mission} Mission yet.")
        return

    st.subheader("Baseline Planned Timeline")
    fig_plan = px.timeline(plan_df, x_start="start_date", x_end="end_date", y="task", color="phase", hover_data=["task", "phase", "duration"])
    fig_plan.update_yaxes(autorange="reversed", title="")
    fig_plan.update_xaxes(title="Timeline")
    fig_plan.update_layout(height=max(300, len(plan_df) * 30))
    st.plotly_chart(plotly_theme(fig_plan), use_container_width=True)

    if not act_df.empty:
        st.divider()
        st.subheader("Plan vs. Actual Execution")
        
        merged_df = build_plan_vs_actual_dataframe(plan_df, act_df)
        
        if "percent_complete" in merged_df.columns:
            avg_pct = merged_df["percent_complete"].mean()
        else:
            avg_pct = 0
            
        st.markdown('<div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom:20px;">', unsafe_allow_html=True)
        completed = len(merged_df[merged_df["schedule_status"] == "Complete"])
        delayed = len(merged_df[merged_df["schedule_status"] == "Delayed"])
        at_risk = len(merged_df[merged_df["schedule_status"] == "At Risk"])
        not_updated = len(merged_df[merged_df["schedule_status"].isin(["Not Updated", "Not Started"])])
        
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Avg % Complete", f"{avg_pct:.1f}%")
        m2.metric("Tasks Complete", completed)
        m3.metric("Tasks Delayed", delayed)
        m4.metric("Tasks At Risk", at_risk)
        m5.metric("Tasks Missing Data", not_updated)
        st.markdown('</div>', unsafe_allow_html=True)

        plot_items = []
        for _, row in merged_df.iterrows():
            if pd.notna(row.get("start_date")) and pd.notna(row.get("end_date")):
                plot_items.append({"task": row["task"], "start": row["start_date"], "end": row["end_date"], "Type": "Planned Schedule"})
            if pd.notna(row.get("actual_start_date")) and pd.notna(row.get("actual_end_date")):
                plot_items.append({"task": row["task"], "start": row["actual_start_date"], "end": row["actual_end_date"], "Type": "Actual Execution"})
                
        if plot_items:
            overlay_df = pd.DataFrame(plot_items)
            color_map = {"Planned Schedule": "rgba(255,255,255,0.25)", "Actual Execution": primary}
            
            fig_overlay = px.timeline(overlay_df, x_start="start", x_end="end", y="task", color="Type", color_discrete_map=color_map)
            fig_overlay.update_layout(barmode="group")
            fig_overlay.update_yaxes(autorange="reversed", title="")
            fig_overlay.update_xaxes(title="Timeline Overlay")
            fig_overlay.update_layout(height=max(400, len(plan_df) * 45))
            st.plotly_chart(plotly_theme(fig_overlay), use_container_width=True)
            
        st.markdown("##### Variance Analytics Data")
        view_cols = ["task", "phase", "start_date", "end_date", "actual_start_date", "actual_end_date", "percent_complete", "schedule_status", "actual_start_variance_days", "actual_end_variance_days", "owner", "notes"]
        valid_cols = [c for c in view_cols if c in merged_df.columns]
        st.dataframe(merged_df[valid_cols], use_container_width=True, hide_index=True)


if current_page == "⌖ Gantt Management":
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-content">
            <div class="av-logo-container">
                <div class="av-logo"><span class="a">A</span><span class="v">V</span></div>
                <div>
                    <div class="eyebrow">Project AV • Timeline Administration</div>
                    <div class="title">Gantt Management</div>
                </div>
            </div>
            <div class="subtitle" style="margin-top: 10px;">
              Create and maintain Mission timelines. Actual Outcome tracking uses the Planned Baseline as its memory source.
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True
    )
    
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    gantt_mission = c1.selectbox("Target Mission", ["Mars", "Luna"])
    gantt_cycle = c2.selectbox("Yearly Cycle", DYNAMIC_CYCLES, index=1)
    gantt_mode = c3.radio("Schedule Mode", ["Planned Baseline", "Actual Outcome"])
    st.markdown('</div>', unsafe_allow_html=True)
    
    plan_df = load_planned_schedule(gantt_mission, gantt_cycle, client, st.session_state.force_refresh)
    act_df = load_actual_schedule(gantt_mission, gantt_cycle, client, st.session_state.force_refresh)
    
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    if gantt_mode == "Planned Baseline":
        st.subheader("▦ Edit Planned Baseline")
        st.markdown('<div class="chart-desc">Add or modify baseline tasks. Dates must be formatted as YYYY-MM-DD.</div>', unsafe_allow_html=True)
        edited_plan = st.data_editor(plan_df if not plan_df.empty else pd.DataFrame(columns=PLANNED_HEADERS), num_rows="dynamic", use_container_width=True, height=500)
        
        if st.button("☑ Save Planned Schedule", type="primary"):
            save_schedule_sheet(client, get_schedule_tab_name(gantt_mission, gantt_cycle, "planned"), edited_plan, PLANNED_HEADERS)
            st.success(f"ⓘ Successfully saved Planned Baseline for {gantt_mission} ({gantt_cycle}).")
            st.cache_data.clear()
            st.rerun()
            
        st.divider()
        render_gantt_charts(edited_plan, act_df, gantt_mission)
            
    else:
        st.subheader("▦ Edit Actual Outcome")
        if plan_df.empty:
            st.warning("⚠ Create the planned baseline first. Actual outcome tracking uses the planned task list as its source.")
        else:
            st.markdown('<div class="chart-desc">Log actual progress against the baseline. Task names are locked to the planned schedule.</div>', unsafe_allow_html=True)
            
            if st.button("↻ Sync Tasks from Planned Baseline"):
                act_df = sync_actual_with_planned(plan_df, act_df)
                st.info("ⓘ Synced missing tasks. Review below and save.")
                
            edited_act = st.data_editor(act_df if not act_df.empty else sync_actual_with_planned(plan_df, act_df), disabled=["task"], use_container_width=True, height=500)
            
            if st.button("☑ Save Actual Outcome", type="primary"):
                save_schedule_sheet(client, get_schedule_tab_name(gantt_mission, gantt_cycle, "actual"), edited_act, ACTUAL_HEADERS)
                st.success(f"ⓘ Successfully saved Actual Outcome for {gantt_mission} ({gantt_cycle}).")
                st.cache_data.clear()
                st.rerun()
                
            st.divider()
            render_gantt_charts(plan_df, edited_act, gantt_mission)
            
    st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# PAGE: MISSION SCHEDULE SUMMARY
# -----------------------------------------------------------------------------
elif current_page == "◷ Mission Schedule":
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-content">
            <div class="av-logo-container">
                <div class="av-logo"><span class="a">A</span><span class="v">V</span></div>
                <div>
                    <div class="eyebrow">Project AV • {mode_text}</div>
                    <div class="title">Mission Schedule</div>
                </div>
            </div>
            <div class="subtitle" style="margin-top: 10px;">
              Live timeline comparison of planned execution vs actual recorded progress across active yearly cycles.
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True
    )
    
    st.markdown('<div style="display: flex; justify-content: center; margin-bottom: 20px;">', unsafe_allow_html=True)
    comp_choice = st.radio(
        "Mission Toggle",
        options=["All Missions", "Mars Mission", "Luna Mission"],
        index=0 if competition == "All" else (1 if competition == "Mars" else 2),
        horizontal=True,
        label_visibility="collapsed",
        key="comp_radio_selector"
    )
    st.markdown('</div>', unsafe_allow_html=True)

    new_comp = "All" if comp_choice == "All Missions" else ("Mars" if comp_choice == "Mars Mission" else "Luna")
    if new_comp != st.session_state.competition:
        st.session_state.competition = new_comp
        st.rerun()
        
    st.markdown('<div class="panel" style="padding: 15px 36px; margin-bottom: 24px;">', unsafe_allow_html=True)
    cycle_choice = st.selectbox("Active Yearly Cycle", DYNAMIC_CYCLES, index=1)
    st.markdown('</div>', unsafe_allow_html=True)
    
    def render_schedule_panel(render_mission: str, cycle: str, db_client, r_token):
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown(f"<h2>◈ {render_mission} Mission Tracker ({cycle})</h2>", unsafe_allow_html=True)
        plan_df = load_planned_schedule(render_mission, cycle, db_client, r_token)
        act_df = load_actual_schedule(render_mission, cycle, db_client, r_token)
        render_gantt_charts(plan_df, act_df, render_mission)
        st.markdown('</div>', unsafe_allow_html=True)

    if competition == "All":
        render_schedule_panel("Mars", cycle_choice, client, st.session_state.force_refresh)
        render_schedule_panel("Luna", cycle_choice, client, st.session_state.force_refresh)
    else:
        render_schedule_panel(competition, cycle_choice, client, st.session_state.force_refresh)

# -----------------------------------------------------------------------------
# PAGE: CONTENT CALENDAR
# -----------------------------------------------------------------------------
elif current_page == "▦ Content Calendar":
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-content">
            <div class="av-logo-container">
                <div class="av-logo"><span class="a">A</span><span class="v">V</span></div>
                <div>
                    <div class="eyebrow">Project AV • Analytics</div>
                    <div class="title">Content Calendar Command</div>
                </div>
            </div>
            <div class="subtitle" style="margin-top: 10px;">
              Track planned outreach against actual execution across missions, platforms, and monthly cycles.
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    
    cal_df = load_content_calendar(client, st.session_state.force_refresh)
    
    # Filters
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    
    default_mission_idx = 0
    if competition == "Mars": default_mission_idx = 1
    elif competition == "Luna": default_mission_idx = 2
    cal_mission = c1.selectbox("Mission Filter", ["All", "Mars", "Luna", "General"], index=default_mission_idx)
    
    cal_cycle = c2.selectbox("Cycle Filter", ["All"] + DYNAMIC_CYCLES, index=0)
    
    # Intelligently default the month and year so the calendar shows up immediately!
    current_month_name = calendar.month_name[date.today().month]
    month_opts = ["All"] + MONTHS_LIST
    default_month_idx = month_opts.index(current_month_name) if current_month_name in month_opts else 0
    
    cal_month = c3.selectbox("Month Filter", month_opts, index=default_month_idx)
    
    c4, c5, c6 = st.columns(3)
    year_opts = ["All", _cy - 1, _cy, _cy + 1, _cy + 2]
    default_year_idx = year_opts.index(_cy) if _cy in year_opts else 0
    
    cal_year = c4.selectbox("Year Filter", year_opts, index=default_year_idx)
    cal_platform = c5.selectbox("Platform Filter", ["All"] + list(PLATFORM_COLORS.keys()), index=0)
    cal_status = c6.selectbox("Status Filter", ["All"] + list(STATUS_SYMBOLS.keys()), index=0)
    st.markdown('</div>', unsafe_allow_html=True)

    if cal_df.empty:
        st.info("ⓘ No content calendar data found yet. Add planned content from the PM app.")
        st.stop()

    filtered_cal = cal_df.copy()
    if cal_mission != "All": filtered_cal = filtered_cal[filtered_cal["mission"] == cal_mission]
    if cal_cycle != "All": filtered_cal = filtered_cal[filtered_cal["cycle"] == cal_cycle]
    if cal_month != "All": filtered_cal = filtered_cal[filtered_cal["month"] == cal_month]
    if cal_year != "All": filtered_cal = filtered_cal[filtered_cal["planned_date_dt"].dt.year == int(cal_year)]
    if cal_platform != "All": filtered_cal = filtered_cal[filtered_cal["platform"] == cal_platform]
    if cal_status != "All": filtered_cal = filtered_cal[filtered_cal["status"] == cal_status]

    if filtered_cal.empty:
        st.warning("⚠ No content matches the selected filters.")
        st.stop()

    # Variance and KPIs
    filtered_cal["posting_variance_days"] = (filtered_cal["actual_posted_date_dt"] - filtered_cal["planned_date_dt"]).dt.days
    
    # Exclude truly blank padding rows
    valid_items = filtered_cal[filtered_cal["platform"] != ""]
    # Exclude No post day from requirement counts
    req_items = valid_items[valid_items["platform"] != "No post day"]
    
    planned_count = len(req_items)
    posted_items = req_items[(req_items["status"] == "Posted") | pd.notna(req_items["actual_posted_date_dt"])]
    posted_count = len(posted_items)
    pending_count = len(req_items[req_items["status"].isin(["Planned", "In Progress", "Rescheduled"]) & pd.isna(req_items["actual_posted_date_dt"])])
    missed_count = len(req_items[req_items["status"] == "Missed"])
    
    late_count = len(posted_items[posted_items["posting_variance_days"] > 0])
    ontime_count = len(posted_items[posted_items["posting_variance_days"] <= 0])
    
    comp_rate = (posted_count / planned_count * 100) if planned_count > 0 else 0

    st.markdown('<div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:24px;">', unsafe_allow_html=True)
    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric("Completion Rate", f"{comp_rate:.1f}%")
    m2.metric("Planned Items", planned_count)
    m3.metric("Posted", posted_count)
    m4.metric("Pending", pending_count)
    m5.metric("Missed", missed_count)
    m6.metric("Late", late_count)
    m7.metric("On-Time", ontime_count)
    st.markdown('</div>', unsafe_allow_html=True)

    # Monthly Calendar Preview
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    if cal_month != "All" and cal_year != "All":
        st.markdown(f"### ◫ {cal_month} {cal_year} Preview")
        month_idx = MONTHS_LIST.index(cal_month) + 1
        cal_grid = calendar.monthcalendar(int(cal_year), month_idx)
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        
        cols = st.columns(7)
        for i, d_name in enumerate(day_names):
            cols[i].markdown(f"<div style='text-align:center; color:#94a3b8; font-weight:800; font-size:14px; margin-bottom:8px;'>{d_name}</div>", unsafe_allow_html=True)
            
        for week in cal_grid:
            cols = st.columns(7)
            for i, day in enumerate(week):
                if day == 0:
                    cols[i].markdown("<div class='cal-day empty'></div>", unsafe_allow_html=True)
                else:
                    date_str = f"{cal_year}-{month_idx:02d}-{day:02d}"
                    day_items = valid_items[valid_items["planned_date"] == date_str]
                    
                    content_html = ""
                    for _, item in day_items.iterrows():
                        platform = item.get("platform", "Other")
                        title = item.get("content_title", "Untitled")
                        status = item.get("status", "Planned")
                        bg_color = PLATFORM_COLORS.get(platform, "#94a3b8")
                        symbol = STATUS_SYMBOLS.get(status, "◌")
                        content_html += f"<div class='cal-badge' style='background:{bg_color};' title='{title}'>{symbol} {platform}</div>"
                        
                    opacity = "0.5" if i >= 5 else "1.0"
                    cols[i].markdown(f"""
                    <div class='cal-day' style='opacity: {opacity};'>
                        <div class='cal-date'>{day}</div>
                        {content_html}
                    </div>
                    """, unsafe_allow_html=True)
    else:
        st.info("ⓘ Select a specific Month and Year in the filters above to view the visual calendar layout.")
    st.markdown('</div>', unsafe_allow_html=True)

    r1, r2 = st.columns([1.5, 1])
    with r1:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.subheader("Plan vs. Actual Execution")
        st.markdown('<div class="chart-desc">Tracks planned content dates against actual execution delivery.</div>', unsafe_allow_html=True)
        
        if not req_items.empty:
            planned_counts = req_items.dropna(subset=["planned_date_dt"]).groupby(req_items["planned_date_dt"].dt.date).size().reset_index(name="Planned")
            planned_counts.rename(columns={"planned_date_dt": "Date"}, inplace=True)
            
            actual_counts = req_items.dropna(subset=["actual_posted_date_dt"]).groupby(req_items["actual_posted_date_dt"].dt.date).size().reset_index(name="Posted")
            actual_counts.rename(columns={"actual_posted_date_dt": "Date"}, inplace=True)
            
            merged_counts = pd.merge(planned_counts, actual_counts, on="Date", how="outer").fillna(0).sort_values("Date")
            
            fig_pva = go.Figure()
            fig_pva.add_trace(go.Bar(x=merged_counts["Date"], y=merged_counts["Planned"], name="Planned", marker_color="rgba(255,255,255,0.2)"))
            fig_pva.add_trace(go.Scatter(x=merged_counts["Date"], y=merged_counts["Posted"], name="Actual Posted", mode="lines+markers", line=dict(color=primary, width=3), marker=dict(size=8)))
            st.plotly_chart(plotly_theme(fig_pva), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with r2:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.subheader("Platform Breakdown")
        st.markdown('<div class="chart-desc">Distribution of scheduled content platforms.</div>', unsafe_allow_html=True)
        if not req_items.empty:
            plat_counts = req_items["platform"].value_counts().reset_index()
            plat_counts.columns = ["Platform", "Count"]
            fig_plat = px.pie(plat_counts, values="Count", names="Platform", color="Platform", color_discrete_map=PLATFORM_COLORS, hole=0.4)
            st.plotly_chart(plotly_theme(fig_plat), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    r3, r4 = st.columns([1, 1])
    with r3:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.subheader("Status Breakdown")
        if not req_items.empty:
            stat_counts = req_items["status"].value_counts().reset_index()
            stat_counts.columns = ["Status", "Count"]
            fig_stat = px.bar(stat_counts, x="Status", y="Count", color="Status", color_discrete_map=STATUS_CHART_COLORS)
            st.plotly_chart(plotly_theme(fig_stat), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
    with r4:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.subheader("Late/Early Analysis")
        st.markdown('<div class="chart-desc">Negative values indicate early execution. Positive values indicate late execution.</div>', unsafe_allow_html=True)
        variance_view = req_items.dropna(subset=["posting_variance_days"]).copy()
        if not variance_view.empty:
            variance_view = variance_view[["mission", "platform", "planned_date", "actual_posted_date", "posting_variance_days", "status"]]
            st.dataframe(variance_view.sort_values("posting_variance_days", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.info("ⓘ No executed items with variance to display.")
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("▦ Content Execution Table")
    
    top_platforms = req_items["platform"].value_counts().head(2).index.tolist()
    plat_str = " and ".join(top_platforms) if top_platforms else "Various platforms"
    summary_text = f"**Executive Summary:** For the selected filters, there were {planned_count} planned content items, with {posted_count} successfully posted and {missed_count} missed. "
    if late_count > 0:
        summary_text += f"There were {late_count} late posts. "
    summary_text += f"{plat_str} had the highest planned volume. The overall completion rate stands at {comp_rate:.1f}%."
    st.markdown(summary_text)
    
    st.markdown("<br>", unsafe_allow_html=True)
    view_cols = ["mission", "cycle", "month", "planned_date", "platform", "content_title", "description", "content_type", "owner", "status", "actual_posted_date", "posting_variance_days", "notes"]
    final_view = valid_items[view_cols].sort_values(["planned_date"], ascending=False)
    st.dataframe(final_view, use_container_width=True, hide_index=True)
    
    st.download_button(
        "⬇ Export Content Matrix to CSV",
        data=final_view.to_csv(index=False).encode("utf-8"),
        file_name=f"content_calendar_export_{date.today().isoformat()}.csv",
        mime="text/csv",
        use_container_width=True,
        type="primary"
    )
    st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# PAGE: DASHBOARD OVERVIEW
# -----------------------------------------------------------------------------
elif current_page == "▦ Dashboard Overview":
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-content">
            <div class="av-logo-container">
                <div class="av-logo"><span class="a">A</span><span class="v">V</span></div>
                <div class="eyebrow" style="margin-top: 15px;">Executive Level Operations</div>
            </div>
            <div class="title">Performance <span class="admin-title">{mode_text}</span></div>
            <div class="subtitle">
              Comprehensive analytical breakdown of division trends, execution bottlenecks, communication gaps, and workforce health. 
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div style="display: flex; justify-content: center; margin-bottom: 32px;">', unsafe_allow_html=True)
    comp_choice = st.radio(
        "Mission Toggle",
        options=["All Missions", "Mars Mission", "Luna Mission"],
        index=0 if competition == "All" else (1 if competition == "Mars" else 2),
        horizontal=True,
        label_visibility="collapsed",
        key="comp_radio_selector"
    )
    st.markdown('</div>', unsafe_allow_html=True)

    new_comp = "All" if comp_choice == "All Missions" else ("Mars" if comp_choice == "Mars Mission" else "Luna")
    if new_comp != st.session_state.competition:
        st.session_state.competition = new_comp
        st.rerun()

    worksheet_name = st.secrets.get("WORKSHEET_NAME", "reports")
    raw_df, warnings = load_reports_from_google_sheets(get_spreadsheet(), worksheet_name, force_refresh_token=st.session_state.force_refresh)

    if not raw_df.empty:
        if "week_start_dt" not in raw_df.columns:
            raw_df["week_start_dt"] = pd.to_datetime(raw_df.get("week_start", ""), errors="coerce")
        if "division" not in raw_df.columns:
            raw_df["division"] = ""
        if "member_name" not in raw_df.columns:
            raw_df["member_name"] = ""

    df = annotate_attendance_streaks(raw_df)

    if competition != "All":
        df = df[df["competition"] == competition]

    if competition == "Luna":
        luna_allowed = ["electrical", "vehicle", "software"]
        available_divisions = [d for d in DIVISIONS if any(k in d.lower() for k in luna_allowed)]
        if not available_divisions:
            available_divisions = ["Power and Electrical Systems", "Vehicle Design & Structures", "Software & Hardware"]
    elif competition == "Mars" or competition == "All":
        available_divisions = DIVISIONS

    available_weeks = sorted([w for w in df["week_start"].dropna().unique().tolist() if w])

    with st.sidebar:
        st.divider()
        st.header("⌖ Division Toggle")
        st.caption("Isolate specific teams in the analytics")
        selected_divs = st.multiselect("Active Divisions", options=available_divisions, default=available_divisions)

    st.markdown('<div class="panel" style="padding: 15px 36px; margin-bottom: 24px;">', unsafe_allow_html=True)
    selected_weeks = st.multiselect("Timeline Filter (Affects entire dashboard)", options=available_weeks, default=available_weeks[-6:] if len(available_weeks) > 6 else available_weeks, format_func=week_label)
    st.markdown('</div>', unsafe_allow_html=True)

    filtered = df[
        (df["week_start"].isin(selected_weeks) if selected_weeks else True) &
        (df["division"].isin(selected_divs) if selected_divs else True)
    ].copy()

    current_week_str = max(filtered["week_start"].dropna()) if not filtered.empty else None
    current_df = filtered[filtered["week_start"] == current_week_str] if current_week_str else filtered
    previous_weeks = sorted([w for w in filtered["week_start"].unique().tolist() if current_week_str and w < current_week_str])
    prev_df = filtered[filtered["week_start"] == previous_weeks[-1]] if previous_weeks else pd.DataFrame(columns=filtered.columns)

    org_avg = float(current_df["performance_pct"].mean()) if not current_df.empty else None
    prev_avg = float(prev_df["performance_pct"].mean()) if not prev_df.empty else None
    risk_count = int(current_df["status"].isin(["Critical", "Watch"]).sum()) if not current_df.empty else 0
    blockers = int(current_df["blocked_tasks"].sum()) if not current_df.empty else 0
    attendance_flags = int((current_df["attendance_risk_streak"] >= 2).sum()) if not current_df.empty else 0

    k1, k2, k3, k4 = st.columns(4)
    with k1: st.markdown(kpi_card("Current Filter Average", f"{org_avg:.1f}%" if org_avg is not None else "—", metric_delta_text(org_avg, prev_avg), primary), unsafe_allow_html=True)
    with k2: st.markdown(kpi_card("At-Risk Members", str(risk_count), "Watch + Critical statuses", "#ef4444"), unsafe_allow_html=True)
    with k3: st.markdown(kpi_card("Active Blockers", str(blockers), "Total tasks currently blocked", "#ffffff"), unsafe_allow_html=True)
    with k4: st.markdown(kpi_card("Attendance Risks", str(attendance_flags), "Consecutive absence streaks", "#3b82f6"), unsafe_allow_html=True)

    st.markdown('<br>', unsafe_allow_html=True)

    if competition == "All":
        tab_exec, tab_action = st.tabs([
            "◈ Executive Overview", 
            "⚠ Action Center"
        ])
        tab_div = None
        tab_ops = None
    else:
        tab_exec, tab_div, tab_ops, tab_action = st.tabs([
            "◈ Executive Overview", 
            "⊙ Division Intelligence", 
            "⌁ Bottlenecks & Health", 
            "⚠ Action Center"
        ])

    with tab_exec:
        st.markdown('<br>', unsafe_allow_html=True)
        if filtered.empty:
            st.info(f"ⓘ No performance data currently logged for {competition} Mission under these filters.")
        else:
            r1c1, r1c2 = st.columns([1.5, 1])
            
            with r1c1:
                st.markdown('<div class="panel">', unsafe_allow_html=True)
                st.subheader("Historical Trajectory by Division")
                st.markdown('<div class="chart-desc">Tracks overall performance percentage of filtered divisions over time.</div>', unsafe_allow_html=True)
                weekly_div = filtered.groupby(["week_start", "division"], as_index=False)["performance_pct"].mean()
                fig1 = px.line(weekly_div, x="week_start", y="performance_pct", color="division", markers=True, color_discrete_map=COLOR_MAP)
                fig1.update_traces(line=dict(width=3), marker=dict(size=8))
                fig1.update_yaxes(range=[0, 100], title="Performance %")
                fig1.update_xaxes(title="Week")
                st.plotly_chart(plotly_theme(fig1), use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
            with r1c2:
                st.markdown('<div class="panel">', unsafe_allow_html=True)
                st.subheader("Operational Balance")
                st.markdown('<div class="chart-desc">Holistic view of current operational capability for selected filters.</div>', unsafe_allow_html=True)
                if not current_df.empty:
                    categories = ['Completion', 'Quality', 'Delivery', 'Attendance', 'Confidence']
                    org_means = current_df[["completion_score", "quality_score", "delivery_score", "attendance_score", "confidence_score"]].mean() * 20
                    org_means_list = org_means.tolist()
                    org_means_list.append(org_means_list[0])
                    categories_loop = categories + [categories[0]]
                    
                    radar_fill = primary_shadow if competition == "All" else primary_shadow
                    radar_line = primary
                    
                    fig5 = go.Figure()
                    fig5.add_trace(go.Scatterpolar(
                        r=org_means_list, theta=categories_loop, fill='toself',
                        fillcolor=radar_fill, line=dict(color=radar_line, width=2), name='Filter Average'
                    ))
                    fig5.update_layout(
                        polar=dict(radialaxis=dict(visible=True, range=[0, 100], gridcolor="rgba(255,255,255,0.1)")),
                        showlegend=False, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        margin=dict(t=20, b=20, l=20, r=20)
                    )
                    st.plotly_chart(fig5, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
            if competition == "All":
                st.markdown('<div class="panel">', unsafe_allow_html=True)
                st.subheader("Mission Performance Comparison")
                st.markdown('<div class="chart-desc">Direct comparison of operational health across active competition programs.</div>', unsafe_allow_html=True)
                comp_summary = filtered.groupby(["week_start", "competition"], as_index=False)["performance_pct"].mean()
                comp_colors = {"Mars": "#ef4444", "Luna": "#f8fafc"}
                fig_comp = px.bar(comp_summary, x="week_start", y="performance_pct", color="competition", barmode="group", color_discrete_map=comp_colors)
                fig_comp.update_yaxes(range=[0, 100], title="Avg Performance %")
                fig_comp.update_xaxes(title="Week")
                fig_comp.update_traces(marker_line_color='rgba(255,255,255,0.2)', marker_line_width=1.5)
                st.plotly_chart(plotly_theme(fig_comp), use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)

    if tab_div is not None:
        with tab_div:
            st.markdown('<br>', unsafe_allow_html=True)
            if current_df.empty:
                st.info(f"ⓘ No performance data currently logged for {competition} Mission under these filters.")
            else:
                st.markdown('<div class="panel">', unsafe_allow_html=True)
                st.subheader("Performance Variance (Consistency)")
                st.markdown('<div class="chart-desc">A tall box means highly inconsistent team performance. A short box means uniform performance. Outlier dots represent specific over/under-performers.</div>', unsafe_allow_html=True)
                fig3 = px.box(current_df, x="division", y="performance_pct", color="division", color_discrete_map=COLOR_MAP, points="all")
                fig3.update_yaxes(range=[0, 105], title="Individual Performance %")
                fig3.update_xaxes(title="")
                fig3.update_layout(showlegend=False, height=350)
                st.plotly_chart(plotly_theme(fig3), use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
        
                st.markdown("### Metric Weakness by Division")
                st.markdown('<div class="chart-desc" style="margin-left: 0;">Heatmaps explicitly styled to match each division\'s brand color. Darker/brighter blocks show which specific metric is currently excelling or dragging the team down.</div>', unsafe_allow_html=True)
                
                cols = st.columns(len(selected_divs))
                
                if not current_df.empty:
                    heat_df = current_df.groupby("division")[["completion_score", "quality_score", "delivery_score", "attendance_score", "confidence_score"]].mean() * 20
                else:
                    heat_df = pd.DataFrame()
                    
                for idx, div_name in enumerate(selected_divs):
                    with cols[idx]:
                        st.markdown(f'<div class="panel" style="padding: 20px; text-align: center;">', unsafe_allow_html=True)
                        st.markdown(f"<h4 style='color: {COLOR_MAP.get(div_name, '#ffffff')}; margin-bottom: 10px;'>{div_name}</h4>", unsafe_allow_html=True)
                        
                        if div_name in heat_df.index and not heat_df.loc[[div_name]].isna().all().all():
                            div_data = heat_df.loc[[div_name]].T
                            div_data.columns = ["Score"]
                            
                            div_color = COLOR_MAP.get(div_name, "#ffffff")
                            custom_scale = [[0.0, "rgba(0,0,0,0)"], [1.0, div_color]]
                            
                            fig_heat = px.imshow(
                                div_data, 
                                text_auto=".1f", 
                                aspect="auto", 
                                color_continuous_scale=custom_scale, 
                                zmin=0, zmax=100
                            )
                            fig_heat.update_layout(
                                coloraxis_showscale=False, 
                                margin=dict(t=10, b=10, l=10, r=10),
                                height=300,
                                plot_bgcolor="rgba(0,0,0,0)",
                                paper_bgcolor="rgba(0,0,0,0)"
                            )
                            fig_heat.update_xaxes(visible=False)
                            st.plotly_chart(plotly_theme(fig_heat), use_container_width=True)
                        else:
                            st.markdown("<div style='height: 300px; display: flex; align-items: center; justify-content: center; color: rgba(255,255,255,0.2); font-size: 14px; font-weight: bold; border: 1px dashed rgba(255,255,255,0.1); border-radius: 12px;'>NO DATA SUBMITTED YET</div>", unsafe_allow_html=True)
                        
                        st.markdown('</div>', unsafe_allow_html=True)

    if tab_ops is not None:
        with tab_ops:
            st.markdown('<br>', unsafe_allow_html=True)
            if current_df.empty:
                st.info(f"ⓘ No performance data currently logged for {competition} Mission under these filters.")
            else:
                r3c1, r3c2 = st.columns([1, 1.2])
                
                with r3c1:
                    st.markdown('<div class="panel">', unsafe_allow_html=True)
                    st.subheader("Blockers vs. Performance Impact")
                    st.markdown('<div class="chart-desc">Analyzes if external blockers are the root cause of poor performance. Size of the dot equals communication score.</div>', unsafe_allow_html=True)
                    
                    scatter_df = current_df.copy()
                    scatter_df["blocked_jitter"] = scatter_df["blocked_tasks"] + np.random.uniform(-0.15, 0.15, size=len(scatter_df))
                    
                    fig4 = px.scatter(
                        scatter_df, x="blocked_jitter", y="performance_pct", color="division", 
                        size="communication_score", hover_data=["member_name", "blocked_tasks", "communication_score"],
                        color_discrete_map=COLOR_MAP
                    )
                    fig4.update_yaxes(range=[0, 105], title="Performance %")
                    fig4.update_xaxes(title="Count of Blocked Tasks (Slight jitter for visibility)", tickvals=[0,1,2,3,4,5])
                    fig4.update_layout(height=450)
                    st.plotly_chart(plotly_theme(fig4), use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
                    
                with r3c2:
                    st.markdown('<div class="panel">', unsafe_allow_html=True)
                    st.subheader("Workforce Status Topology")
                    st.markdown('<div class="chart-desc">Hierarchical view: Divisions → Roles → Statuses. Click into a block to zoom. Colors represent status severity.</div>', unsafe_allow_html=True)
                    
                    if not current_df.empty:
                        tree_df = current_df.copy()
                        status_map = {"Healthy": 1, "Watch": 2, "Critical": 3}
                        tree_df["status_num"] = tree_df["status"].map(status_map)
                        tree_df["count"] = 1
                        
                        fig6 = px.treemap(
                            tree_df, path=[px.Constant("Organization"), "division", "role", "status"], 
                            values="count", color="status_num", color_continuous_scale=["#22c55e", "#eab308", "#ef4444"],
                            hover_data=["member_name"]
                        )
                        fig6.update_layout(coloraxis_showscale=False, margin=dict(t=10, l=10, r=10, b=10), height=450)
                        st.plotly_chart(plotly_theme(fig6), use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)

    with tab_action:
        st.markdown('<br>', unsafe_allow_html=True)
        if filtered.empty:
            st.info(f"ⓘ No performance data currently logged for {competition} Mission under these filters.")
        else:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.subheader("⚠ Executive Intervention Required")
            st.markdown('<div class="chart-desc">Auto-filtered list of personnel who are in Critical/Watch status, have open blockers, or are flagging for consecutive absences.</div>', unsafe_allow_html=True)
        
            risk_df = current_df[
                current_df["status"].isin(["Critical", "Watch"])
                | (current_df["blocked_tasks"] > 0)
                | (current_df["attendance_risk_streak"] >= 2)
            ].copy()
        
            if risk_df.empty:
                st.success("ⓘ No current personnel risks detected under the selected filters. Operations are nominal.")
            else:
                risk_df["flags_text"] = risk_df["flags"].apply(flags_to_text)
                risk_df = risk_df.sort_values(["status", "performance_pct"], ascending=[False, True])
                
                st.dataframe(
                    risk_df[[
                        "competition", "division", "member_name", "role", "performance_pct", "status", "blocked_tasks",
                        "attendance_risk_streak", "communication_score", "flags_text", "notes"
                    ]],
                    use_container_width=True, hide_index=True,
                )
            st.markdown('</div>', unsafe_allow_html=True)
        
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.subheader("▦ Complete Data Matrix")
            st.markdown('<div class="chart-desc">The unfiltered, raw Google Sheets data flattened into a tabular matrix for external export or auditing.</div>', unsafe_allow_html=True)
        
            raw_view = filtered.copy()
            raw_view["flags"] = raw_view["flags"].apply(flags_to_text)
            
            if competition == "All":
                raw_view = raw_view.sort_values(["week_start", "competition", "division", "member_name"], ascending=[False, True, True, True])
            else:
                raw_view = raw_view.sort_values(["competition", "week_start", "division", "member_name"], ascending=[True, False, True, True])
        
            st.dataframe(raw_view, use_container_width=True, hide_index=True)
        
            st.download_button(
                "⬇ Export Matrix to CSV",
                data=raw_view.to_csv(index=False).encode("utf-8"),
                file_name=f"av_admin_export_{date.today().isoformat()}.csv",
                mime="text/csv",
                use_container_width=True,
                type="primary"
            )
            st.markdown('</div>', unsafe_allow_html=True)
