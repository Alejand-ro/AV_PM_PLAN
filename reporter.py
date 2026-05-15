from __future__ import annotations

import calendar
import json
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

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

st.set_page_config(page_title="AV PM Weekly Reporter", page_icon="⌖", layout="wide")

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
    "timestamp", "competition", "week_start", "division", "pm_name", "member_name",
    "role", "tasks_assigned", "hours_invested", "tasks_completed", "tasks_on_time",
    "tasks_late", "blocked_tasks", "avg_quality_1_to_5", "meetings_required",
    "meetings_attended", "pm_confidence_1_to_5", "communication_score", "notes",
    "report_id", "record_id", "created_at", "iso_year", "iso_week", "completion_score",
    "quality_score", "delivery_score", "attendance_score", "confidence_score",
    "performance_score", "performance_pct", "status", "flags",
]

DRAFT_COLUMNS = [
    "draft_key", "competition", "week_start", "week_end", "division",
    "pm_name", "updated_at", "draft_json",
]

CONTENT_CAL_COLUMNS = [
    "content_id", "mission", "cycle", "month", "planned_date", "platform",
    "content_title", "description", "content_type", "owner", "status",
    "actual_posted_date", "marked_done_at", "notes", "created_at", "updated_at"
]

EVENTS_HEADERS = [
    "event_id", "mission", "cycle", "event_name", "event_type", "planned_date", "actual_date", 
    "location", "target_audience", "expected_gross_revenue", "expected_expenses", "expected_net_revenue", 
    "actual_gross_revenue", "actual_expenses", "actual_net_revenue", "status", "owner", "key_contacts", 
    "venue_confirmed", "permits_needed", "permits_completed", "marketing_ready", "volunteers_ready", 
    "follow_up_completed", "notes", "created_at", "updated_at"
]

TRANSACTIONS_HEADERS = [
    "transaction_id", "event_id", "transaction_date", "mission", "cycle", "event_name", 
    "source_type", "source_name", "payment_method", "amount", "confirmed", "deposited", 
    "deposit_date", "notes", "created_at", "updated_at"
]

EXPENSES_HEADERS = [
    "expense_id", "event_id", "expense_date", "mission", "cycle", "event_name", "vendor", 
    "item_description", "category", "amount", "reimbursed", "receipt_available", "notes", 
    "created_at", "updated_at"
]

GOALS_HEADERS = [
    "goal_id", "mission", "cycle", "goal_name", "target_amount", "deadline", "purpose", 
    "status", "notes", "created_at", "updated_at"
]

PLATFORM_COLORS = {
    "No post day": "#ef4444", "Outreach Activity": "#f97316", "LinkedIn": "#eab308", 
    "Email": "#22c55e", "X": "#2dd4bf", "TikTok": "#38bdf8", "Facebook": "#c084fc", 
    "YouTube": "#f43f5e", "Instagram": "#d946ef", "Other": "#94a3b8"
}

STATUS_SYMBOLS = {
    "Planned": "◌", "In Progress": "◐", "Posted": "●",
    "Missed": "⚠", "Cancelled": "×", "Rescheduled": "↷"
}

DYNAMIC_CYCLES = ["2026-2027", "2027-2028", "2028-2029"]
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

def get_content_calendar_worksheet():
    return get_or_create_worksheet("content_calendar", CONTENT_CAL_COLUMNS, rows=2000)

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

def ensure_draft_headers(worksheet) -> list[str]:
    return ensure_headers(worksheet, DRAFT_COLUMNS)

def ensure_sheet_headers(worksheet) -> list[str]:
    return ensure_headers(worksheet, SHEET_COLUMNS)

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

# --- CONTENT CALENDAR HELPER FUNCTIONS ---
@st.cache_data(ttl=60, show_spinner=False)
def load_content_calendar(force_refresh=0) -> pd.DataFrame:
    worksheet = get_content_calendar_worksheet()
    records = worksheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=CONTENT_CAL_COLUMNS)
    df = pd.DataFrame(records)
    for col in CONTENT_CAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df

def save_content_calendar_month(df_edited: pd.DataFrame, mission: str, cycle: str, target_month: str, target_year: int):
    worksheet = get_content_calendar_worksheet()
    headers = ensure_headers(worksheet, CONTENT_CAL_COLUMNS)
    
    all_records = worksheet.get_all_records()
    df_all = pd.DataFrame(all_records)
    if df_all.empty:
        df_all = pd.DataFrame(columns=headers)
        
    for col in headers:
        if col not in df_all.columns:
            df_all[col] = ""

    # Drop existing rows for this specific mission, cycle, and month/year
    if not df_all.empty:
        df_all["temp_dt"] = pd.to_datetime(df_all["planned_date"], errors="coerce")
        mask = (
            (df_all["mission"] == mission) & 
            (df_all["cycle"] == cycle) & 
            (df_all["temp_dt"].dt.month == MONTHS_LIST.index(target_month) + 1) &
            (df_all["temp_dt"].dt.year == target_year)
        )
        df_all = df_all[~mask].drop(columns=["temp_dt"])

    # Prepare edited df
    now_str = datetime.utcnow().isoformat() + "Z"
    
    clean_edited = []
    for _, row in df_edited.iterrows():
        r = row.to_dict()
        # Skip truly blank rows (unless it's a "No post day")
        if not r.get("content_title") and not r.get("description") and r.get("platform") != "No post day":
            continue
            
        if not r.get("content_id"):
            r["content_id"] = f"{mission}_{cycle}_{r.get('planned_date','')}_{uuid.uuid4().hex[:6]}"
            r["created_at"] = now_str
            
        r["mission"] = mission
        r["cycle"] = cycle
        r["month"] = target_month
        r["updated_at"] = now_str
        
        # Mark as done logic
        if r.get("status") == "Posted":
            if not r.get("actual_posted_date") or r.get("actual_posted_date") == "NaT":
                r["actual_posted_date"] = date.today().strftime("%Y-%m-%d")
            if not r.get("marked_done_at"):
                r["marked_done_at"] = now_str
        else:
            # If changed back from posted, clear the actual date
            if r.get("actual_posted_date"):
                r["actual_posted_date"] = ""
            if r.get("marked_done_at"):
                r["marked_done_at"] = ""
                
        clean_edited.append(r)
        
    df_new = pd.DataFrame(clean_edited)
    if not df_new.empty:
        for col in headers:
            if col not in df_new.columns:
                df_new[col] = ""
        df_all = pd.concat([df_all, df_new], ignore_index=True)
        
    df_all = df_all.fillna("").astype(str).replace(["NaT", "nan", "None", "<NA>"], "")
    
    # Write full sheet back safely
    data = [headers] + df_all[headers].values.tolist()
    worksheet.clear()
    worksheet.append_rows(data, value_input_option="USER_ENTERED")

# --- FUNDRAISING & FINANCE HELPER FUNCTIONS ---
@st.cache_data(ttl=60, show_spinner=False)
def load_finance_sheet(sheet_name: str, headers: list[str]) -> pd.DataFrame:
    worksheet = get_or_create_worksheet(sheet_name, headers, rows=1000)
    records = worksheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=headers)
    df = pd.DataFrame(records)
    for col in headers:
        if col not in df.columns:
            df[col] = ""
    return df

