from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import gspread
import pandas as pd
import streamlit as st
from google.oauth2 import service_account

from av_common import (
    APP_NAME,
    DIVISION_COLORS,
    DIVISIONS,
    METRIC_WEIGHTS,
    OUTBOX_DIR,
    division_color,
    empty_input_rows,
    flags_to_text,
    make_report,
    metric_weights_text,
    save_report,
    today_monday,
)

# --- DRAFT CONFIGURATION ---
APP_DIR = Path(__file__).resolve().parent
DRAFTS_DIR = APP_DIR / "reports_drafts"
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

def safe_key_part(value) -> str:
    return str(value or "").strip().lower()

def get_draft_path(competition, pm, div, date_val):
    safe_comp = safe_key_part(competition)
    safe_pm = safe_key_part(pm).replace(" ", "_") or "blank_pm"
    safe_div = safe_key_part(div).replace(" ", "_") or "blank_division"
    return DRAFTS_DIR / f"draft_{safe_comp}_{date_val}_{safe_div}_{safe_pm}.json"

def cloud_draft_key(competition: str, pm_name: str, division: str, week_start) -> str:
    return "|".join([safe_key_part(competition), str(week_start), safe_key_part(division), safe_key_part(pm_name)])

def monday_for(any_date):
    if hasattr(any_date, "date"):
        any_date = any_date.date()
    return any_date - timedelta(days=any_date.weekday())

def week_range_label(monday_date) -> str:
    friday = monday_date + timedelta(days=4)
    if monday_date.year == friday.year:
        return f"{monday_date:%b %d} – {friday:%b %d, %Y}"
    return f"{monday_date:%b %d, %Y} – {friday:%b %d, %Y}"

def build_week_options(center_monday, weeks_back: int = 12, weeks_forward: int = 8):
    return [center_monday + timedelta(weeks=i) for i in range(-weeks_back, weeks_forward + 1)]


# --- GOOGLE SHEETS CONFIGURATION ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_COLUMNS = [
    "timestamp",
    "competition", 
    "week_start",
    "division",
    "pm_name",
    "member_name",
    "role",
    "tasks_assigned",
    "hours_invested",
    "tasks_completed",
    "tasks_on_time",
    "tasks_late",
    "blocked_tasks",
    "avg_quality_1_to_5",
    "meetings_required",
    "meetings_attended",
    "pm_confidence_1_to_5",
    "communication_score",
    "notes",
    "report_id",
    "record_id",
    "created_at",
    "iso_year",
    "iso_week",
    "completion_score",
    "quality_score",
    "delivery_score",
    "attendance_score",
    "confidence_score",
    "performance_score",
    "performance_pct",
    "status",
    "flags",
]

DRAFT_COLUMNS = [
    "draft_key",
    "competition", 
    "week_start",
    "week_end",
    "division",
    "pm_name",
    "updated_at",
    "draft_json",
]


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


def get_or_create_worksheet(title: str, columns: list[str], rows: int = 1000):
    spreadsheet = get_spreadsheet()
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=len(columns) + 5)
    ensure_headers(worksheet, columns)
    return worksheet


@st.cache_resource(show_spinner=False)
def get_worksheet():
    worksheet_name = st.secrets.get("WORKSHEET_NAME", "reports")
    return get_or_create_worksheet(worksheet_name, SHEET_COLUMNS, rows=2000)


@st.cache_resource(show_spinner=False)
def get_draft_worksheet():
    draft_worksheet_name = st.secrets.get("DRAFT_WORKSHEET_NAME", "drafts")
    return get_or_create_worksheet(draft_worksheet_name, DRAFT_COLUMNS, rows=1000)


def ensure_headers(worksheet, required_columns: list[str]) -> list[str]:
    existing = worksheet.row_values(1)
    existing = [str(h).strip() for h in existing if str(h).strip()]
    headers = list(existing)
    for col in required_columns:
        if col not in headers:
            headers.append(col)
    if headers != existing:
        worksheet.update("1:1", [headers])
    return headers