def save_finance_sheet(sheet_name: str, df_edited: pd.DataFrame, headers: list[str], id_col: str, mission: str, cycle: str):
    worksheet = get_or_create_worksheet(sheet_name, headers, rows=1000)
    df_all = pd.DataFrame(worksheet.get_all_records())
    
    if df_all.empty:
        df_all = pd.DataFrame(columns=headers)
    for col in headers:
        if col not in df_all.columns:
            df_all[col] = ""

    # Clear existing rows for this mission and cycle
    if not df_all.empty and "mission" in df_all.columns and "cycle" in df_all.columns:
        mask = (df_all["mission"] == mission) & (df_all["cycle"] == cycle)
        df_all = df_all[~mask]

    now_str = datetime.utcnow().isoformat() + "Z"
    clean_edited = []
    
    for _, row in df_edited.iterrows():
        r = row.to_dict()
        
        # Skip completely blank lines 
        if not str(r.get(id_col, "")) and not str(r.get("event_name", "")) and not str(r.get("amount", "")) and not str(r.get("goal_name", "")):
            continue
            
        if not str(r.get(id_col, "")):
            r[id_col] = f"{mission}_{cycle}_{uuid.uuid4().hex[:8]}"
            r["created_at"] = now_str
            
        r["mission"] = mission
        r["cycle"] = cycle
        r["updated_at"] = now_str
        clean_edited.append(r)
        
    df_new = pd.DataFrame(clean_edited)
    if not df_new.empty:
        for col in headers:
            if col not in df_new.columns:
                df_new[col] = ""
        df_all = pd.concat([df_all, df_new], ignore_index=True)
        
    df_all = df_all.fillna("").astype(str).replace(["NaT", "nan", "None", "<NA>", "False"], "")
    
    data = [headers] + df_all[headers].values.tolist()
    worksheet.clear()
    worksheet.append_rows(data, value_input_option="USER_ENTERED")

# -----------------------------------------------------------------------------
# EARLY STATE INITIALIZATION (Allows theme & filter updates without double reload)
# -----------------------------------------------------------------------------
if "comp_radio" not in st.session_state:
    st.session_state.comp_radio = "Mars Mission"
    
competition = "Mars" if "Mars" in st.session_state.comp_radio else ("Luna" if "Luna" in st.session_state.comp_radio else "General")
st.session_state.competition = competition

# Division Filter Logic based on selected competition
if competition == "Luna":
    luna_allowed = ["electrical", "vehicle", "software"]
    active_divisions = [d for d in DIVISIONS if any(k in d.lower() for k in luna_allowed)]
    if not active_divisions:
        active_divisions = ["Electrical", "Vehicle Design", "Software"]
else:
    active_divisions = DIVISIONS

# -----------------------------------------------------------------------------
# DYNAMIC THEME ENGINE
# -----------------------------------------------------------------------------
if competition == "Mars":
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
    logo_v_color = "#ffffff"
    logo_v_shadow = "#94a3b8"
elif competition == "Luna":
    bg_top = "#334155"      
    bg_bot = "#0f172a"      
    side_top = "#334155"
    side_bot = "#1e293b"
    panel_bg = "#475569"    
    primary = "#f8fafc"     
    primary_hover = "#e2e8f0"
    primary_text = "#1e3a8a" 
    primary_shadow = "rgba(255, 255, 255, 0.20)"
    logo_a_color = "#f8fafc"
    logo_a_shadow = "#64748b"
    logo_v_color = "#3b82f6"
    logo_v_shadow = "#1e3a8a"
else:
    bg_top = "#1e293b"
    bg_bot = "#000000"
    side_top = "#1e293b"
    side_bot = "#111827"
    panel_bg = "#1e293b"
    primary = "#3b82f6"
    primary_hover = "#2563eb"
    primary_text = "#ffffff"
    primary_shadow = "rgba(59, 130, 246, 0.25)"
    logo_a_color = "#ef4444"
    logo_a_shadow = "#7f1d1d"
    logo_v_color = "#3b82f6"
    logo_v_shadow = "#1e3a8a"

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
        --logo-v-color: {logo_v_color};
        --logo-v-shadow: {logo_v_shadow};
        
        --ink: #f8fafc;
        --line: rgba(255, 255, 255, 0.15);
        --shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
    }}
    
    /* ANIMATIONS */
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
        margin-bottom: 24px;
        color: #f8fafc;
    }}
    .hero-content {{ position: relative; z-index: 2; max-width: 920px; }}
    .eyebrow {{ color: #60a5fa; font-size: 13px; letter-spacing: .16em; text-transform: uppercase; font-weight: 800; }}
    .title {{ font-size: clamp(32px, 4.5vw, 64px); font-weight: 900; letter-spacing: -.05em; line-height: 1; margin: 5px 0 15px 0; color: #ffffff; }}
    .subtitle {{ color: #cbd5e1; font-size: 18px; max-width: 900px; line-height: 1.58; }}
    
    .av-logo-container {{ display: flex; align-items: center; gap: 20px; }}
    .av-logo {{ font-family: 'Arial Black', sans-serif; font-size: 72px; letter-spacing: -14px; font-style: italic; line-height: 1; user-select: none; }}
    .av-logo .a {{ color: var(--logo-a-color); text-shadow: 3px 3px 0px var(--logo-a-shadow); }}
    .av-logo .v {{ color: var(--logo-v-color); text-shadow: 3px 3px 0px var(--logo-v-shadow); mix-blend-mode: normal; }}

    .glass {{
        padding: 22px 28px;
        border-radius: 20px;
        background: var(--panel);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
        margin-bottom: 24px;
        color: var(--ink);
    }}
    
    /* Segmented Slider Control Styling */
    div.row-widget.stRadio > div {{
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: 16px;
        background: rgba(255,255,255,0.05);
        padding: 8px 16px;
        border-radius: 100px;
        border: 1px solid var(--line);
        width: fit-content;
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
    
    .kpi {{ 
        padding: 24px; 
        border-radius: 16px; 
        background: rgba(255,255,255,0.03); 
        border: 1px solid var(--line); 
        margin-bottom: 24px;
    }}
    .kpi-label {{ color:#94a3b8; font-size:12px; font-weight:900; letter-spacing:.12em; text-transform:uppercase; }}
    .kpi-value {{ color:#ffffff; font-size:36px; font-weight:950; letter-spacing:-.06em; margin-top:8px; }}
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

# -----------------------------------------------------------------------------
# SIDEBAR NAVIGATION
# -----------------------------------------------------------------------------
st.sidebar.header("⌖ Navigation")
current_page = st.sidebar.radio("Go to", ["▦ Weekly Performance Report", "◫ Content Calendar", "$ Fundraising & Finance"])

if current_page == "▦ Weekly Performance Report":
    # -----------------------------------------------------------------------------
    # PAGE: WEEKLY PERFORMANCE REPORT
    # -----------------------------------------------------------------------------
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
        """, unsafe_allow_html=True
    )

    legend_html = "".join(
        f'<span class="division-pill"><span class="dot" style="background:{color}"></span>{division_name}</span>'
        for division_name, color in DIVISION_COLORS.items() if division_name in active_divisions
    )
    st.markdown(f'<div class="glass"><b>Official Division Legend</b><br><br>{legend_html}<div class="metric-note">Formula: {metric_weights_text()}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="glass" style="padding: 20px 28px;">', unsafe_allow_html=True)
    st.markdown("<h4 style='margin-top: 0; margin-bottom: 12px; color: #f8fafc; font-size: 18px;'>◈ Target Competition Program</h4>", unsafe_allow_html=True)
    st.radio(
        "Competition Program",
        options=["Mars Mission", "Luna Mission"],
        key="comp_radio",
        horizontal=True,
        label_visibility="collapsed",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    with st.sidebar:
        st.header("Report setup")
        pm_name = st.text_input("PM name", placeholder="Ej. Alejandro / PM Robotic Arm")
        division = st.selectbox("Division", active_divisions, index=0)

        st.divider()
        st.subheader("Week Selection")
        st.caption("Pick the Monday-Friday work week being reported.")
        
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

    sheet_ok, sheet_msg = google_sheet_ready()

    init_df = pd.DataFrame(empty_input_rows())
    if "hours_invested" not in init_df.columns:
        init_df["hours_invested"] = 0
    if "communication_score" not in init_df.columns:
        init_df["communication_score"] = 0.0

    if len(init_df) < 50:
        missing_rows = 50 - len(init_df)
        pad_data = {c: ("" if c in ["member_name", "role", "notes"] else 0) for c in init_df.columns}
        padding = pd.DataFrame([pad_data for _ in range(missing_rows)])
        init_df = pd.concat([init_df, padding], ignore_index=True)

    current_draft_key = f"{competition}_{pm_name}_{division}_{week_start}"
    draft_path = get_draft_path(competition, pm_name, division, week_start)

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
        st.info(f"ⓘ {st.session_state.pop('loaded_cloud_draft_message')}")
    if st.session_state.get("cloud_draft_load_error"):
        st.warning(f"⚠ Could not load cloud draft: {st.session_state.pop('cloud_draft_load_error')}")

    col_config_base = {
        "member_name": st.column_config.TextColumn("Member Name", help="Required for row to count"),
        "role": st.column_config.TextColumn("Role / Subteam", help="What subteam or functional role does this member have?"),
        "tasks_assigned": st.column_config.NumberColumn("Tasks Assigned", min_value=0, step=1, help="Total number of tasks handed out."),
        "hours_invested": st.column_config.NumberColumn("Hours Logged", min_value=0, step=1, help="Estimated time spent this week."),
        "tasks_completed": st.column_config.NumberColumn("Tasks Completed", min_value=0, step=1, help="Total tickets fully finished."),
        "tasks_on_time": st.column_config.NumberColumn("Completed On Time", min_value=0, step=1, help="How many were completed by the target deadline?"),
        "tasks_late": st.column_config.NumberColumn("Completed Late", min_value=0, step=1, help="How many were completed past the deadline?"),
        "blocked_tasks": st.column_config.NumberColumn("Blocked Tasks", min_value=0, step=1, help="How many tasks are stuck waiting on something else?"),
        "avg_quality_1_to_5": st.column_config.NumberColumn("Quality Avg (1-5)", min_value=0.0, max_value=5.0, step=0.1, help="Rate the quality of their work output."),
        "meetings_required": st.column_config.NumberColumn("Meetings Required", min_value=0, step=1, help="How many meetings should they have attended?"),
        "meetings_attended": st.column_config.NumberColumn("Meetings Attended", min_value=0, step=1, help="How many meetings did they actually show up to?"),
        "pm_confidence_1_to_5": st.column_config.NumberColumn("PM Confidence (1-5)", min_value=1.0, max_value=5.0, step=0.5, help="Your personal trust in their current trajectory."),
        "communication_score": st.column_config.NumberColumn("Comm Score (1-5)", min_value=0.0, max_value=5.0, step=0.5, help="Responsiveness, clarity, and teamwork."),
        "notes": st.column_config.TextColumn("Notes / Blockers", help="Any external flags, context, or praise."),
    }

    col_config_locked = col_config_base.copy()
    col_config_locked["member_name"] = st.column_config.TextColumn("Member Name", disabled=True, help="Edit names in the Assignment tab")

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    c_title, c_help = st.columns([10, 1])
    with c_title:
        st.subheader("Member weekly rows")
    with c_help:
        with st.popover("ⓘ Help"):
            st.markdown("""
            **Data Entry Guide**

            **◈ 1. Assignment**
            * **Member Name:** Identity (Required).
            * **Role:** Subteam or project focus.
            * **Tasks Assigned:** Workload given this week.
            * **Hours Logged:** Estimated time spent executing.

            **◈ 2. Execution**
            * **Tasks Completed:** Total tickets finished.
            * **Completed On Time:** Delivered before the deadline.
            * **Completed Late:** Delivered after the deadline.
            * **Blocked Tasks:** Stuck waiting on someone else.

            **◈ 3. Performance**
            * **Quality (1-5):** How good was the output? (5=Perfect)
            * **Meetings:** Required to attend vs. actually attended.
            * **PM Confidence (1-5):** Your trust in their current trajectory.
            * **Comm Score (1-5):** Responsiveness and team clarity.
            * **Notes:** Blockers, praise, or internal flags.
            """)

    st.info("ⓘ Type freely in any tab. Click Save Progress to store the draft in Google Sheets by Competition + PM + Division + Week.")

    with st.form("weekly_data_form"):
        tab1, tab2, tab3 = st.tabs(["◈ 1. Assignment", "◈ 2. Execution", "◈ 3. Performance"])

        with tab1:
            df1 = st.data_editor(
                st.session_state.tracker_df[["member_name", "role", "tasks_assigned", "hours_invested"]],
                key="editor_tab1",
                use_container_width=True,
                hide_index=True,
                height=480, 
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
        submit_edits = st.form_submit_button("☑ Save Cloud Draft & Update Preview Below", type="primary", use_container_width=True)

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

    success_message = st.session_state.pop("show_success", False)
    if success_message:
        st.success(f"ⓘ {success_message}")
    warning_message = st.session_state.pop("show_warning", False)
    if warning_message:
        st.warning(f"⚠ {warning_message}")
    if st.session_state.get("show_save_error"):
        st.error(f"⚠ Draft save failed: {st.session_state.pop('show_save_error')}")

    st.markdown('</div>', unsafe_allow_html=True)

    rows = st.session_state.tracker_df.fillna("").to_dict(orient="records")
    report = make_report(pm_name=pm_name, division=division, week_start=week_start, rows=rows)
    report["competition"] = competition 
    preview = pd.DataFrame(report["records"])

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.subheader("Auto-calculated preview")
    if preview.empty:
        st.info("ⓘ No real rows yet. Add at least one member name in the 'Assignment' tab and click Save to preview metrics.")
    else:
        visible = preview[
            [
                "member_name", "role", "completion_score", "quality_score",
                "delivery_score", "attendance_score", "confidence_score",
                "performance_pct", "status", "flags", "notes",
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
        st.success(f"ⓘ {sheet_msg}")
    else:
        st.error(f"⚠ {sheet_msg}")

    replace_existing = st.checkbox(
        f"Replace any previous rows for {competition} / {pm_name} / {division} / {week_start}",
        value=True,
    )

    col_a, col_b = st.columns([1, 2])
    with col_a:
        save_clicked = st.button(f"► Final Submit to Google Sheets", type="primary", use_container_width=True)
    with col_b:
        st.code(st.secrets.get("SHEET_NAME", "AV PM Reports Database"), language="text")

    if save_clicked:
        if not pm_name.strip():
            st.error("⚠ Falta el nombre del PM.")
        elif preview.empty:
            st.error("⚠ No hay miembros válidos para exportar.")
        elif not sheet_ok:
            st.error("⚠ Google Sheets is not configured yet. Check Streamlit Secrets.")
        else:
            try:
                rows_written, rows_deleted = append_report_to_sheet(report, rows, competition, replace_existing=replace_existing)
                st.success(f"ⓘ Submitted {rows_written} member row(s) to Google Sheets.")
                if rows_deleted:
                    st.info(f"ⓘ Replaced {rows_deleted} old row(s) for {competition} / {pm_name} / {division} / {week_start}.")
                st.cache_data.clear()

                try:
                    deleted_drafts = delete_cloud_draft(competition, pm_name, division, week_start)
                    if deleted_drafts:
                        st.info(f"ⓘ Cleared {deleted_drafts} cloud draft row(s).")
                except Exception as draft_exc:
                    st.warning(f"⚠ Submitted successfully, but cloud draft cleanup failed: {draft_exc}")
                if draft_path.exists():
                    os.remove(draft_path)
            except Exception as exc:
                st.error(f"⚠ Google Sheets submit failed: {exc}")

    json_bytes = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button(
        "Download backup JSON",
        data=json_bytes,
        file_name=f"{report['iso_year']}-W{report['iso_week']:02d}_{competition}_{division.replace(' ', '_').replace('&', 'and')}_weekly_report.json",
        mime="application/json",
        use_container_width=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)


elif current_page == "◫ Content Calendar":
    # -----------------------------------------------------------------------------
    # PAGE: CONTENT CALENDAR
    # -----------------------------------------------------------------------------
    if "cc_pm_month" not in st.session_state:
        st.session_state.cc_pm_month = calendar.month_name[date.today().month]
    if "cc_pm_year" not in st.session_state:
        st.session_state.cc_pm_year = date.today().year

    def cc_prev_month():
        m_idx = MONTHS_LIST.index(st.session_state.cc_pm_month) + 1
        y = int(st.session_state.cc_pm_year)
        if m_idx == 1:
            m_idx = 12
            y -= 1
        else:
            m_idx -= 1
        st.session_state.cc_pm_month = calendar.month_name[m_idx]
        st.session_state.cc_pm_year = y

    def cc_next_month():
        m_idx = MONTHS_LIST.index(st.session_state.cc_pm_month) + 1
        y = int(st.session_state.cc_pm_year)
        if m_idx == 12:
            m_idx = 1
            y += 1
        else:
            m_idx += 1
        st.session_state.cc_pm_month = calendar.month_name[m_idx]
        st.session_state.cc_pm_year = y

    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-content">
            <div class="av-logo-container">
                <div class="av-logo"><span class="a">A</span><span class="v">V</span></div>
                <div>
                    <div class="eyebrow">Project AV • Planning</div>
                    <div class="title">Content Calendar</div>
                </div>
            </div>
            <div class="subtitle" style="margin-top: 10px;">
              Plan and track outreach/social media execution by mission, month, and platform. 
              The Master Dashboard evaluates planned vs actual execution natively.
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True
    )

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    cal_mission = c1.selectbox("Mission", ["General", "Mars", "Luna"], index=0)
    cal_cycle = c2.selectbox("Cycle", DYNAMIC_CYCLES, index=1)
    
    cal_month = c3.selectbox("Month", MONTHS_LIST, key="cc_pm_month")
    
    current_year = date.today().year
    year_options = [current_year - 1, current_year, current_year + 1, current_year + 2]
    cal_year = c4.selectbox("Year", year_options, key="cc_pm_year")
    st.markdown('</div>', unsafe_allow_html=True)
    
    if st.button("↻ Refresh from Google Sheets"):
        load_content_calendar.clear()
        
    full_cal_df = load_content_calendar()
    
    if not full_cal_df.empty:
        full_cal_df["temp_dt"] = pd.to_datetime(full_cal_df["planned_date"], errors="coerce")
        month_idx = MONTHS_LIST.index(cal_month) + 1
        
        mask = (
            (full_cal_df["mission"] == cal_mission) & 
            (full_cal_df["cycle"] == cal_cycle) & 
            (full_cal_df["temp_dt"].dt.month == month_idx) &
            (full_cal_df["temp_dt"].dt.year == cal_year)
        )
        active_df = full_cal_df[mask].drop(columns=["temp_dt"]).copy()
    else:
        active_df = pd.DataFrame(columns=CONTENT_CAL_COLUMNS)

    # Execution Tracker
    st.markdown("### ⌖ Execution Tracker")
    total_planned = len(active_df)
    posted = len(active_df[active_df["status"] == "Posted"])
    missed = len(active_df[active_df["status"] == "Missed"])
    pending = len(active_df[active_df["status"].isin(["Planned", "In Progress", "Rescheduled"])])
    
    late_count = 0
    if not active_df.empty:
        posted_df = active_df[active_df["status"] == "Posted"]
        p_dates = pd.to_datetime(posted_df["planned_date"], errors="coerce")
        a_dates = pd.to_datetime(posted_df["actual_posted_date"], errors="coerce")
        late_count = len(posted_df[a_dates > p_dates])
        
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Planned Items", total_planned)
    m2.metric("Posted", posted)
    m3.metric("Missed", missed)
    m4.metric("Pending", pending)
    m5.metric("Posted Late", late_count)

    st.divider()
    
    # --- VISUAL MONTHLY CALENDAR ---
    c_prev, c_title, c_next = st.columns([1, 6, 1])
    with c_prev:
        st.button("◀ Prev", on_click=cc_prev_month, use_container_width=True)
    with c_title:
        st.markdown(f"<h3 style='text-align:center; margin-top:0;'>◫ {cal_month} {cal_year}</h3>", unsafe_allow_html=True)
    with c_next:
        st.button("Next ▶", on_click=cc_next_month, use_container_width=True)
    
    month_idx = MONTHS_LIST.index(cal_month) + 1
    cal = calendar.monthcalendar(cal_year, month_idx)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    cols = st.columns(7)
    for i, d_name in enumerate(day_names):
        cols[i].markdown(f"<div style='text-align:center; color:#94a3b8; font-weight:800; font-size:14px; margin-bottom:8px;'>{d_name}</div>", unsafe_allow_html=True)
        
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].markdown("<div class='cal-day empty'></div>", unsafe_allow_html=True)
            else:
                date_str = f"{cal_year}-{month_idx:02d}-{day:02d}"
                day_items = active_df[active_df["planned_date"] == date_str]
                
                content_html = ""
                for _, item in day_items.iterrows():
                    platform = item.get("platform", "Other")
                    title = item.get("content_title", "Untitled")
                    status = item.get("status", "Planned")
                    
                    bg_color = PLATFORM_COLORS.get(platform, "#94a3b8")
                    symbol = STATUS_SYMBOLS.get(status, "◌")
                    
                    content_html += f"<div class='cal-badge' style='background:{bg_color};' title='{title}'>{symbol} {platform}</div>"
                    
                cols[i].markdown(f"""
                <div class='cal-day'>
                    <div class='cal-date'>{day}</div>
                    {content_html}
                </div>
                """, unsafe_allow_html=True)

    st.divider()

    # --- CONTENT EDITOR ---
    st.markdown("### ▦ Content Editor")
    st.markdown('<div class="chart-desc">ⓘ Edit rows directly. To add a new event, scroll to the bottom and click the empty row. Marking an item as "Posted" will automatically timestamp the execution.</div>', unsafe_allow_html=True)
    
    edit_cols = ["content_id", "planned_date", "platform", "content_title", "description", "content_type", "owner", "status", "actual_posted_date", "notes"]
    display_df = active_df[edit_cols].copy()
    
    blank_rows = []
    for _ in range(3):
        blank_rows.append({"status": "Planned", "platform": "Instagram"})
    display_df = pd.concat([display_df, pd.DataFrame(blank_rows)], ignore_index=True)
    
    display_df["planned_date"] = pd.to_datetime(display_df["planned_date"], errors="coerce").dt.date
    display_df["actual_posted_date"] = pd.to_datetime(display_df["actual_posted_date"], errors="coerce").dt.date
    
    config = {
        "content_id": None, 
        "planned_date": st.column_config.DateColumn("Planned Date", format="YYYY-MM-DD", help="Date the content is scheduled to go live."),
        "platform": st.column_config.SelectboxColumn("Platform", options=list(PLATFORM_COLORS.keys()), help="Target platform for the content."),
        "content_title": st.column_config.TextColumn("Title", help="Short name or headline for the content."),
        "description": st.column_config.TextColumn("Description", help="Caption, draft, or key points."),
        "content_type": st.column_config.TextColumn("Content Type", help="Format of the content (e.g., Reel, Carousel, Newsletter)."),
        "owner": st.column_config.TextColumn("Owner", help="Team member responsible for this content."),
        "status": st.column_config.SelectboxColumn("Status", options=list(STATUS_SYMBOLS.keys()), help="Current state. Marking as 'Posted' automatically sets actual dates."),
        "actual_posted_date": st.column_config.DateColumn("Actual Posted", format="YYYY-MM-DD", help="When it actually went live. Auto-fills when status is Posted."),
        "notes": st.column_config.TextColumn("Notes", help="Links to assets, final URLs, or comments."),
    }
    
    edited_view = st.data_editor(display_df, num_rows="dynamic", use_container_width=True, height=500, column_config=config)
    
    if st.button("☑ Save Content Calendar", type="primary"):
        final_save_df = edited_view.copy()
        
        meta_cols = ["content_id", "marked_done_at", "created_at"]
        if not active_df.empty:
            meta_df = active_df[meta_cols].dropna(subset=["content_id"])
            final_save_df = pd.merge(final_save_df, meta_df, on="content_id", how="left")
            
        final_save_df["planned_date"] = pd.to_datetime(final_save_df["planned_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
        final_save_df["actual_posted_date"] = pd.to_datetime(final_save_df["actual_posted_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
        
        for c in CONTENT_CAL_COLUMNS:
            if c not in final_save_df.columns:
                final_save_df[c] = ""
                
        save_content_calendar_month(final_save_df, cal_mission, cal_cycle, cal_month, cal_year)
        st.success(f"ⓘ Successfully saved Content Calendar for {cal_mission} ({cal_month} {cal_year}).")
        load_content_calendar.clear()
        st.rerun()


elif current_page == "$ Fundraising & Finance":
    # -----------------------------------------------------------------------------
    # PAGE: FUNDRAISING & FINANCE
    # -----------------------------------------------------------------------------
    
    @st.cache_data(ttl=60, show_spinner=False)
    def load_finance_sheet(sheet_name: str, headers: list[str]) -> pd.DataFrame:
        worksheet = get_or_create_worksheet(sheet_name, headers, rows=1000)
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=headers)
        df = pd.DataFrame(records)
        for col in headers:
            if col not in df.columns:
                df[col] = ""
        return df

    def save_finance_sheet(sheet_name: str, df_edited: pd.DataFrame, headers: list[str], id_col: str, mission: str, cycle: str):
        worksheet = get_or_create_worksheet(sheet_name, headers, rows=1000)
        df_all = pd.DataFrame(worksheet.get_all_records())
        if df_all.empty:
            df_all = pd.DataFrame(columns=headers)
            
        if not df_all.empty and "mission" in df_all.columns and "cycle" in df_all.columns:
            mask = (df_all["mission"] == mission) & (df_all["cycle"] == cycle)
            df_all = df_all[~mask]
            
        now_str = datetime.utcnow().isoformat() + "Z"
        
        clean_edited = []
        for _, row in df_edited.iterrows():
            r = row.to_dict()
            
            if not str(r.get(id_col, "")) and not str(r.get("event_name", "")) and not str(r.get("amount", "")) and not str(r.get("goal_name", "")):
                continue
                
            if not str(r.get(id_col, "")):
                r[id_col] = f"{mission}_{cycle}_{uuid.uuid4().hex[:8]}"
                r["created_at"] = now_str
                
            r["mission"] = mission
            r["cycle"] = cycle
            r["updated_at"] = now_str
            clean_edited.append(r)
            
        df_new = pd.DataFrame(clean_edited)
        if not df_new.empty:
            for col in headers:
                if col not in df_new.columns:
                    df_new[col] = ""
            df_all = pd.concat([df_all, df_new], ignore_index=True)
            
        df_all = df_all.fillna("").astype(str).replace(["NaT", "nan", "None", "<NA>", "False"], "")
        
        data = [headers] + df_all[headers].values.tolist()
        worksheet.clear()
        worksheet.append_rows(data, value_input_option="USER_ENTERED")

    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-content">
            <div class="av-logo-container">
                <div class="av-logo"><span class="a">A</span><span class="v">V</span></div>
                <div>
                    <div class="eyebrow">Project AV • Financial Administration</div>
                    <div class="title">Fundraising & Finance</div>
                </div>
            </div>
            <div class="subtitle" style="margin-top: 10px;">
              Plan fundraising activities, record revenue and expenses, and track financial performance across Project AV.
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True
    )
    
    st.markdown('<div class="glass">', unsafe_allow_html=True)
    f1, f2, f3, f4 = st.columns(4)
    fin_mission = f1.selectbox("Mission Filter", ["General", "Mars", "Luna"], index=0)
    fin_cycle = f2.selectbox("Cycle Filter", DYNAMIC_CYCLES, index=1)
    
    current_month_index = date.today().month - 1
    fin_month = f3.selectbox("Month Filter", MONTHS_LIST, index=current_month_index, key="fin_month")
    
    current_year = date.today().year
    fin_year = f4.selectbox("Year Filter", [current_year - 1, current_year, current_year + 1, current_year + 2], index=1, key="fin_year")
    st.markdown('</div>', unsafe_allow_html=True)

    if st.button("↻ Refresh Finance Data"):
        load_finance_sheet.clear()
        
    events_raw = load_finance_sheet("fundraising_events", EVENTS_HEADERS)
    trans_raw = load_finance_sheet("fundraising_transactions", TRANSACTIONS_HEADERS)
    exp_raw = load_finance_sheet("fundraising_expenses", EXPENSES_HEADERS)
    goals_raw = load_finance_sheet("fundraising_goals", GOALS_HEADERS)
    
    events_df = events_raw[(events_raw["mission"] == fin_mission) & (events_raw["cycle"] == fin_cycle)].copy() if not events_raw.empty else pd.DataFrame(columns=EVENTS_HEADERS)
    trans_df = trans_raw[(trans_raw["mission"] == fin_mission) & (trans_raw["cycle"] == fin_cycle)].copy() if not trans_raw.empty else pd.DataFrame(columns=TRANSACTIONS_HEADERS)
    exp_df = exp_raw[(exp_raw["mission"] == fin_mission) & (exp_raw["cycle"] == fin_cycle)].copy() if not exp_raw.empty else pd.DataFrame(columns=EXPENSES_HEADERS)
    goals_df = goals_raw[(goals_raw["mission"] == fin_mission) & (goals_raw["cycle"] == fin_cycle)].copy() if not goals_raw.empty else pd.DataFrame(columns=GOALS_HEADERS)

    # Autocalculate Actuals logic
    if not trans_df.empty:
        trans_df["amount"] = pd.to_numeric(trans_df["amount"], errors="coerce").fillna(0)
        trans_sums = trans_df.groupby("event_id")["amount"].sum()
    else:
        trans_sums = pd.Series()
        
    if not exp_df.empty:
        exp_df["amount"] = pd.to_numeric(exp_df["amount"], errors="coerce").fillna(0)
        exp_sums = exp_df.groupby("event_id")["amount"].sum()
    else:
        exp_sums = pd.Series()

    if not events_df.empty:
        for idx, row in events_df.iterrows():
            eid = row.get("event_id")
            g = trans_sums.get(eid, 0.0)
            e = exp_sums.get(eid, 0.0)
            
            events_df.at[idx, "actual_gross_revenue"] = g
            events_df.at[idx, "actual_expenses"] = e
            events_df.at[idx, "actual_net_revenue"] = g - e
            
            exp_g = float(row.get("expected_gross_revenue") or 0)
            exp_e = float(row.get("expected_expenses") or 0)
            events_df.at[idx, "expected_net_revenue"] = exp_g - exp_e

    # Build dropdown options
    event_options = []
    if not events_df.empty:
        for _, row in events_df.iterrows():
            if str(row.get("event_name", "")).strip():
                event_options.append(str(row["event_name"]))
    if not event_options:
        event_options = ["None"]

    tab_cal, tab_evt, tab_txn, tab_exp, tab_goal, tab_analytics = st.tabs([
        "◫ Calendar Preview", "◈ Events", "▦ Transactions", "▦ Expenses", "⊙ Goals", "⌁ Analytics"
    ])

    with tab_cal:
        st.markdown(f"### ◫ {fin_month} {fin_year}")
        month_idx = MONTHS_LIST.index(fin_month) + 1
        cal_grid = calendar.monthcalendar(fin_year, month_idx)
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
                    date_str = f"{fin_year}-{month_idx:02d}-{day:02d}"
                    content_html = ""
                    
                    if not events_df.empty:
                        day_items = events_df[events_df["planned_date"] == date_str]
                        for _, item in day_items.iterrows():
                            title = item.get("event_name", "Unnamed Event")
                            status = item.get("status", "Planned")
                            ex_net = float(item.get("expected_net_revenue") or 0)
                            ac_net = float(item.get("actual_net_revenue") or 0)
                            
                            if status == "Completed":
                                badge_text = f"{title} (${ac_net:,.0f} net)"
                                bg_color = "#22c55e" # green
                            else:
                                badge_text = f"{title} (Est: ${ex_net:,.0f})"
                                bg_color = "#3b82f6" # blue
                                
                            content_html += f"<div class='cal-badge' style='background:{bg_color}; color:#fff;' title='{status}'>{badge_text}</div>"
                    
                    cols[i].markdown(f"""
                    <div class='cal-day'>
                        <div class='cal-date'>{day}</div>
                        {content_html}
                    </div>
                    """, unsafe_allow_html=True)
        st.divider()

    with tab_evt:
        st.markdown("### ◈ Event Management")
        st.markdown('<div class="chart-desc">ⓘ Create and manage fundraising initiatives. Net revenues will auto-calculate based on saved transactions and expenses.</div>', unsafe_allow_html=True)
        
        evt_cols = ["event_id", "event_name", "event_type", "planned_date", "actual_date", "location", "status", "expected_gross_revenue", "expected_expenses", "venue_confirmed", "permits_completed", "marketing_ready", "volunteers_ready"]
        evt_view = events_df[evt_cols].copy() if not events_df.empty else pd.DataFrame(columns=evt_cols)
        
        pad = []
        for _ in range(3): pad.append({"status": "Planned", "event_type": "Other", "expected_gross_revenue": 0, "expected_expenses": 0})
        evt_view = pd.concat([evt_view, pd.DataFrame(pad)], ignore_index=True)
        
        evt_view["planned_date"] = pd.to_datetime(evt_view["planned_date"], errors="coerce").dt.date
        evt_view["actual_date"] = pd.to_datetime(evt_view["actual_date"], errors="coerce").dt.date
        
        config = {
            "event_id": None, 
            "event_name": st.column_config.TextColumn("Event Name", help="Name of the fundraising activity."),
            "planned_date": st.column_config.DateColumn("Planned Date", format="YYYY-MM-DD", help="When the event is scheduled."),
            "actual_date": st.column_config.DateColumn("Actual Date", format="YYYY-MM-DD", help="When the event actually occurred."),
            "event_type": st.column_config.SelectboxColumn("Type", options=["Food Sale", "Raffle", "Sponsorship", "Donation", "Venue Fundraiser", "Online Campaign", "Community Event", "Other"], help="Category of the fundraiser."),
            "location": st.column_config.TextColumn("Location", help="Physical or virtual venue."),
            "status": st.column_config.SelectboxColumn("Status", options=["Planned", "In Progress", "Completed", "Cancelled", "Delayed", "Needs Follow-Up"], help="Current operational phase."),
            "expected_gross_revenue": st.column_config.NumberColumn("Exp. Revenue $", help="Estimated total income before expenses."),
            "expected_expenses": st.column_config.NumberColumn("Exp. Cost $", help="Estimated total cost to run the event."),
            "venue_confirmed": st.column_config.CheckboxColumn("Venue", help="Is the location secured?"),
            "permits_completed": st.column_config.CheckboxColumn("Permits", help="Are all legal/campus permits approved?"),
            "marketing_ready": st.column_config.CheckboxColumn("Marketing", help="Are flyers/social posts ready?"),
            "volunteers_ready": st.column_config.CheckboxColumn("Vols", help="Is the team staffing finalized?"),
        }
        
        edited_evt = st.data_editor(evt_view, num_rows="dynamic", use_container_width=True, height=450, column_config=config)
        
        if st.button("☑ Save Events", type="primary"):
            final = edited_evt.copy()
            meta_cols = ["event_id", "created_at", "actual_gross_revenue", "actual_expenses", "actual_net_revenue", "expected_net_revenue"]
            if not events_df.empty:
                meta = events_df[[c for c in meta_cols if c in events_df.columns]].dropna(subset=["event_id"])
                final = pd.merge(final, meta, on="event_id", how="left")
            
            final["planned_date"] = pd.to_datetime(final["planned_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            final["actual_date"] = pd.to_datetime(final["actual_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            save_finance_sheet("fundraising_events", final, EVENTS_HEADERS, "event_id", fin_mission, fin_cycle)
            st.success("ⓘ Events saved.")
            load_finance_sheet.clear()
            st.rerun()

    with tab_txn:
        st.markdown("### ▦ Income Transactions")
        st.markdown('<div class="chart-desc">ⓘ Record all money received. These values will automatically aggregate to calculate Event Gross Revenue.</div>', unsafe_allow_html=True)
        
        txn_cols = ["transaction_id", "event_name", "transaction_date", "source_type", "source_name", "payment_method", "amount", "deposited"]
        txn_view = trans_df[txn_cols].copy() if not trans_df.empty else pd.DataFrame(columns=txn_cols)
        
        pad = []
        for _ in range(3): pad.append({"source_type": "Other", "payment_method": "Cash", "amount": 0})
        txn_view = pd.concat([txn_view, pd.DataFrame(pad)], ignore_index=True)
        txn_view["transaction_date"] = pd.to_datetime(txn_view["transaction_date"], errors="coerce").dt.date
        
        config = {
            "transaction_id": None, 
            "transaction_date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", help="Date the money was received."),
            "event_name": st.column_config.SelectboxColumn("Linked Event", options=event_options, help="Which event generated this income?"),
            "source_type": st.column_config.SelectboxColumn("Source", options=["Individual", "Sponsor", "Ticket Sale", "Raffle Sale", "Food Sale", "Online Donation", "Cash Donation", "Other"], help="Who or what provided the funds?"),
            "source_name": st.column_config.TextColumn("Source Name", help="Name of the person/sponsor (optional)."),
            "payment_method": st.column_config.SelectboxColumn("Method", options=["ATH Movil", "Cash", "PayPal", "Check", "Bank Transfer", "Card", "Other"], help="How was it paid?"),
            "amount": st.column_config.NumberColumn("Amount $", help="Gross amount received."),
            "deposited": st.column_config.CheckboxColumn("Deposited?", help="Has this hit the main bank account?"),
        }
        
        edited_txn = st.data_editor(txn_view, num_rows="dynamic", use_container_width=True, height=450, column_config=config)
        
        if st.button("☑ Save Transactions", type="primary"):
            final = edited_txn.copy()
            meta_cols = ["transaction_id", "created_at"]
            if not trans_df.empty:
                meta = trans_df[[c for c in meta_cols if c in trans_df.columns]].dropna(subset=["transaction_id"])
                final = pd.merge(final, meta, on="transaction_id", how="left")
            
            name_to_id = dict(zip(events_df["event_name"], events_df["event_id"])) if not events_df.empty else {}
            final["event_id"] = final["event_name"].map(name_to_id).fillna("")
            
            final["transaction_date"] = pd.to_datetime(final["transaction_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            save_finance_sheet("fundraising_transactions", final, TRANSACTIONS_HEADERS, "transaction_id", fin_mission, fin_cycle)
            st.success("ⓘ Transactions saved.")
            load_finance_sheet.clear()
            st.rerun()

    with tab_exp:
        st.markdown("### ▦ Expenses")
        st.markdown('<div class="chart-desc">ⓘ Record all money spent. These values will automatically aggregate to calculate Event Net Revenue.</div>', unsafe_allow_html=True)
        
        exp_cols = ["expense_id", "event_name", "expense_date", "vendor", "item_description", "category", "amount", "reimbursed"]
        exp_view = exp_df[exp_cols].copy() if not exp_df.empty else pd.DataFrame(columns=exp_cols)
        
        pad = []
        for _ in range(3): pad.append({"category": "Other", "amount": 0})
        exp_view = pd.concat([exp_view, pd.DataFrame(pad)], ignore_index=True)
        exp_view["expense_date"] = pd.to_datetime(exp_view["expense_date"], errors="coerce").dt.date
        
        config = {
            "expense_id": None, 
            "expense_date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", help="Date the purchase was made."),
            "event_name": st.column_config.SelectboxColumn("Linked Event", options=event_options, help="Which event is this cost for?"),
            "vendor": st.column_config.TextColumn("Vendor", help="Store or supplier name."),
            "item_description": st.column_config.TextColumn("Item", help="What was bought?"),
            "category": st.column_config.SelectboxColumn("Category", options=["Food / Materials", "Venue", "Marketing", "Equipment", "Transportation", "Permit", "Prize", "Supplies", "Other"], help="Type of expense."),
            "amount": st.column_config.NumberColumn("Amount $", help="Total cost paid."),
            "reimbursed": st.column_config.CheckboxColumn("Reimbursed?", help="Has the purchaser been paid back?"),
        }
        
        edited_exp = st.data_editor(exp_view, num_rows="dynamic", use_container_width=True, height=450, column_config=config)
        
        if st.button("☑ Save Expenses", type="primary"):
            final = edited_exp.copy()
            meta_cols = ["expense_id", "created_at"]
            if not exp_df.empty:
                meta = exp_df[[c for c in meta_cols if c in exp_df.columns]].dropna(subset=["expense_id"])
                final = pd.merge(final, meta, on="expense_id", how="left")
                
            name_to_id = dict(zip(events_df["event_name"], events_df["event_id"])) if not events_df.empty else {}
            final["event_id"] = final["event_name"].map(name_to_id).fillna("")
            
            final["expense_date"] = pd.to_datetime(final["expense_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            save_finance_sheet("fundraising_expenses", final, EXPENSES_HEADERS, "expense_id", fin_mission, fin_cycle)
            st.success("ⓘ Expenses saved.")
            load_finance_sheet.clear()
            st.rerun()

    with tab_goal:
        st.markdown("### ⊙ Organizational Goals")
        st.markdown('<div class="chart-desc">ⓘ Set macro financial targets to measure total fundraising success against.</div>', unsafe_allow_html=True)
        
        goal_cols = ["goal_id", "goal_name", "target_amount", "deadline", "purpose", "status"]
        goal_view = goals_df[goal_cols].copy() if not goals_df.empty else pd.DataFrame(columns=goal_cols)
        
        pad = []
        for _ in range(1): pad.append({"status": "In Progress", "target_amount": 0})
        goal_view = pd.concat([goal_view, pd.DataFrame(pad)], ignore_index=True)
        goal_view["deadline"] = pd.to_datetime(goal_view["deadline"], errors="coerce").dt.date
        
        config = {
            "goal_id": None, 
            "goal_name": st.column_config.TextColumn("Goal Name", help="Name of the fundraising target."),
            "purpose": st.column_config.TextColumn("Purpose", help="Why are we raising this money?"),
            "deadline": st.column_config.DateColumn("Deadline", format="YYYY-MM-DD", help="When do we need the funds by?"),
            "status": st.column_config.SelectboxColumn("Status", options=["Planned", "In Progress", "Achieved", "Missed"], help="Current standing."),
            "target_amount": st.column_config.NumberColumn("Target $", help="Total amount needed."),
        }
        
        edited_goal = st.data_editor(goal_view, num_rows="dynamic", use_container_width=True, height=250, column_config=config)
        
        if st.button("☑ Save Goals", type="primary"):
            final = edited_goal.copy()
            meta_cols = ["goal_id", "created_at"]
            if not goals_df.empty:
                meta = goals_df[[c for c in meta_cols if c in goals_df.columns]].dropna(subset=["goal_id"])
                final = pd.merge(final, meta, on="goal_id", how="left")
                
            final["deadline"] = pd.to_datetime(final["deadline"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            save_finance_sheet("fundraising_goals", final, GOALS_HEADERS, "goal_id", fin_mission, fin_cycle)
            st.success("ⓘ Goals saved.")
            load_finance_sheet.clear()
            st.rerun()

    with tab_analytics:
        st.markdown("### ⌁ Financial Analytics Dashboard")
        
        t_gross = events_df["actual_gross_revenue"].sum() if not events_df.empty else 0.0
        t_exp = events_df["actual_expenses"].sum() if not events_df.empty else 0.0
        t_net = t_gross - t_exp
        
        t_goal = 0.0
        if not goals_df.empty:
            goals_df["target_amount"] = pd.to_numeric(goals_df["target_amount"], errors="coerce").fillna(0)
            t_goal = goals_df["target_amount"].sum()
            
        progress_pct = (t_net / t_goal * 100) if t_goal > 0 else 0.0
        remaining = max(0, t_goal - t_net)
        
        best_event = "—"
        worst_event = "—"
        if not events_df.empty and t_gross > 0:
            best_event = events_df.loc[events_df["actual_net_revenue"].idxmax()]["event_name"]
            worst_event = events_df.loc[events_df["actual_expenses"].idxmax()]["event_name"]
            
        cost_per_dlr = (t_exp / t_gross) if t_gross > 0 else 0.0
        roi = (t_gross / t_exp * 100) if t_exp > 0 else 0.0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Gross Revenue", f"${t_gross:,.2f}")
        m2.metric("Total Expenses", f"${t_exp:,.2f}")
        m3.metric("Total Net Revenue", f"${t_net:,.2f}")
        m4.metric("Goal Progress", f"{progress_pct:.1f}%")
        
        m5, m6, m7, m8 = st.columns(4)
        m5.metric("Remaining to Goal", f"${remaining:,.2f}")
        m6.metric("Best Event (Net)", best_event)
        m7.metric("Cost per $1 Raised", f"${cost_per_dlr:.2f}")
        m8.metric("ROI", f"{roi:.0f}%" if t_exp > 0 else "—")
        
        st.divider()
        
        c1, c2 = st.columns([1, 1])
        with c1:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown("##### Goal Progress")
            fig_g = go.Figure(go.Indicator(
                mode = "gauge+number",
                value = t_net,
                title = {'text': "Net Revenue vs Target"},
                gauge = {
                    'axis': {'range': [0, max(t_goal, t_net, 1)]},
                    'bar': {'color': "#22c55e"},
                    'steps': [{'range': [0, t_goal], 'color': "rgba(255,255,255,0.1)"}],
                    'threshold': {'line': {'color': "white", 'width': 4}, 'thickness': 0.75, 'value': t_goal}
                }
            ))
            fig_g.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#f8fafc"))
            st.plotly_chart(fig_g, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with c2:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown("##### Planned vs Actual Net by Event")
            if not events_df.empty:
                comp_df = events_df[["event_name", "expected_net_revenue", "actual_net_revenue"]].dropna(subset=["event_name"])
                fig_comp = go.Figure()
                fig_comp.add_trace(go.Bar(x=comp_df["event_name"], y=comp_df["expected_net_revenue"], name="Expected", marker_color="rgba(255,255,255,0.2)"))
                fig_comp.add_trace(go.Bar(x=comp_df["event_name"], y=comp_df["actual_net_revenue"], name="Actual", marker_color=primary))
                fig_comp.update_layout(barmode='group', height=300, margin=dict(l=20, r=20, t=40, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#f8fafc"))
                st.plotly_chart(fig_comp, use_container_width=True)
            else:
                st.info("ⓘ No events to display.")
            st.markdown('</div>', unsafe_allow_html=True)
            
        c3, c4 = st.columns([1, 1])
        with c3:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown("##### Revenue by Payment Method")
            if not trans_df.empty:
                pm_df = trans_df.groupby("payment_method")["amount"].sum().reset_index()
                fig_pm = px.pie(pm_df, values="amount", names="payment_method", hole=0.4)
                fig_pm.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#f8fafc"))
                st.plotly_chart(fig_pm, use_container_width=True)
            else:
                st.info("ⓘ No transactions to display.")
            st.markdown('</div>', unsafe_allow_html=True)
            
        with c4:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown("##### Event Status Breakdown")
            if not events_df.empty:
                st_df = events_df["status"].value_counts().reset_index()
                st_df.columns = ["status", "count"]
                fig_st = px.bar(st_df, x="status", y="count", color="status")
                fig_st.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, font=dict(color="#f8fafc"))
                st.plotly_chart(fig_st, use_container_width=True)
            else:
                st.info("ⓘ No events to display.")
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown("##### ◈ Fundraiser Report Card")
        sel_evt = st.selectbox("Select Event to View", options=event_options)
        if sel_evt != "None" and not events_df.empty:
            evt_row = events_df[events_df["event_name"] == sel_evt].iloc[0]
            
            p_date = evt_row.get("planned_date", "—")
            a_date = evt_row.get("actual_date", "—")
            e_net = float(evt_row.get("expected_net_revenue") or 0)
            a_gross = float(evt_row.get("actual_gross_revenue") or 0)
            a_exp = float(evt_row.get("actual_expenses") or 0)
            a_net = float(evt_row.get("actual_net_revenue") or 0)
            diff = a_net - e_net
            
            summary_txt = f"**{sel_evt}** generated **${a_gross:,.2f}** in gross revenue, spent **${a_exp:,.2f}** in expenses, and produced **${a_net:,.2f}** in net profit. "
            if diff >= 0:
                summary_txt += f"This beat the expected net profit by **${diff:,.2f}**."
            else:
                summary_txt += f"This fell short of the expected net profit by **${abs(diff):,.2f}**."
                
            st.info(summary_txt)
            
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Actual Gross", f"${a_gross:,.2f}")
            r2.metric("Actual Expenses", f"${a_exp:,.2f}")
            r3.metric("Actual Net Profit", f"${a_net:,.2f}")
            r4.metric("Variance to Plan", f"${diff:,.2f}")
            
            st.markdown("**Operational Checklist:**")
            v_conf = "☑" if str(evt_row.get("venue_confirmed")).lower() == "true" else "☐"
            p_comp = "☑" if str(evt_row.get("permits_completed")).lower() == "true" else "☐"
            m_read = "☑" if str(evt_row.get("marketing_ready")).lower() == "true" else "☐"
            v_read = "☑" if str(evt_row.get("volunteers_ready")).lower() == "true" else "☐"
            st.markdown(f"{v_conf} Venue | {p_comp} Permits | {m_read} Marketing | {v_read} Volunteers")
        st.markdown('</div>', unsafe_allow_html=True)