def ensure_sheet_headers(worksheet) -> list[str]:
    return ensure_headers(worksheet, SHEET_COLUMNS)


def ensure_draft_headers(worksheet) -> list[str]:
    return ensure_headers(worksheet, DRAFT_COLUMNS)


def normalize_tracker_df(records: list[dict], template_df: pd.DataFrame) -> pd.DataFrame:
    if not records:
        df = template_df.copy()
    else:
        df = pd.DataFrame(records)
        
    for col in template_df.columns:
        if col not in df.columns:
            df[col] = 0 if col not in ["member_name", "role", "notes"] else ""
            
    if len(df) < 50:
        missing_rows = 50 - len(df)
        pad_data = {c: ("" if c in ["member_name", "role", "notes"] else 0) for c in template_df.columns}
        padding = pd.DataFrame([pad_data for _ in range(missing_rows)])
        df = pd.concat([df, padding], ignore_index=True)
        
    return df.reindex(columns=template_df.columns).fillna("")


def load_cloud_draft(competition: str, pm_name: str, division: str, week_start) -> list[dict] | None:
    if not pm_name.strip():
        return None
    worksheet = get_draft_worksheet()
    rows = worksheet.get_all_records()
    key = cloud_draft_key(competition, pm_name, division, week_start)
    for row in rows:
        if str(row.get("draft_key", "")).strip() == key:
            raw_json = row.get("draft_json", "")
            if not raw_json:
                return None
            return json.loads(raw_json)
    return None


def delete_cloud_draft(competition: str, pm_name: str, division: str, week_start) -> int:
    if not pm_name.strip():
        return 0
    worksheet = get_draft_worksheet()
    key = cloud_draft_key(competition, pm_name, division, week_start)
    rows = worksheet.get_all_records()
    to_delete = []
    for offset, row in enumerate(rows, start=2):
        if str(row.get("draft_key", "")).strip() == key:
            to_delete.append(offset)
    for row_number in reversed(to_delete):
        worksheet.delete_rows(row_number)
    return len(to_delete)


def save_cloud_draft(competition: str, pm_name: str, division: str, week_start, rows: list[dict]) -> tuple[bool, str]:
    if not pm_name.strip():
        return False, "Please enter your PM name before saving a cloud draft."
    worksheet = get_draft_worksheet()
    headers = ensure_draft_headers(worksheet)
    deleted = delete_cloud_draft(competition, pm_name, division, week_start)
    week_end = week_start + timedelta(days=4)
    draft_row = {
        "draft_key": cloud_draft_key(competition, pm_name, division, week_start),
        "competition": competition,
        "week_start": str(week_start),
        "week_end": str(week_end),
        "division": division,
        "pm_name": pm_name,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "draft_json": json.dumps(rows, ensure_ascii=False),
    }
    worksheet.append_row([draft_row.get(header, "") for header in headers], value_input_option="USER_ENTERED")
    if deleted:
        return True, f"Cloud draft updated. Replaced {deleted} previous draft row(s)."
    return True, "Cloud draft saved. You can reopen this PM/division/week later from any computer."


def report_records_for_sheet(report: dict, input_rows: list[dict], competition: str) -> list[dict]:
    valid_input_rows = [r for r in input_rows if str(r.get("member_name", "")).strip()]
    records = []
    for idx, record in enumerate(report.get("records", [])):
        row = dict(record)
        raw = valid_input_rows[idx] if idx < len(valid_input_rows) else {}
        row["competition"] = competition
        row["timestamp"] = report.get("created_at", row.get("created_at", ""))
        row["hours_invested"] = raw.get("hours_invested", 0)
        row["communication_score"] = raw.get("communication_score", 0)
        if isinstance(row.get("flags"), list):
            row["flags"] = json.dumps(row["flags"], ensure_ascii=False)
        records.append(row)
    return records


def delete_existing_rows(worksheet, *, competition: str, pm_name: str, division: str, week_start: str) -> int:
    rows = worksheet.get_all_records()
    to_delete = []
    target_comp = str(competition).strip().lower()
    target_pm = str(pm_name).strip().lower()
    target_div = str(division).strip().lower()
    target_week = str(week_start).strip()
    
    for offset, row in enumerate(rows, start=2):
        row_comp = str(row.get("competition", "")).strip().lower()
        if (
            row_comp == target_comp
            and str(row.get("pm_name", "")).strip().lower() == target_pm
            and str(row.get("division", "")).strip().lower() == target_div
            and str(row.get("week_start", "")).strip() == target_week
        ):
            to_delete.append(offset)
            
    for row_number in reversed(to_delete):
        worksheet.delete_rows(row_number)
    return len(to_delete)


def append_report_to_sheet(report: dict, input_rows: list[dict], competition: str, replace_existing: bool = True) -> tuple[int, int]:
    worksheet = get_worksheet()
    headers = ensure_sheet_headers(worksheet)
    deleted = 0
    if replace_existing:
        deleted = delete_existing_rows(
            worksheet,
            competition=competition,
            pm_name=report.get("pm_name", ""),
            division=report.get("division", ""),
            week_start=report.get("week_start", ""),
        )
        headers = ensure_sheet_headers(worksheet)

    records = report_records_for_sheet(report, input_rows, competition)
    values = [[row.get(header, "") for header in headers] for row in records]
    if values:
        worksheet.append_rows(values, value_input_option="USER_ENTERED")
    return len(values), deleted


st.set_page_config(page_title="AV PM Weekly Reporter", page_icon="❖", layout="wide")

# -----------------------------------------------------------------------------
# COMPETITION STATE INITIALIZATION & TOGGLE
# -----------------------------------------------------------------------------
if "competition" not in st.session_state:
    st.session_state.competition = "Mars"

# Render the selector early so we can grab its state for CSS
c_comp1, c_comp2 = st.columns([1, 1])
with c_comp1:
    st.markdown('<div class="glass" style="margin-bottom: 18px; padding: 16px 24px;">', unsafe_allow_html=True)
    st.markdown("<h4 style='margin-top: 0; margin-bottom: 12px; color: #f8fafc; font-size: 16px;'>🎯 Target Competition Program</h4>", unsafe_allow_html=True)
    comp_choice = st.radio(
        "Competition Program",
        options=["Mars Mission", "Luna Mission"],
        index=0 if st.session_state.competition == "Mars" else 1,
        horizontal=True,
        label_visibility="collapsed",
    )
    st.markdown('</div>', unsafe_allow_html=True)

st.session_state.competition = "Mars" if comp_choice == "Mars Mission" else "Luna"
competition = st.session_state.competition

# -----------------------------------------------------------------------------
# DYNAMIC THEME ENGINE (Animated Transition between Mars & Luna)
# -----------------------------------------------------------------------------
if competition == "Mars":
    # Dark & Red
    bg_top = "#1e293b"
    bg_bot = "#000000"
    side_top = "#1e293b"
    side_bot = "#111827"
    panel_bg = "#1e293b"
    primary = "#ef4444"
    primary_hover = "#dc2626"
    primary_text = "#ffffff"
    primary_shadow = "rgba(239, 68, 68, 0.25)"
    logo_a_color = "#ef4444"
    logo_a_shadow = "#7f1d1d"
else:
    # Lighter Dark & White/Silver
    bg_top = "#334155"      
    bg_bot = "#0f172a"      
    side_top = "#334155"
    side_bot = "#1e293b"
    panel_bg = "#475569"    
    primary = "#f8fafc"     
    primary_hover = "#e2e8f0"
    primary_text = "#1e3a8a" # Deep dark blue from the 'V' shadow
    primary_shadow = "rgba(255, 255, 255, 0.20)"
    logo_a_color = "#f8fafc"
    logo_a_shadow = "#64748b"

st.markdown(
    f"""
<style>
    :root {{
        --bg-top: {bg_top};
        --bg-bot: {bg_bot};
        --side-top: {side_top};
        --side-bot: {side_bot};
        --panel: {panel_bg};
        --primary: {primary};
        --primary-hover: {primary_hover};
        --primary-text: {primary_text};
        --primary-shadow: {primary_shadow};
        --logo-a-color: {logo_a_color};
        --logo-a-shadow: {logo_a_shadow};
        
        --ink: #f8fafc;
        --line: rgba(255, 255, 255, 0.15);
        --shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
    }}
    
    /* ANIMATIONS: Add smooth fade to all major structural elements */
    [data-testid="stAppViewContainer"],
    [data-testid="stSidebar"],
    .hero, .glass, button, button *, .av-logo .a, div[data-baseweb="tab-highlight"], 
    .stButton > button, [data-testid="stFormSubmitButton"] > button {{
        transition: all 0.7s ease-in-out !important;
    }}
    
    [data-testid="stAppViewContainer"] {{
        background: radial-gradient(circle at top, var(--bg-top) 0%, var(--bg-bot) 100%);
        background-attachment: fixed;
        color: var(--ink);
    }}
    
    [data-testid="stHeader"] {{ background: rgba(15, 23, 42, 0); }}
    
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, var(--side-top) 0%, var(--side-bot) 100%);
        border-right: 1px solid var(--line);
    }}
    
    .block-container {{ padding-top: 2rem; max-width: 1440px; }}
    
    .hero {{
        position: relative;
        overflow: hidden;
        padding: 38px 42px;
        border-radius: 24px;
        background: var(--panel);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
        margin-bottom: 20px;
        color: #f8fafc;
    }}
    .hero-content {{ position: relative; z-index: 2; max-width: 920px; }}
    .eyebrow {{ color: #60a5fa; font-size: 13px; letter-spacing: .16em; text-transform: uppercase; font-weight: 800; }}
    .title {{ font-size: clamp(32px, 4.5vw, 64px); font-weight: 900; letter-spacing: -.05em; line-height: 1; margin: 5px 0 15px 0; color: #ffffff; }}
    .subtitle {{ color: #cbd5e1; font-size: 18px; max-width: 900px; line-height: 1.58; }}
    
    /* Dynamic AV Logo Styling */
    .av-logo-container {{ display: flex; align-items: center; gap: 20px; }}
    .av-logo {{
        font-family: 'Arial Black', sans-serif;
        font-size: 72px;
        letter-spacing: -14px;
        font-style: italic;
        line-height: 1;
        user-select: none;
    }}
    .av-logo .a {{ color: var(--logo-a-color); text-shadow: 3px 3px 0px var(--logo-a-shadow); }}
    .av-logo .v {{ color: #3b82f6; text-shadow: 3px 3px 0px #1e3a8a; mix-blend-mode: screen; }}

    .glass {{
        padding: 22px 24px;
        border-radius: 20px;
        background: var(--panel);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
        margin-bottom: 18px;
        color: var(--ink);
    }}
    
    /* Segmented Control Styling */
    div.row-widget.stRadio > div {{
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: 20px;
        background: rgba(255,255,255,0.05);
        padding: 10px 20px;
        border-radius: 12px;
        border: 1px solid var(--line);
    }}

    .division-pill {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid var(--line);
        margin: 0 8px 8px 0;
        color: #f8fafc;
        font-size: 13px;
        font-weight: 750;
    }}
    .dot {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; }}
    .metric-note {{ color: #94a3b8; font-size: 13px; margin-top: 10px;}}
    
    h1, h2, h3, p, label, span, div {{ text-shadow: none; color: var(--ink); }}
    
    /* Tabs Styling */
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

    /* Standard Buttons (Blue fallback) */
    .stButton > button {{
        background: #2563eb !important; 
        color: #ffffff !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
    }}
    .stButton > button * {{ color: #ffffff !important; }}
    
    /* Primary Accent Buttons (Dynamic Red or White) */
    button[kind="primary"], [data-testid="stFormSubmitButton"] > button, .stDownloadButton > button {{
        background: var(--primary) !important;
        color: var(--primary-text) !important;
        box-shadow: 0 8px 20px var(--primary-shadow) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
    }}
    
    /* Force inner Streamlit text tags to inherit dynamic color */
    button[kind="primary"] *, [data-testid="stFormSubmitButton"] > button *, .stDownloadButton > button * {{
        color: var(--primary-text) !important;
    }}
    
    button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button:hover, .stDownloadButton > button:hover {{ 
        background: var(--primary-hover) !important; 
        transform: translateY(-1px); 
    }}
    
    /* Fix inputs */
    input, textarea, [data-baseweb="select"] {{ color: #f8fafc !important; }}
    [data-baseweb="base-input"], [data-baseweb="select"] > div {{
        background: #0f172a !important;
        border-color: #334155 !important;
    }}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="hero">
  <div class="hero-content">
    <div class="av-logo-container">
        <div class="av-logo"><span class="a">A</span><span class="v">V</span></div>
        <div>
            <div class="eyebrow">Project AV • {competition} Mission Mode</div>
            <div class="title">Weekly Performance Report</div>
        </div>
    </div>
    <div class="subtitle" style="margin-top: 10px;">
      PMs fill this once per week. The app does not assign tasks; it turns execution, quality, attendance, delivery, blockers, and PM confidence into clean leadership data.
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# SIDEBAR CONFIGURATION
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("Report setup")
    pm_name = st.text_input("PM name", placeholder="Ej. Alejandro / PM Robotic Arm")
    division = st.selectbox("Division", DIVISIONS, index=0)

    st.divider()
    st.subheader("Week Selection")
    st.caption("Pick the Monday-Friday work week being reported.")
    
    # Calendar Controls
    if "selected_date" not in st.session_state:
        st.session_state.selected_date = today_monday()

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("◀ Prev"):
            st.session_state.selected_date -= timedelta(weeks=1)
    with c2:
        if st.button("■ This", type="primary", use_container_width=True):
            st.session_state.selected_date = today_monday()
    with c3:
        if st.button("Next ▶"):
            st.session_state.selected_date += timedelta(weeks=1)
            
    cal_date = st.date_input("Calendar Date", value=st.session_state.selected_date)
    st.session_state.selected_date = cal_date
    week_start = monday_for(cal_date)
    week_end = week_start + timedelta(days=4)
    
    st.info(f"Selected work week: **{week_range_label(week_start)}**")

    st.divider()
    st.caption("Score weights")
    for name, weight in METRIC_WEIGHTS.items():
        st.write(f"**{name.title()}**: {int(weight * 100)}%")

legend_html = "".join(
    f'<span class="division-pill"><span class="dot" style="background:{color}"></span>{division_name}</span>'
    for division_name, color in DIVISION_COLORS.items()
)
st.markdown(f'<div class="glass"><b>Official division legend</b><br><br>{legend_html}<div class="metric-note">Formula: {metric_weights_text()}</div></div>', unsafe_allow_html=True)

sheet_ok, sheet_msg = google_sheet_ready()

# --- DATA INITIALIZATION & DRAFT LOADING ---
init_df = pd.DataFrame(empty_input_rows())
if "hours_invested" not in init_df.columns:
    init_df["hours_invested"] = 0
if "communication_score" not in init_df.columns:
    init_df["communication_score"] = 0.0

# Ensure capacity for 50 rows
if len(init_df) < 50:
    missing_rows = 50 - len(init_df)
    pad_data = {c: ("" if c in ["member_name", "role", "notes"] else 0) for c in init_df.columns}
    padding = pd.DataFrame([pad_data for _ in range(missing_rows)])
    init_df = pd.concat([init_df, padding], ignore_index=True)

current_draft_key = f"{competition}_{pm_name}_{division}_{week_start}"
draft_path = get_draft_path(competition, pm_name, division, week_start)

# Load draft safely. Cloud draft is preferred. Local draft is only fallback.
if "tracker_df" not in st.session_state or st.session_state.get("last_draft_key") != current_draft_key:
    draft_records = None
    st.session_state.pop("loaded_cloud_draft_message", None)
    st.session_state.pop("cloud_draft_load_error", None)

    if pm_name.strip() and sheet_ok:
        try:
            draft_records = load_cloud_draft(competition, pm_name, division, week_start)
            if draft_records is not None:
                st.session_state.loaded_cloud_draft_message = f"Loaded saved cloud draft for {competition}, {division}, {week_range_label(week_start)}."
        except Exception as exc:
            st.session_state.cloud_draft_load_error = str(exc)

    if draft_records is not None:
        st.session_state.tracker_df = normalize_tracker_df(draft_records, init_df)
    elif pm_name.strip() and draft_path.exists():
        try:
            with open(draft_path, "r", encoding="utf-8") as f:
                draft_data = json.load(f)
            st.session_state.tracker_df = normalize_tracker_df(draft_data, init_df)
            st.session_state.loaded_cloud_draft_message = "Loaded local fallback draft. Save once to move it into the cloud draft tab."
        except Exception:
            st.session_state.tracker_df = init_df.copy()
    else:
        st.session_state.tracker_df = init_df.copy()
    
    st.session_state["last_draft_key"] = current_draft_key

if st.session_state.get("loaded_cloud_draft_message"):
    st.info(st.session_state.pop("loaded_cloud_draft_message"))
if st.session_state.get("cloud_draft_load_error"):
    st.warning(f"Could not load cloud draft: {st.session_state.pop('cloud_draft_load_error')}")

# --- COLUMN CONFIGURATIONS ---
col_config_base = {
    "member_name": st.column_config.TextColumn("Member Name", help="Required for row to count"),
    "role": st.column_config.TextColumn("Role / Subteam"),
    "tasks_assigned": st.column_config.NumberColumn("Tasks Assigned", min_value=0, step=1),
    "hours_invested": st.column_config.NumberColumn("Hours Logged", min_value=0, step=1, help="Estimated time spent this week"),
    "tasks_completed": st.column_config.NumberColumn("Tasks Completed", min_value=0, step=1),
    "tasks_on_time": st.column_config.NumberColumn("Completed On Time", min_value=0, step=1),
    "tasks_late": st.column_config.NumberColumn("Completed Late", min_value=0, step=1),
    "blocked_tasks": st.column_config.NumberColumn("Blocked Tasks", min_value=0, step=1),
    "avg_quality_1_to_5": st.column_config.NumberColumn("Quality Avg (1-5)", min_value=0.0, max_value=5.0, step=0.1),
    "meetings_required": st.column_config.NumberColumn("Meetings Required", min_value=0, step=1),
    "meetings_attended": st.column_config.NumberColumn("Meetings Attended", min_value=0, step=1),
    "pm_confidence_1_to_5": st.column_config.NumberColumn("PM Confidence (1-5)", min_value=1.0, max_value=5.0, step=0.5),
    "communication_score": st.column_config.NumberColumn("Comm Score (1-5)", min_value=0.0, max_value=5.0, step=0.5, help="Responsiveness, clarity, and teamwork"),
    "notes": st.column_config.TextColumn("Notes / Blockers"),
}

col_config_locked = col_config_base.copy()
col_config_locked["member_name"] = st.column_config.TextColumn("Member Name", disabled=True, help="Edit names in the Assignment tab")

# -----------------------------------------------------------------------------
# TAB SECTION WITH HELP ICON AND FORM
# -----------------------------------------------------------------------------
st.markdown('<div class="glass">', unsafe_allow_html=True)

c_title, c_help = st.columns([10, 1])
with c_title:
    st.subheader("Member weekly rows")
with c_help:
    with st.popover("ℹ️ Help"):
        st.markdown("""
        **Data Entry Guide**

        **❖ 1. Assignment**
        * **Member Name:** Identity (Required).
        * **Role:** Subteam or project focus.
        * **Tasks Assigned:** Workload given this week.
        * **Hours Logged:** Estimated time spent executing.

        **❖ 2. Execution**
        * **Tasks Completed:** Total tickets finished.
        * **Completed On Time:** Delivered before the deadline.
        * **Completed Late:** Delivered after the deadline.
        * **Blocked Tasks:** Stuck waiting on someone else.

        **❖ 3. Performance**
        * **Quality (1-5):** How good was the output? (5=Perfect)
        * **Meetings:** Required to attend vs. actually attended.
        * **PM Confidence (1-5):** Your trust in their current trajectory.
        * **Comm Score (1-5):** Responsiveness and team clarity.
        * **Notes:** Blockers, praise, or internal flags.
        """)

st.info("Type freely in any tab. Click Save Progress to store the draft in Google Sheets by Competition + PM + Division + Week.")

# Wrapping the editors in a form stops Streamlit from rerunning the app while you type
with st.form("weekly_data_form"):
    tab1, tab2, tab3 = st.tabs(["❖ 1. Assignment", "❖ 2. Execution", "❖ 3. Performance"])

    with tab1:
        df1 = st.data_editor(
            st.session_state.tracker_df[["member_name", "role", "tasks_assigned", "hours_invested"]],
            key="editor_tab1",
            use_container_width=True,
            hide_index=True,
            height=480, # Scrollable fixed height for 50 rows
            column_config=col_config_base
        )
    with tab2:
        df2 = st.data_editor(
            st.session_state.tracker_df[["member_name", "tasks_completed", "tasks_on_time", "tasks_late", "blocked_tasks"]],
            key="editor_tab2",
            use_container_width=True,
            hide_index=True,
            height=480, 
            column_config=col_config_locked
        )
    with tab3:
        df3 = st.data_editor(
            st.session_state.tracker_df[["member_name", "avg_quality_1_to_5", "meetings_required", "meetings_attended", "pm_confidence_1_to_5", "communication_score", "notes"]],
            key="editor_tab3",
            use_container_width=True,
            hide_index=True,
            height=480, 
            column_config=col_config_locked
        )

    st.markdown("<br>", unsafe_allow_html=True)
    # The explicit save button to lock in edits uses type="primary" to pull the dynamic Mars/Luna color
    submit_edits = st.form_submit_button("☑ Save Cloud Draft & Update Preview Below", type="primary", use_container_width=True)

# Process the save event AFTER the form is submitted
if submit_edits:
    st.session_state.tracker_df.update(df1)
    st.session_state.tracker_df.update(df2.drop(columns=["member_name"]))
    st.session_state.tracker_df.update(df3.drop(columns=["member_name"]))
    
    if pm_name.strip():
        draft_records_to_save = st.session_state.tracker_df.to_dict(orient="records")
        if sheet_ok:
            try:
                ok, message = save_cloud_draft(competition, pm_name, division, week_start, draft_records_to_save)
                if ok:
                    st.session_state.show_success = message
                else:
                    st.session_state.show_warning = message
            except Exception as exc:
                try:
                    draft_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(draft_path, "w", encoding="utf-8") as f:
                        json.dump(draft_records_to_save, f, indent=4)
                    st.session_state.show_save_error = f"Cloud draft failed, but local fallback was saved: {exc}"
                except Exception as local_exc:
                    st.session_state.show_save_error = f"Cloud draft failed: {exc}; local fallback also failed: {local_exc}"
        else:
            st.session_state.show_save_error = "Google Sheets is not configured, so the cloud draft could not be saved."
    else:
        st.session_state.show_warning = True
        
    st.rerun()

# Display the save messages outside the rerun cycle
success_message = st.session_state.pop("show_success", False)
if success_message:
    st.success(success_message if isinstance(success_message, str) else "Changes saved successfully to your cloud draft.")
warning_message = st.session_state.pop("show_warning", False)
if warning_message:
    st.warning(warning_message if isinstance(warning_message, str) else "Please enter your PM Name in the sidebar to save your cloud draft.")
if st.session_state.get("show_save_error"):
    st.error(f"Draft save failed: {st.session_state.pop('show_save_error')}")

st.markdown('</div>', unsafe_allow_html=True)

# --- REPORT GENERATION ---
rows = st.session_state.tracker_df.fillna("").to_dict(orient="records")
report = make_report(pm_name=pm_name, division=division, week_start=week_start, rows=rows)
report["competition"] = competition  # Inject competition into JSON backup
preview = pd.DataFrame(report["records"])

st.markdown('<div class="glass">', unsafe_allow_html=True)
st.subheader("Auto-calculated preview")
if preview.empty:
    st.info("No real rows yet. Add at least one member name in the 'Assignment' tab and click Save to preview metrics.")
else:
    visible = preview[
        [
            "member_name",
            "role",
            "completion_score",
            "quality_score",
            "delivery_score",
            "attendance_score",
            "confidence_score",
            "performance_pct",
            "status",
            "flags",
            "notes",
        ]
    ].copy()
    visible["flags"] = visible["flags"].apply(flags_to_text)
    st.dataframe(visible, use_container_width=True, hide_index=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Members", len(preview))
    c2.metric("Avg performance", f"{preview['performance_pct'].mean():.1f}%")
    c3.metric("Open blockers", int(preview["blocked_tasks"].sum()))
    c4.metric("Critical / Watch", int(preview["status"].isin(["Critical", "Watch"]).sum()))
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="glass">', unsafe_allow_html=True)
st.subheader("Submit to Google Sheets")
st.write(f"Submitting **{competition} Mission** metrics to the Google Sheet database. Drafts are saved to `drafts` and final reports to `reports`.")

if sheet_ok:
    st.success(sheet_msg)
else:
    st.error(sheet_msg)
    st.caption("Add the Google service account and Sheet settings in Streamlit Cloud → Manage app → Settings → Secrets.")

replace_existing = st.checkbox(
    f"Replace any previous rows for {competition} / {pm_name} / {division} / {week_start}",
    value=True,
    help="Recommended. Prevents duplicate weekly submissions when a PM fixes and resubmits a report.",
)

col_a, col_b = st.columns([1, 2])
with col_a:
    save_clicked = st.button(f"► Final Submit to Google Sheets", type="primary", use_container_width=True)
with col_b:
    st.code(st.secrets.get("SHEET_NAME", "AV PM Reports Database"), language="text")

if save_clicked:
    if not pm_name.strip():
        st.error("Falta el nombre del PM.")
    elif preview.empty:
        st.error("No hay miembros válidos para exportar.")
    elif not sheet_ok:
        st.error("Google Sheets is not configured yet. Check Streamlit Secrets.")
    else:
        try:
            rows_written, rows_deleted = append_report_to_sheet(report, rows, competition, replace_existing=replace_existing)
            st.success(f"Submitted {rows_written} member row(s) to Google Sheets.")
            if rows_deleted:
                st.info(f"Replaced {rows_deleted} old row(s) for {competition} / {pm_name} / {division} / {week_start}.")
            st.cache_data.clear()

            # Clear cloud/local drafts now that it is officially submitted.
            try:
                deleted_drafts = delete_cloud_draft(competition, pm_name, division, week_start)
                if deleted_drafts:
                    st.info(f"Cleared {deleted_drafts} cloud draft row(s).")
            except Exception as draft_exc:
                st.warning(f"Submitted successfully, but cloud draft cleanup failed: {draft_exc}")
            if draft_path.exists():
                os.remove(draft_path)
        except Exception as exc:
            st.error(f"Google Sheets submit failed: {exc}")
            st.caption("Most common causes: missing Streamlit secrets, Sheet not shared with the service account, or wrong worksheet name.")

json_bytes = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
st.download_button(
    "Download backup JSON",
    data=json_bytes,
    file_name=f"{report['iso_year']}-W{report['iso_week']:02d}_{competition}_{division.replace(' ', '_').replace('&', 'and')}_weekly_report.json",
    mime="application/json",
    use_container_width=True,
)
st.markdown('</div>', unsafe_allow_html=True)
