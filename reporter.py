from __future__ import annotations

import calendar
import json
import os
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import gspread
from gspread.exceptions import APIError, WorksheetNotFound
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

PLANNER_TASKS_COLS = [
    "task_id", "mission", "cycle", "division", "bucket", "title", "description", 
    "assigned_to", "cc_people", "created_by", "start_date", "due_date", "completed_date", 
    "status", "priority", "percent_complete", "week_start", "linked_gantt_task", 
    "linked_gantt_phase", "gantt_dependency_type", "blocks_gantt_start", 
    "blocks_gantt_completion", "delay_flag", "delay_days", "late_reason", 
    "deliverable_link", "tags", "created_at", "updated_at"
]

PLANNER_CHECKLIST_COLS = ["checklist_item_id", "task_id", "item_text", "completed", "completed_by", "completed_at", "created_at", "updated_at"]
PLANNER_COMMENTS_COLS = ["comment_id", "task_id", "author", "comment", "created_at"]
PLANNER_MEMBERS_COLS = ["member_id", "member_name", "email", "division", "mission", "role", "active", "notes", "created_at", "updated_at"]
PLANNER_NOTIFICATIONS_COLS = ["notification_id", "task_id", "notification_type", "recipient", "cc_people", "subject", "message", "status", "created_at", "sent_at", "error"]
GANTT_TASK_LINKS_COLS = ["link_id", "mission", "cycle", "planner_task_id", "planner_task_title", "linked_gantt_task", "linked_gantt_phase", "blocks_gantt_start", "blocks_gantt_completion", "delay_flag", "delay_days", "status", "created_at", "updated_at"]

PLATFORM_COLORS = {"No post day": "#ef4444", "Outreach Activity": "#f97316", "LinkedIn": "#eab308", "Email": "#22c55e", "X": "#2dd4bf", "TikTok": "#38bdf8", "Facebook": "#c084fc", "YouTube": "#f43f5e", "Instagram": "#d946ef", "Other": "#94a3b8"}
STATUS_SYMBOLS = {"Planned": "◌", "In Progress": "◐", "Posted": "●", "Missed": "⚠", "Cancelled": "×", "Rescheduled": "↷"}

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

# --- ROBUST SPREADSHEET CACHING & BACKOFF ---
def ensure_worksheet_safe(sh, title, columns):
    """Safely fetches a worksheet, ensuring all columns exist."""
    try:
        ws = sh.worksheet(title)
        headers = ws.row_values(1)
        missing = [c for c in columns if c not in headers]
        if missing:
            new_headers = headers + missing
            ws.update("1:1", [new_headers])
        return ws
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=len(columns))
        ws.update("1:1", [columns])
        return ws

@st.cache_data(ttl=120, show_spinner=False)
def fetch_cached_df(sheet_name: str, columns: list[str], force_refresh: int = 0) -> pd.DataFrame:
    """Fetches a dataframe directly to memory and caches it to prevent API traffic jams."""
    sh = get_spreadsheet()
    for attempt in range(3):
        try:
            ws = ensure_worksheet_safe(sh, sheet_name, columns)
            data = ws.get_all_records()
            if not data:
                df = pd.DataFrame(columns=columns)
            else:
                df = pd.DataFrame(data)
                for c in columns:
                    if c not in df.columns:
                        df[c] = ""
            return df
        except APIError as e:
            if attempt == 2:
                st.error(f"Google Sheets API is overloaded. Failed to load {sheet_name}. Please wait a moment and refresh.")
                raise e
            time.sleep(2.5)
        except Exception as e:
            if attempt == 2:
                raise e
            time.sleep(2.5)

# --- DATA SAVE HELPERS (Flushes cache on save) ---
def save_planner_data(edited_df, original_df, cols, sheet_name, id_col):
    for idx, row in edited_df.iterrows():
        if not row.get(id_col) or pd.isna(row.get(id_col)) or str(row.get(id_col)).strip() == "":
            edited_df.at[idx, id_col] = str(uuid.uuid4())
            edited_df.at[idx, "created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        edited_df.at[idx, "updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if sheet_name == "planner_tasks":
        today = pd.to_datetime(date.today())
        for idx, row in edited_df.iterrows():
            dd = pd.to_datetime(row.get("due_date"), errors="coerce")
            cd = pd.to_datetime(row.get("completed_date"), errors="coerce")
            status = row.get("status", "")
            delay_flag, delay_days = False, 0
            if pd.notnull(dd):
                if status not in ["Completed", "Cancelled"] and today > dd:
                    delay_flag, delay_days = True, (today - dd).days
                elif status == "Completed" and pd.notnull(cd) and cd > dd:
                    delay_flag, delay_days = True, (cd - dd).days
            edited_df.at[idx, "delay_flag"] = delay_flag
            edited_df.at[idx, "delay_days"] = delay_days
    
    for c in cols:
        if c not in edited_df.columns: edited_df[c] = ""
    for col in edited_df.columns:
        if "date" in col.lower() and col not in ["created_at", "updated_at"]:
            edited_df[col] = pd.to_datetime(edited_df[col], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            
    edited_df = edited_df[cols]
    if not original_df.empty:
        merged_df = original_df[~original_df[id_col].isin(edited_df[id_col])].copy()
        merged_df = pd.concat([merged_df, edited_df], ignore_index=True)
    else:
        merged_df = edited_df
        
    merged_df.replace([np.inf, -np.inf], 0, inplace=True)
    merged_df.fillna("", inplace=True)
    
    sh = get_spreadsheet()
    ws = ensure_worksheet_safe(sh, sheet_name, cols)
    ws.clear()
    ws.update("1:1", [merged_df.columns.values.tolist()])
    if not merged_df.empty:
        ws.update("A2", merged_df.values.tolist())
        
    st.cache_data.clear() # Reset cache to prevent stale reads
    st.success(f"ⓘ Saved {sheet_name} successfully.")

def update_gantt_links(edited_tasks, df_links):
    links_to_save = []
    for _, task in edited_tasks.iterrows():
        if task.get("linked_gantt_task"):
            links_to_save.append({
                "link_id": f"link_{task['task_id']}",
                "mission": task.get("mission", ""),
                "cycle": task.get("cycle", ""),
                "planner_task_id": task["task_id"],
                "planner_task_title": task.get("title", ""),
                "linked_gantt_task": task["linked_gantt_task"],
                "linked_gantt_phase": task.get("linked_gantt_phase", ""),
                "blocks_gantt_start": task.get("blocks_gantt_start", False),
                "blocks_gantt_completion": task.get("blocks_gantt_completion", False),
                "delay_flag": task.get("delay_flag", False),
                "delay_days": task.get("delay_days", 0),
                "status": task.get("status", ""),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
    if links_to_save:
        new_links_df = pd.DataFrame(links_to_save)
        for c in GANTT_TASK_LINKS_COLS:
            if c not in new_links_df.columns:
                new_links_df[c] = ""
        new_links_df = new_links_df[GANTT_TASK_LINKS_COLS]
        
        if not df_links.empty:
            merged_links = df_links[~df_links["link_id"].isin(new_links_df["link_id"])].copy()
            merged_links = pd.concat([merged_links, new_links_df], ignore_index=True)
        else:
            merged_links = new_links_df
            
        merged_links.fillna("", inplace=True)
        sh = get_spreadsheet()
        ws_links = ensure_worksheet_safe(sh, "gantt_task_links", GANTT_TASK_LINKS_COLS)
        ws_links.clear()
        ws_links.update("1:1", [merged_links.columns.values.tolist()])
        if not merged_links.empty:
            ws_links.update("A2", merged_links.values.tolist())
        st.cache_data.clear()

def save_content_calendar_month(df_edited: pd.DataFrame, mission: str, cycle: str, target_month: str, target_year: int):
    sh = get_spreadsheet()
    ws = ensure_worksheet_safe(sh, "content_calendar", CONTENT_CAL_COLUMNS)
    
    all_records = ws.get_all_records()
    df_all = pd.DataFrame(all_records)
    if df_all.empty:
        df_all = pd.DataFrame(columns=CONTENT_CAL_COLUMNS)
        
    for col in CONTENT_CAL_COLUMNS:
        if col not in df_all.columns:
            df_all[col] = ""

    if not df_all.empty:
        df_all["temp_dt"] = pd.to_datetime(df_all["planned_date"], errors="coerce")
        mask = (
            (df_all["mission"] == mission) & 
            (df_all["cycle"] == cycle) & 
            (df_all["temp_dt"].dt.month == MONTHS_LIST.index(target_month) + 1) &
            (df_all["temp_dt"].dt.year == target_year)
        )
        df_all = df_all[~mask].drop(columns=["temp_dt"])

    now_str = datetime.utcnow().isoformat() + "Z"
    clean_edited = []
    for _, row in df_edited.iterrows():
        r = row.to_dict()
        if not r.get("content_title") and not r.get("description") and r.get("platform") != "No post day":
            continue
            
        if not r.get("content_id"):
            r["content_id"] = f"{mission}_{cycle}_{r.get('planned_date','')}_{uuid.uuid4().hex[:6]}"
            r["created_at"] = now_str
            
        r["mission"] = mission
        r["cycle"] = cycle
        r["month"] = target_month
        r["updated_at"] = now_str
        
        if r.get("status") == "Posted":
            if not r.get("actual_posted_date") or r.get("actual_posted_date") == "NaT":
                r["actual_posted_date"] = date.today().strftime("%Y-%m-%d")
            if not r.get("marked_done_at"):
                r["marked_done_at"] = now_str
        else:
            if r.get("actual_posted_date"): r["actual_posted_date"] = ""
            if r.get("marked_done_at"): r["marked_done_at"] = ""
                
        clean_edited.append(r)
        
    df_new = pd.DataFrame(clean_edited)
    if not df_new.empty:
        for col in CONTENT_CAL_COLUMNS:
            if col not in df_new.columns:
                df_new[col] = ""
        df_all = pd.concat([df_all, df_new], ignore_index=True)
        
    df_all = df_all.fillna("").astype(str).replace(["NaT", "nan", "None", "<NA>"], "")
    ws.clear()
    ws.update("1:1", [CONTENT_CAL_COLUMNS])
    if not df_all.empty:
        ws.update("A2", df_all[CONTENT_CAL_COLUMNS].values.tolist())
    st.cache_data.clear()

def save_finance_sheet(sheet_name: str, df_edited: pd.DataFrame, headers: list[str], id_col: str, mission: str, cycle: str):
    sh = get_spreadsheet()
    ws = ensure_worksheet_safe(sh, sheet_name, headers)
    
    all_records = ws.get_all_records()
    df_all = pd.DataFrame(all_records)
    if df_all.empty:
        df_all = pd.DataFrame(columns=headers)
    for col in headers:
        if col not in df_all.columns:
            df_all[col] = ""

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
    ws.clear()
    ws.update("1:1", [headers])
    if not df_all.empty:
        ws.update("A2", df_all[headers].values.tolist())
    st.cache_data.clear()

def queue_notification(task_row, df_notif, custom_subject=None, custom_msg=None):
    subj = custom_subject if custom_subject else f"Task Reminder: {task_row.get('title', 'Unknown')}"
    msg = custom_msg if custom_msg else f"Please update task {task_row.get('title', 'Unknown')}. Currently: {task_row.get('status', 'Unknown')}."
    
    new_notif = pd.DataFrame([{
        "notification_id": str(uuid.uuid4()),
        "task_id": task_row["task_id"],
        "notification_type": "Reminder",
        "recipient": task_row.get("assigned_to", ""),
        "cc_people": task_row.get("cc_people", ""),
        "subject": subj,
        "message": msg,
        "status": "Queued",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }])
    save_planner_data(new_notif, df_notif, PLANNER_NOTIFICATIONS_COLS, "planner_notifications_queue", "notification_id")

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
    target_comp, target_pm, target_div, target_week = str(competition).strip().lower(), str(pm_name).strip().lower(), str(division).strip().lower(), str(week_start).strip()
    for offset, row in enumerate(rows, start=2):
        if (str(row.get("competition", "")).strip().lower() == target_comp and 
            str(row.get("pm_name", "")).strip().lower() == target_pm and 
            str(row.get("division", "")).strip().lower() == target_div and 
            str(row.get("week_start", "")).strip() == target_week):
            to_delete.append(offset)
    for row_number in reversed(to_delete):
        worksheet.delete_rows(row_number)
    return len(to_delete)

def append_report_to_sheet(report: dict, input_rows: list[dict], competition: str, replace_existing: bool = True) -> tuple[int, int]:
    sh = get_spreadsheet()
    worksheet = ensure_worksheet_safe(sh, "reports", SHEET_COLUMNS)
    deleted = 0
    if replace_existing:
        deleted = delete_existing_rows(worksheet, competition=competition, pm_name=report.get("pm_name", ""), division=report.get("division", ""), week_start=report.get("week_start", ""))
    records = report_records_for_sheet(report, input_rows, competition)
    values = [[row.get(header, "") for header in SHEET_COLUMNS] for row in records]
    if values:
        worksheet.append_rows(values, value_input_option="USER_ENTERED")
    return len(values), deleted

# --- DIALOGS (POPUPS) FOR CLEANER CREATION ---
@st.dialog("+ Create New Task")
def create_task_dialog(mission, cycle, division, members, df_tasks, df_memb, df_notif):
    st.markdown("Fill out the details to assign a new task to your board.")
    with st.form("new_task_form"):
        title = st.text_input("Task Title *")
        desc = st.text_area("Description")
        
        c1, c2 = st.columns(2)
        assignee = c1.selectbox("Assign To", ["Unassigned"] + members, help="Start typing a name to search the directory.")
        
        if assignee != "Unassigned" and not df_memb.empty:
            mem_row = df_memb[df_memb['member_name'] == assignee]
            if not mem_row.empty:
                em = mem_row.iloc[0].get('email', 'No email')
                ro = mem_row.iloc[0].get('role', 'No role')
                c1.caption(f"✉ {em} | ⚙ {ro}")
                
        bucket = c2.selectbox("Bucket", ["Backlog", "This Week", "In Progress", "Waiting / Blocked", "Review", "Completed"])
        
        c3, c4 = st.columns(2)
        due_date = c3.date_input("Due Date", value=None)
        priority = c4.selectbox("Priority", ["Low", "Medium", "High", "Critical"], index=1)
        
        submit = st.form_submit_button("☑ Create Task", type="primary", use_container_width=True)
        if submit:
            if not title:
                st.error("⚠ Title is required.")
            else:
                new_task_dict = {
                    "task_id": str(uuid.uuid4()),
                    "mission": mission,
                    "cycle": cycle,
                    "division": division,
                    "bucket": bucket,
                    "title": title,
                    "description": desc,
                    "assigned_to": assignee if assignee != "Unassigned" else "",
                    "priority": priority,
                    "status": "Not Started" if bucket != "Completed" else "Completed",
                    "due_date": due_date.strftime("%Y-%m-%d") if due_date else "",
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                new_task = pd.DataFrame([new_task_dict])
                save_planner_data(new_task, df_tasks, PLANNER_TASKS_COLS, "planner_tasks", "task_id")
                
                if assignee != "Unassigned":
                    subj = f"New Task Assigned: {title}"
                    msg = f"You have been assigned a new task: <strong>{title}</strong>.<br>Priority: {priority}<br>Due: {due_date.strftime('%Y-%m-%d') if due_date else 'No Due Date'}<br><br>Description:<br>{desc}"
                    queue_notification(new_task.iloc[0], df_notif, custom_subject=subj, custom_msg=msg)
                
                st.rerun()

@st.dialog("+ Schedule Content")
def create_content_dialog(mission, cycle, month_name, year_val):
    st.markdown("Draft new content for your social or outreach pipelines.")
    with st.form("new_content_form"):
        title = st.text_input("Content Title *")
        c1, c2 = st.columns(2)
        platform = c1.selectbox("Platform", list(PLATFORM_COLORS.keys()))
        status = c2.selectbox("Status", list(STATUS_SYMBOLS.keys()))
        
        c3, c4 = st.columns(2)
        try: m_int = MONTHS_LIST.index(month_name) + 1
        except: m_int = date.today().month
        y_int = int(year_val) if str(year_val).isdigit() else date.today().year
        
        p_date = c3.date_input("Planned Date", value=date(y_int, m_int, 1))
        ctype = c4.text_input("Content Type (Reel, Post, etc.)")
        
        desc = st.text_area("Description / Copy")
        owner = st.text_input("Owner")
        
        submit = st.form_submit_button("☑ Schedule Content", type="primary", use_container_width=True)
        if submit:
            if not title: st.error("⚠ Title is required.")
            else:
                new_row = pd.DataFrame([{
                    "content_id": str(uuid.uuid4()),
                    "mission": mission,
                    "cycle": cycle,
                    "month": month_name,
                    "planned_date": p_date.strftime("%Y-%m-%d") if p_date else "",
                    "platform": platform,
                    "content_title": title,
                    "description": desc,
                    "content_type": ctype,
                    "owner": owner,
                    "status": status,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }])
                save_content_calendar_month(new_row, mission, cycle, month_name, y_int)
                st.rerun()

@st.dialog("+ Plan Fundraiser Event")
def create_fundraiser_dialog(mission, cycle, df_events):
    with st.form("new_event_form"):
        name = st.text_input("Event Name *")
        c1, c2 = st.columns(2)
        etype = c1.selectbox("Event Type", ["Food Sale", "Raffle", "Sponsorship", "Donation", "Venue Fundraiser", "Online Campaign", "Community Event", "Other"])
        status = c2.selectbox("Status", ["Planned", "In Progress", "Completed", "Cancelled", "Delayed", "Needs Follow-Up"])
        
        c3, c4 = st.columns(2)
        pdate = c3.date_input("Planned Date", value=date.today())
        loc = c4.text_input("Location")
        
        c5, c6 = st.columns(2)
        exp_gross = c5.number_input("Expected Gross $", min_value=0.0)
        exp_costs = c6.number_input("Expected Costs $", min_value=0.0)
        
        submit = st.form_submit_button("☑ Create Event", type="primary", use_container_width=True)
        if submit:
            if not name: st.error("⚠ Event Name is required.")
            else:
                new_event = pd.DataFrame([{
                    "event_id": str(uuid.uuid4()),
                    "mission": mission,
                    "cycle": cycle,
                    "event_name": name,
                    "event_type": etype,
                    "planned_date": pdate.strftime("%Y-%m-%d") if pdate else "",
                    "location": loc,
                    "status": status,
                    "expected_gross_revenue": exp_gross,
                    "expected_expenses": exp_costs,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }])
                save_finance_sheet("fundraising_events", new_event, EVENTS_HEADERS, "event_id", mission, cycle)
                st.rerun()

@st.dialog("+ Log Income / Transaction")
def create_transaction_dialog(mission, cycle, df_txns, df_events):
    event_opts = [str(x) for x in df_events["event_name"].dropna().unique()] if not df_events.empty else []
    with st.form("new_txn_form"):
        evt = st.selectbox("Linked Event", ["Unlinked"] + event_opts)
        c1, c2 = st.columns(2)
        src_type = c1.selectbox("Source Type", ["Individual", "Sponsor", "Ticket Sale", "Raffle Sale", "Food Sale", "Online Donation", "Cash Donation", "Other"])
        src_name = c2.text_input("Source Name (Optional)")
        
        c3, c4 = st.columns(2)
        method = c3.selectbox("Payment Method", ["ATH Movil", "Cash", "PayPal", "Check", "Bank Transfer", "Card", "Other"])
        amt = c4.number_input("Amount $ *", min_value=0.01)
        
        tdate = st.date_input("Transaction Date", value=date.today())
        
        if st.form_submit_button("☑ Save Transaction", type="primary", use_container_width=True):
            name_to_id = dict(zip(df_events["event_name"], df_events["event_id"])) if not df_events.empty else {}
            eid = name_to_id.get(evt, "") if evt != "Unlinked" else ""
            
            new_t = pd.DataFrame([{
                "transaction_id": str(uuid.uuid4()),
                "event_id": eid,
                "event_name": evt if evt != "Unlinked" else "",
                "mission": mission,
                "cycle": cycle,
                "source_type": src_type,
                "source_name": src_name,
                "payment_method": method,
                "amount": amt,
                "transaction_date": tdate.strftime("%Y-%m-%d") if tdate else "",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }])
            save_finance_sheet("fundraising_transactions", new_t, TRANSACTIONS_HEADERS, "transaction_id", mission, cycle)
            st.rerun()

@st.dialog("+ Log Expense")
def create_expense_dialog(mission, cycle, df_exps, df_events):
    event_opts = [str(x) for x in df_events["event_name"].dropna().unique()] if not df_events.empty else []
    with st.form("new_exp_form"):
        evt = st.selectbox("Linked Event", ["Unlinked"] + event_opts)
        c1, c2 = st.columns(2)
        cat = c1.selectbox("Category", ["Food / Materials", "Venue", "Marketing", "Equipment", "Transportation", "Permit", "Prize", "Supplies", "Other"])
        vendor = c2.text_input("Vendor")
        
        item = st.text_input("Item Description")
        
        c3, c4 = st.columns(2)
        amt = c3.number_input("Amount Spent $ *", min_value=0.01)
        edate = c4.date_input("Expense Date", value=date.today())
        
        if st.form_submit_button("☑ Save Expense", type="primary", use_container_width=True):
            name_to_id = dict(zip(df_events["event_name"], df_events["event_id"])) if not df_events.empty else {}
            eid = name_to_id.get(evt, "") if evt != "Unlinked" else ""
            
            new_e = pd.DataFrame([{
                "expense_id": str(uuid.uuid4()),
                "event_id": eid,
                "event_name": evt if evt != "Unlinked" else "",
                "mission": mission,
                "cycle": cycle,
                "category": cat,
                "vendor": vendor,
                "item_description": item,
                "amount": amt,
                "expense_date": edate.strftime("%Y-%m-%d") if edate else "",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }])
            save_finance_sheet("fundraising_expenses", new_e, EXPENSES_HEADERS, "expense_id", mission, cycle)
            st.rerun()

# -----------------------------------------------------------------------------
# SIDEBAR NAVIGATION & ROUTER
# -----------------------------------------------------------------------------
st.sidebar.header("⌖ Navigation")
current_page = st.sidebar.radio("Go to", ["▦ Weekly Performance Report", "◫ Content Calendar", "$ Fundraising & Finance", "▦ Planner"])

if "force_refresh" not in st.session_state:
    st.session_state.force_refresh = 0

df_memb = fetch_cached_df("planner_members", PLANNER_MEMBERS_COLS, st.session_state.force_refresh)
member_opts = df_memb["member_name"].dropna().unique().tolist() if not df_memb.empty else []

if "competition" not in st.session_state:
    st.session_state.competition = "Mars"

with st.sidebar:
    st.divider()
    st.header("⌕ Context Filters")
    st.caption("These filters control what you see and create.")
    
    global_mission = st.selectbox("Mission Filter", ["Mars", "Luna"], index=0 if st.session_state.competition == "Mars" else 1)
    st.session_state.competition = global_mission
    
    active_divisions = [d for d in DIVISIONS if any(k in d.lower() for k in ["electrical", "vehicle", "software"])] if global_mission == "Luna" else list(DIVISIONS)

    if current_page == "▦ Weekly Performance Report":
        st.info("ⓘ Filters for the weekly report are located on the main page.")
        
    elif current_page == "▦ Planner":
        plan_mission = global_mission
        plan_cycle = st.selectbox("Cycle Filter", DYNAMIC_CYCLES, index=1)
        plan_division = st.selectbox("Division Filter", active_divisions, index=0)
        plan_assignee = st.selectbox("Assignee Filter", ["All"] + member_opts, help="Filter the board for a specific team member.")
        
    elif current_page == "◫ Content Calendar":
        cal_mission = global_mission
        cal_cycle = st.selectbox("Cycle Filter", DYNAMIC_CYCLES, index=1)
        cal_month = st.selectbox("Month Filter", MONTHS_LIST, index=date.today().month - 1)
        cal_year = st.selectbox("Year Filter", [date.today().year - 1, date.today().year, date.today().year + 1, date.today().year + 2], index=1)
        
    elif current_page == "$ Fundraising & Finance":
        fin_mission = global_mission
        fin_cycle = st.selectbox("Cycle Filter", DYNAMIC_CYCLES, index=1)
        fin_month = st.selectbox("Month Filter", MONTHS_LIST, index=date.today().month - 1)
        fin_year = st.selectbox("Year Filter", [date.today().year - 1, date.today().year, date.today().year + 1, date.today().year + 2], index=1)

    st.divider()
    st.header("↻ Data Sync")
    if st.button("↻ Force Refresh Google Sheets", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# -----------------------------------------------------------------------------
# DYNAMIC VIBE THEME ENGINE
# -----------------------------------------------------------------------------
if current_page == "◫ Content Calendar":
    bg_top, bg_bot, side_top, side_bot = "#2e1065", "#000000", "#2e1065", "#000000"
    panel_bg, panel_light = "rgba(30, 27, 75, 0.60)", "rgba(46, 16, 101, 0.40)"
    primary, primary_hover, primary_text, primary_shadow = "#ec4899", "#db2777", "#ffffff", "rgba(236, 72, 153, 0.25)"
    logo_a_color, logo_a_shadow, logo_v_color, logo_v_shadow = "#ec4899", "#831843", "#a855f7", "#581c87"
    custom_logo = '<div class="av-logo"><span class="a">A</span><span class="v" style="margin-right: 5px;">V</span><span style="font-size: 0.5em; color: #ec4899; text-shadow: 2px 2px 0px #831843; font-style: normal; transform: translateY(-10px); display: inline-block;">[►]</span></div>'
elif current_page == "$ Fundraising & Finance":
    bg_top, bg_bot, side_top, side_bot = "#064e3b", "#000000", "#064e3b", "#000000"
    panel_bg, panel_light = "rgba(2, 44, 34, 0.60)", "rgba(6, 78, 59, 0.40)"
    primary, primary_hover, primary_text, primary_shadow = "#10b981", "#059669", "#ffffff", "rgba(16, 185, 129, 0.25)"
    logo_a_color, logo_a_shadow, logo_v_color, logo_v_shadow = "#10b981", "#064e3b", "#6ee7b7", "#047857"
    custom_logo = '<div class="av-logo"><span class="a">A</span><span class="v" style="margin-right: 5px;">V</span><span style="font-size: 0.6em; color: #10b981; text-shadow: 2px 2px 0px #064e3b; font-style: normal; transform: translateY(-8px); display: inline-block;">$</span></div>'
elif current_page == "▦ Planner":
    bg_top, bg_bot, side_top, side_bot = "#1e1b4b", "#000000", "#1e1b4b", "#000000"
    panel_bg, panel_light = "rgba(49, 46, 129, 0.45)", "rgba(67, 56, 202, 0.35)"
    primary, primary_hover, primary_text, primary_shadow = "#6366f1", "#4f46e5", "#ffffff", "rgba(99, 102, 241, 0.25)"
    logo_a_color, logo_a_shadow, logo_v_color, logo_v_shadow = "#6366f1", "#312e81", "#a855f7", "#4c1d95"
    custom_logo = '<div class="av-logo"><span class="a">A</span><span class="v" style="margin-right: 5px;">V</span><span style="font-size: 0.5em; color: #6366f1; text-shadow: 2px 2px 0px #312e81; font-style: normal; transform: translateY(-10px); display: inline-block;">✓</span></div>'
else:
    custom_logo = '<div class="av-logo"><span class="a">A</span><span class="v">V</span></div>'
    if global_mission == "Mars":
        bg_top, bg_bot, side_top, side_bot = "#1e293b", "#000000", "#1e293b", "#111827"
        panel_bg, panel_light = "#1e293b", "rgba(51, 65, 85, 0.35)"
        primary, primary_hover, primary_text, primary_shadow = "#ef4444", "#dc2626", "#ffffff", "rgba(239, 68, 68, 0.25)"
        logo_a_color, logo_a_shadow, logo_v_color, logo_v_shadow = "#ef4444", "#7f1d1d", "#ffffff", "#94a3b8"
    else:
        bg_top, bg_bot, side_top, side_bot = "#334155", "#0f172a", "#334155", "#1e293b"
        panel_bg, panel_light = "#475569", "rgba(100, 116, 139, 0.30)"
        primary, primary_hover, primary_text, primary_shadow = "#f8fafc", "#e2e8f0", "#1e3a8a", "rgba(255, 255, 255, 0.20)"
        logo_a_color, logo_a_shadow, logo_v_color, logo_v_shadow = "#f8fafc", "#64748b", "#3b82f6", "#1e3a8a"

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
    
    [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
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
        position: relative; overflow: hidden; padding: 38px 42px; border-radius: 24px;
        background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); margin-bottom: 24px; color: #f8fafc;
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
        padding: 22px 28px; border-radius: 20px; background: var(--panel); border: 1px solid var(--line); box-shadow: var(--shadow); margin-bottom: 24px; color: var(--ink);
    }}
    
    div.row-widget.stRadio > div {{
        display: flex; flex-direction: row; align-items: center; gap: 16px; background: rgba(255,255,255,0.05); padding: 8px 16px; border-radius: 100px; border: 1px solid var(--line); width: fit-content;
    }}
    .division-pill {{
        display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--line); margin: 0 8px 8px 0; color: #f8fafc; font-size: 13px; font-weight: 750;
    }}
    .dot {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; }}
    .metric-note {{ color: #94a3b8; font-size: 13px; margin-top: 10px;}}
    
    h1, h2, h3, p, label, span, div {{ text-shadow: none; color: var(--ink); }}
    
    button[data-baseweb="tab"] {{ color: #cbd5e1 !important; font-weight: 700 !important; font-size: 16px !important; padding: 10px 20px !important; }}
    button[data-baseweb="tab"][aria-selected="true"] {{ color: #ffffff !important; }}
    div[data-baseweb="tab-highlight"] {{ background-color: var(--primary) !important; height: 3px !important; }}

    .stButton > button {{
        background: rgba(255,255,255,0.05) !important; color: #f8fafc !important; border: 1px solid rgba(255,255,255,0.1) !important; border-radius: 12px !important; font-weight: 700 !important; transition: all 0.3s ease !important;
    }}
    .stButton > button:hover {{ background: rgba(255,255,255,0.1) !important; border-color: rgba(255,255,255,0.3) !important; color: #ffffff !important; }}
    
    button[kind="primary"], [data-testid="stFormSubmitButton"] > button {{
        background: var(--primary) !important; color: var(--primary-text) !important; box-shadow: 0 8px 20px var(--primary-shadow) !important; border: 1px solid rgba(255,255,255,0.1) !important; border-radius: 12px !important; font-weight: 800 !important; transition: all 0.3s ease !important; text-transform: uppercase; letter-spacing: 1px;
    }}
    button[kind="primary"] *, [data-testid="stFormSubmitButton"] > button * {{ color: var(--primary-text) !important; }}
    button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button:hover {{ background: var(--primary-hover) !important; transform: translateY(-2px); }}

    .stDownloadButton > button {{
        background: rgba(0,0,0,0.4) !important; color: #94a3b8 !important; border: 1px dashed rgba(255,255,255,0.2) !important; border-radius: 12px !important; font-weight: 600 !important; box-shadow: none !important; transition: all 0.3s ease !important;
    }}
    .stDownloadButton > button * {{ color: #94a3b8 !important; }}
    .stDownloadButton > button:hover {{ background: rgba(0,0,0,0.8) !important; color: #ffffff !important; border: 1px solid rgba(255,255,255,0.4) !important; }}
    .stDownloadButton > button:hover * {{ color: #ffffff !important; }}
    
    input, textarea, [data-baseweb="select"] {{ color: #f8fafc !important; }}
    [data-baseweb="base-input"], [data-baseweb="select"] > div {{ background: #0f172a !important; border-color: #334155 !important; }}
    
    .cal-day {{ border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; min-height: 130px; padding: 8px; background: rgba(0,0,0,0.2); margin-bottom: 10px; display: flex; flex-direction: column; gap: 4px; }}
    .cal-day.empty {{ background: transparent; border: 1px dashed rgba(255,255,255,0.05); }}
    .cal-date {{ font-weight: 800; color: #cbd5e1; font-size: 14px; margin-bottom: 4px; }}
    .cal-badge {{ font-size: 11px; padding: 4px 6px; border-radius: 4px; color: #000000; font-weight: 700; line-height: 1.2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    
    .kpi {{ padding: 24px; border-radius: 16px; background: rgba(255,255,255,0.03); border: 1px solid var(--line); margin-bottom: 24px; }}
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
# PAGE: WEEKLY PERFORMANCE REPORT
# -----------------------------------------------------------------------------
if current_page == "▦ Weekly Performance Report":
    st.markdown(
        f"""
        <div class="hero">
        <div class="hero-content">
            <div class="av-logo-container">
                {custom_logo}
                <div>
                    <div class="eyebrow">Project AV • {global_mission} Mission Mode</div>
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

    legend_html = "".join(f'<span class="division-pill"><span class="dot" style="background:{color}"></span>{division_name}</span>' for division_name, color in DIVISION_COLORS.items() if division_name in active_divisions)
    st.markdown(f'<div class="glass"><b>Official Division Legend</b><br><br>{legend_html}<div class="metric-note">Formula: {metric_weights_text()}</div></div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    pm_name = c1.text_input("PM name", placeholder="Ej. Alejandro / PM Robotic Arm")
    division = c2.selectbox("Division", active_divisions, index=0)
    
    if "selected_date" not in st.session_state: st.session_state.selected_date = today_monday()
    cal_date = c3.date_input("Week Starting", value=st.session_state.selected_date)
    week_start = monday_for(cal_date)
    
    init_df = pd.DataFrame(empty_input_rows())
    if "hours_invested" not in init_df.columns: init_df["hours_invested"] = 0
    if "communication_score" not in init_df.columns: init_df["communication_score"] = 0.0

    if len(init_df) < 50:
        pad = pd.DataFrame([{c: ("" if c in ["member_name", "role", "notes"] else 0) for c in init_df.columns} for _ in range(50 - len(init_df))])
        init_df = pd.concat([init_df, pad], ignore_index=True)

    current_draft_key = f"{global_mission}_{pm_name}_{division}_{week_start}"
    
    if "tracker_df" not in st.session_state or st.session_state.get("last_draft_key") != current_draft_key:
        draft_records = load_cloud_draft(global_mission, pm_name, division, week_start) if pm_name.strip() else None
        if draft_records is not None:
            st.session_state.tracker_df = normalize_tracker_df(draft_records, init_df)
        else:
            st.session_state.tracker_df = init_df.copy()
        st.session_state["last_draft_key"] = current_draft_key

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    with st.expander("▦ Load Tasks from Planner"):
        st.markdown("Pull assigned tasks from the Planner and automatically build member performance rows for this week.")
        if st.button("Load Weekly Rows from Planner", type="primary"):
            df_tasks = fetch_cached_df("planner_tasks", PLANNER_TASKS_COLS, st.session_state.force_refresh)
            if not df_tasks.empty:
                mask = (df_tasks["division"] == division) & (df_tasks["status"] != "Cancelled")
                filtered = df_tasks[mask].copy()
                ws_date = pd.to_datetime(week_start)
                we_date = ws_date + timedelta(days=6)
                filtered["due_date_dt"] = pd.to_datetime(filtered["due_date"], errors="coerce")
                filtered["week_start_dt"] = pd.to_datetime(filtered["week_start"], errors="coerce")
                week_mask = (filtered["week_start_dt"] == ws_date) | ((filtered["due_date_dt"] >= ws_date) & (filtered["due_date_dt"] <= we_date))
                filtered = filtered[week_mask]
                
                if not filtered.empty:
                    members = filtered["assigned_to"].dropna().unique()
                    new_rows = []
                    for m in members:
                        if not m: continue
                        m_tasks = filtered[filtered["assigned_to"] == m]
                        completed_tasks = m_tasks[m_tasks["status"] == "Completed"]
                        
                        late_tasks, on_time_tasks = 0, 0
                        for _, t in completed_tasks.iterrows():
                            cd = pd.to_datetime(t["completed_date"], errors="coerce")
                            dd = pd.to_datetime(t["due_date"], errors="coerce")
                            if pd.notnull(cd) and pd.notnull(dd) and cd > dd: late_tasks += 1
                            else: on_time_tasks += 1
                                
                        blocked_tasks = len(m_tasks[(m_tasks["status"] == "Blocked") | (m_tasks["delay_flag"].astype(str).str.lower() == "true")])
                        new_rows.append({
                            "member_name": m, "role": "Member", "tasks_assigned": len(m_tasks), "hours_invested": 0,
                            "tasks_completed": len(completed_tasks), "tasks_on_time": on_time_tasks, "tasks_late": late_tasks,
                            "blocked_tasks": blocked_tasks, "avg_quality_1_to_5": 3, "meetings_required": 1, "meetings_attended": 1,
                            "pm_confidence_1_to_5": 3, "communication_score": 3, "notes": " | ".join(m_tasks["title"].tolist())[:200]
                        })
                    
                    if new_rows:
                        new_df = pd.DataFrame(new_rows)
                        for col in init_df.columns:
                            if col not in new_df.columns: new_df[col] = "" if col in ["member_name", "role", "notes"] else 0
                        current = st.session_state.tracker_df
                        current = current[current["member_name"].astype(str).str.strip() != ""]
                        merged = pd.concat([current, new_df]).drop_duplicates(subset=["member_name"], keep="last")
                        if len(merged) < 50:
                            pad = pd.DataFrame([{c: ("" if c in ["member_name", "role", "notes"] else 0) for c in init_df.columns} for _ in range(50 - len(merged))])
                            merged = pd.concat([merged, pad], ignore_index=True)
                        st.session_state.tracker_df = merged.reset_index(drop=True)
                        st.success("ⓘ Planner tasks merged successfully! Review them in the tabs below.")
                        st.rerun()
                else: st.warning("⚠ No Planner tasks found for this division and week.")
            else: st.warning("⚠ Planner tasks sheet is empty.")

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

    with st.form("weekly_data_form"):
        tab1, tab2, tab3 = st.tabs(["◈ 1. Assignment", "◈ 2. Execution", "◈ 3. Performance"])
        with tab1: df1 = st.data_editor(st.session_state.tracker_df[["member_name", "role", "tasks_assigned", "hours_invested"]], key="editor_tab1", use_container_width=True, hide_index=True, height=480, column_config=col_config_base)
        with tab2: df2 = st.data_editor(st.session_state.tracker_df[["member_name", "tasks_completed", "tasks_on_time", "tasks_late", "blocked_tasks"]], key="editor_tab2", use_container_width=True, hide_index=True, height=480, column_config=col_config_locked)
        with tab3: df3 = st.data_editor(st.session_state.tracker_df[["member_name", "avg_quality_1_to_5", "meetings_required", "meetings_attended", "pm_confidence_1_to_5", "communication_score", "notes"]], key="editor_tab3", use_container_width=True, hide_index=True, height=480, column_config=col_config_locked)
        submit_edits = st.form_submit_button("☑ Save Cloud Draft & Update Preview", type="primary", use_container_width=True)

    if submit_edits:
        st.session_state.tracker_df.update(df1)
        st.session_state.tracker_df.update(df2.drop(columns=["member_name"]))
        st.session_state.tracker_df.update(df3.drop(columns=["member_name"]))
        if pm_name.strip():
            save_cloud_draft(global_mission, pm_name, division, week_start, st.session_state.tracker_df.to_dict(orient="records"))
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    rows = st.session_state.tracker_df.fillna("").to_dict(orient="records")
    report = make_report(pm_name=pm_name, division=division, week_start=week_start, rows=rows)
    report["competition"] = global_mission 
    preview = pd.DataFrame(report["records"])

    st.markdown('<div class="glass">', unsafe_allow_html=True)
    st.subheader("Submit to Google Sheets")
    replace_existing = st.checkbox(f"Replace any previous rows for {global_mission} / {pm_name} / {division} / {week_start}", value=True)

    col_a, col_b = st.columns([1, 2])
    with col_a:
        save_clicked = st.button(f"☑ FINAL SUBMIT TO GOOGLE SHEETS", type="primary", use_container_width=True)
    with col_b:
        json_bytes = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button("↓ Download backup JSON", data=json_bytes, file_name=f"{report['iso_year']}-W{report['iso_week']:02d}_{global_mission}_weekly_report.json", mime="application/json", use_container_width=True)

    if save_clicked:
        if not pm_name.strip(): st.error("⚠ Falta el nombre del PM.")
        elif preview.empty: st.error("⚠ No hay miembros válidos para exportar.")
        else:
            rows_written, rows_deleted = append_report_to_sheet(report, rows, global_mission, replace_existing=replace_existing)
            st.success(f"ⓘ Submitted {rows_written} member row(s) to Google Sheets.")
            delete_cloud_draft(global_mission, pm_name, division, week_start)
    st.markdown('</div>', unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# PAGE: CONTENT CALENDAR
# -----------------------------------------------------------------------------
elif current_page == "◫ Content Calendar":
    if "cc_pm_month" not in st.session_state: st.session_state.cc_pm_month = calendar.month_name[date.today().month]
    if "cc_pm_year" not in st.session_state: st.session_state.cc_pm_year = date.today().year

    def cc_prev_month():
        m_idx = MONTHS_LIST.index(st.session_state.cc_pm_month) + 1
        y = int(st.session_state.cc_pm_year)
        if m_idx == 1: m_idx, y = 12, y - 1
        else: m_idx -= 1
        st.session_state.cc_pm_month, st.session_state.cc_pm_year = calendar.month_name[m_idx], y

    def cc_next_month():
        m_idx = MONTHS_LIST.index(st.session_state.cc_pm_month) + 1
        y = int(st.session_state.cc_pm_year)
        if m_idx == 12: m_idx, y = 1, y + 1
        else: m_idx += 1
        st.session_state.cc_pm_month, st.session_state.cc_pm_year = calendar.month_name[m_idx], y

    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-content">
            <div class="av-logo-container">
                {custom_logo}
                <div>
                    <div class="eyebrow">Project AV • Planning</div>
                    <div class="title">Content Calendar</div>
                </div>
            </div>
            <div class="subtitle" style="margin-top: 10px;">
              Plan and track outreach/social media execution by mission, month, and platform. 
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True
    )

    full_cal_df = fetch_cached_df("content_calendar", CONTENT_CAL_COLUMNS, st.session_state.force_refresh)
    
    if not full_cal_df.empty:
        full_cal_df["temp_dt"] = pd.to_datetime(full_cal_df["planned_date"], errors="coerce")
        month_idx = MONTHS_LIST.index(st.session_state.cc_pm_month) + 1
        mask = ((full_cal_df["mission"] == cal_mission) & (full_cal_df["cycle"] == cal_cycle) & 
                (full_cal_df["temp_dt"].dt.month == month_idx) & (full_cal_df["temp_dt"].dt.year == st.session_state.cc_pm_year))
        active_df = full_cal_df[mask].drop(columns=["temp_dt"]).copy()
    else:
        active_df = pd.DataFrame(columns=CONTENT_CAL_COLUMNS)

    st.markdown("### ⌖ Execution Tracker")
    total_planned = len(active_df)
    posted = len(active_df[active_df["status"] == "Posted"])
    missed = len(active_df[active_df["status"] == "Missed"])
    pending = len(active_df[active_df["status"].isin(["Planned", "In Progress", "Rescheduled"])])
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Planned Items", total_planned)
    m2.metric("Posted", posted)
    m3.metric("Missed", missed)
    m4.metric("Pending", pending)
    st.divider()
    
    c_action, c_space = st.columns([1, 4])
    with c_action:
        if st.button("+ Schedule Content", type="primary", use_container_width=True):
            create_content_dialog(cal_mission, cal_cycle, st.session_state.cc_pm_month, st.session_state.cc_pm_year)

    st.markdown("<br>", unsafe_allow_html=True)

    c_prev, c_title, c_next = st.columns([1, 6, 1])
    with c_prev: st.button("◀ Prev", on_click=cc_prev_month, use_container_width=True)
    with c_title: st.markdown(f"<h3 style='text-align:center; margin-top:0;'>◫ {st.session_state.cc_pm_month} {st.session_state.cc_pm_year}</h3>", unsafe_allow_html=True)
    with c_next: st.button("Next ▶", on_click=cc_next_month, use_container_width=True)
    
    month_idx = MONTHS_LIST.index(st.session_state.cc_pm_month) + 1
    cal = calendar.monthcalendar(st.session_state.cc_pm_year, month_idx)
    
    cols = st.columns(7)
    for i, d_name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
        cols[i].markdown(f"<div style='text-align:center; color:#94a3b8; font-weight:800; font-size:14px; margin-bottom:8px;'>{d_name}</div>", unsafe_allow_html=True)
        
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].markdown("<div class='cal-day empty'></div>", unsafe_allow_html=True)
            else:
                date_str = f"{st.session_state.cc_pm_year}-{month_idx:02d}-{day:02d}"
                day_items = active_df[active_df["planned_date"] == date_str]
                content_html = ""
                for _, item in day_items.iterrows():
                    platform = item.get("platform", "Other")
                    title = item.get("content_title", "Untitled")
                    status = item.get("status", "Planned")
                    bg_color = PLATFORM_COLORS.get(platform, "#94a3b8")
                    symbol = STATUS_SYMBOLS.get(status, "◌")
                    content_html += f"<div class='cal-badge' style='background:{bg_color};' title='{title}'>{symbol} {platform}</div>"
                cols[i].markdown(f"<div class='cal-day'><div class='cal-date'>{day}</div>{content_html}</div>", unsafe_allow_html=True)

    st.divider()
    with st.expander("▦ Bulk Content Editor"):
        st.markdown('<div class="chart-desc">ⓘ Bulk edit rows directly. Changing status to "Posted" automatically updates the execution timestamp.</div>', unsafe_allow_html=True)
        edit_cols = ["content_id", "planned_date", "platform", "content_title", "description", "content_type", "owner", "status", "actual_posted_date", "notes"]
        display_df = active_df[edit_cols].copy()
        
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
        
        if st.button("☑ Save Content Editor", type="primary"):
            final_save_df = edited_view.copy()
            if not active_df.empty:
                meta_df = active_df[["content_id", "marked_done_at", "created_at"]].dropna(subset=["content_id"])
                final_save_df = pd.merge(final_save_df, meta_df, on="content_id", how="left")
            final_save_df["planned_date"] = pd.to_datetime(final_save_df["planned_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            final_save_df["actual_posted_date"] = pd.to_datetime(final_save_df["actual_posted_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            save_content_calendar_month(final_save_df, cal_mission, cal_cycle, st.session_state.cc_pm_month, st.session_state.cc_pm_year)
            st.rerun()

# -----------------------------------------------------------------------------
# PAGE: FUNDRAISING & FINANCE
# -----------------------------------------------------------------------------
elif current_page == "$ Fundraising & Finance":
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-content">
            <div class="av-logo-container">
                {custom_logo}
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

    events_df = fetch_cached_df("fundraising_events", EVENTS_HEADERS, st.session_state.force_refresh)
    trans_df = fetch_cached_df("fundraising_transactions", TRANSACTIONS_HEADERS, st.session_state.force_refresh)
    exp_df = fetch_cached_df("fundraising_expenses", EXPENSES_HEADERS, st.session_state.force_refresh)
    goals_df = fetch_cached_df("fundraising_goals", GOALS_HEADERS, st.session_state.force_refresh)

    if not events_df.empty: events_df = events_df[(events_df["mission"] == fin_mission) & (events_df["cycle"] == fin_cycle)].copy()
    if not trans_df.empty: trans_df = trans_df[(trans_df["mission"] == fin_mission) & (trans_df["cycle"] == fin_cycle)].copy()
    if not exp_df.empty: exp_df = exp_df[(exp_df["mission"] == fin_mission) & (exp_df["cycle"] == fin_cycle)].copy()
    if not goals_df.empty: goals_df = goals_df[(goals_df["mission"] == fin_mission) & (goals_df["cycle"] == fin_cycle)].copy()

    trans_sums = trans_df.groupby("event_id")["amount"].sum() if not trans_df.empty else pd.Series()
    exp_sums = exp_df.groupby("event_id")["amount"].sum() if not exp_df.empty else pd.Series()

    if not events_df.empty:
        for idx, row in events_df.iterrows():
            eid = row.get("event_id")
            g = trans_sums.get(eid, 0.0)
            e = exp_sums.get(eid, 0.0)
            events_df.at[idx, "actual_gross_revenue"] = g
            events_df.at[idx, "actual_expenses"] = e
            events_df.at[idx, "actual_net_revenue"] = g - e
            events_df.at[idx, "expected_net_revenue"] = float(row.get("expected_gross_revenue") or 0) - float(row.get("expected_expenses") or 0)

    event_options = [str(x) for x in events_df["event_name"].dropna().unique()] if not events_df.empty else ["None"]

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("+ Plan Fundraiser", type="primary", use_container_width=True):
            create_fundraiser_dialog(fin_mission, fin_cycle, events_df)
    with c2:
        if st.button("+ Log Income", type="primary", use_container_width=True):
            create_transaction_dialog(fin_mission, fin_cycle, trans_df, events_df)
    with c3:
        if st.button("+ Log Expense", type="primary", use_container_width=True):
            create_expense_dialog(fin_mission, fin_cycle, exp_df, events_df)

    st.markdown("<br>", unsafe_allow_html=True)
    tab_evt, tab_txn, tab_exp, tab_goal, tab_analytics = st.tabs(["◈ Events", "▦ Transactions", "▦ Expenses", "⊙ Goals", "⌁ Analytics"])

    with tab_evt:
        st.markdown("### ◈ Event Management")
        evt_cols = ["event_id", "event_name", "event_type", "planned_date", "actual_date", "location", "status", "expected_gross_revenue", "expected_expenses", "venue_confirmed", "permits_completed", "marketing_ready", "volunteers_ready"]
        evt_view = events_df[evt_cols].copy() if not events_df.empty else pd.DataFrame(columns=evt_cols)
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
        if st.button("☑ Save Events Bulk Editor", type="primary"):
            final = edited_evt.copy()
            if not events_df.empty:
                meta = events_df[["event_id", "created_at", "actual_gross_revenue", "actual_expenses", "actual_net_revenue", "expected_net_revenue"]].dropna(subset=["event_id"])
                final = pd.merge(final, meta, on="event_id", how="left")
            final["planned_date"] = pd.to_datetime(final["planned_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            final["actual_date"] = pd.to_datetime(final["actual_date"], errors="coerce").dt.strftime('%Y-%m-%d').fillna("")
            save_finance_sheet("fundraising_events", final, EVENTS_HEADERS, "event_id", fin_mission, fin_cycle)
            st.rerun()

    with tab_txn:
        st.markdown("### ▦ Income Transactions")
        txn_cols = ["transaction_id", "event_name", "transaction_date", "source_type", "source_name", "payment_method", "amount", "deposited"]
        txn_view = trans_df[txn_cols].copy() if not trans_df.empty else pd.DataFrame(columns=txn_cols)
        txn_view["transaction_date"] = pd.to_datetime(txn_view["transaction_date"], errors="coerce").dt.date
        
        config = {
            "transaction_id": None, 
            "transaction_date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", help="Date the money was received."),
            "event_name": st.column_config.SelectboxColumn("Linked Event", options=event_options, help="Which event generated this income?"),
            "source_type": st.column_config.SelectboxColumn("Source", options=["Individual", "Sponsor", "Ticket Sale", "Raffle Sale", "Food Sale", "Online Donation", "Cash Donation", "Other"], help="Who or what provided the funds?"),
            "payment_method": st.column_config.SelectboxColumn("Method", options=["ATH Movil", "Cash", "PayPal", "Check", "Bank Transfer", "Card", "Other"], help="How was it paid?"),
        }
        edited_txn = st.data_editor(txn_view, num_rows="dynamic", use_container_width=True, height=450, column_config=config)
        if st.button("☑ Save Transactions Bulk Editor", type="primary"):
            name_to_id = dict(zip(events_df["event_name"], events_df["event_id"])) if not events_df.empty else {}
            edited_txn["event_id"] = edited_txn["event_name"].map(name_to_id).fillna("")
            save_finance_sheet("fundraising_transactions", edited_txn, TRANSACTIONS_HEADERS, "transaction_id", fin_mission, fin_cycle)
            st.rerun()

    with tab_exp:
        st.markdown("### ▦ Expenses")
        exp_cols = ["expense_id", "event_name", "expense_date", "vendor", "item_description", "category", "amount", "reimbursed"]
        exp_view = exp_df[exp_cols].copy() if not exp_df.empty else pd.DataFrame(columns=exp_cols)
        exp_view["expense_date"] = pd.to_datetime(exp_view["expense_date"], errors="coerce").dt.date
        
        config = {
            "expense_id": None, 
            "expense_date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", help="Date the purchase was made."),
            "event_name": st.column_config.SelectboxColumn("Linked Event", options=event_options, help="Which event is this cost for?"),
            "category": st.column_config.SelectboxColumn("Category", options=["Food / Materials", "Venue", "Marketing", "Equipment", "Transportation", "Permit", "Prize", "Supplies", "Other"], help="Type of expense."),
        }
        edited_exp = st.data_editor(exp_view, num_rows="dynamic", use_container_width=True, height=450, column_config=config)
        if st.button("☑ Save Expenses Bulk Editor", type="primary"):
            name_to_id = dict(zip(events_df["event_name"], events_df["event_id"])) if not events_df.empty else {}
            edited_exp["event_id"] = edited_exp["event_name"].map(name_to_id).fillna("")
            save_finance_sheet("fundraising_expenses", edited_exp, EXPENSES_HEADERS, "expense_id", fin_mission, fin_cycle)
            st.rerun()

    with tab_goal:
        st.markdown("### ⊙ Organizational Goals")
        goal_cols = ["goal_id", "goal_name", "target_amount", "deadline", "purpose", "status"]
        goal_view = goals_df[goal_cols].copy() if not goals_df.empty else pd.DataFrame(columns=goal_cols)
        
        if goal_view.empty:
            goal_view = pd.concat([goal_view, pd.DataFrame([{"status": "In Progress", "target_amount": 0}])], ignore_index=True)
            
        goal_view["deadline"] = pd.to_datetime(goal_view["deadline"], errors="coerce").dt.date
        
        config = {
            "goal_id": None, 
            "deadline": st.column_config.DateColumn("Deadline", format="YYYY-MM-DD"),
            "status": st.column_config.SelectboxColumn("Status", options=["Planned", "In Progress", "Achieved", "Missed"]),
        }
        edited_goal = st.data_editor(goal_view, num_rows="dynamic", use_container_width=True, height=250, column_config=config)
        if st.button("☑ Save Goals", type="primary"):
            save_finance_sheet("fundraising_goals", edited_goal, GOALS_HEADERS, "goal_id", fin_mission, fin_cycle)
            st.rerun()

    with tab_analytics:
        st.markdown("### ⌁ Financial Analytics Dashboard")
        t_gross = events_df["actual_gross_revenue"].sum() if not events_df.empty else 0.0
        t_exp = events_df["actual_expenses"].sum() if not events_df.empty else 0.0
        t_net = t_gross - t_exp
        t_goal = goals_df["target_amount"].sum() if not goals_df.empty else 0.0
        progress_pct = (t_net / t_goal * 100) if t_goal > 0 else 0.0
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Gross Revenue", f"${t_gross:,.2f}")
        m2.metric("Total Expenses", f"${t_exp:,.2f}")
        m3.metric("Total Net Revenue", f"${t_net:,.2f}")
        m4.metric("Goal Progress", f"{progress_pct:.1f}%")
        st.divider()
        st.info("ⓘ Advanced executive charts are available on the Master Dashboard.")

# -----------------------------------------------------------------------------
# PAGE: PLANNER COMMAND
# -----------------------------------------------------------------------------
elif current_page == "▦ Planner":
    
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-content">
            <div class="av-logo-container">
                {custom_logo}
                <div>
                    <div class="eyebrow">Project AV • Operations</div>
                    <div class="title">Task Planner Command</div>
                </div>
            </div>
            <div class="subtitle" style="margin-top: 10px;">
              Create, assign, and track tasks across missions, divisions, and Gantt milestones.
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True
    )
    
    df_tasks = fetch_cached_df("planner_tasks", PLANNER_TASKS_COLS, st.session_state.force_refresh)
    df_check = fetch_cached_df("planner_task_checklist", PLANNER_CHECKLIST_COLS, st.session_state.force_refresh)
    df_comm = fetch_cached_df("planner_task_comments", PLANNER_COMMENTS_COLS, st.session_state.force_refresh)
    df_links = fetch_cached_df("gantt_task_links", GANTT_TASK_LINKS_COLS, st.session_state.force_refresh)
    df_notif = fetch_cached_df("planner_notifications_queue", PLANNER_NOTIFICATIONS_COLS, st.session_state.force_refresh)
    
    view_df = df_tasks.copy()
    if not view_df.empty:
        view_df = view_df[view_df["mission"] == plan_mission]
        view_df = view_df[view_df["cycle"] == plan_cycle]
        view_df = view_df[view_df["division"] == plan_division]
        if plan_assignee != "All": view_df = view_df[view_df["assigned_to"] == plan_assignee]

    tabs = st.tabs(["▦ Board View", "▦ Bulk Table Editor", "◈ Task Details", "❖ Team Directory"])
    
    with tabs[0]:
        st.markdown("### ▦ Board View")
        
        c_action, _ = st.columns([1, 4])
        with c_action:
            if st.button("+ Create Task", type="primary", use_container_width=True):
                create_task_dialog(plan_mission, plan_cycle, plan_division, member_opts, df_tasks, df_memb, df_notif)

        st.markdown("<br>", unsafe_allow_html=True)
        buckets = ["Backlog", "This Week", "In Progress", "Waiting / Blocked", "Review", "Completed"]
        b_cols = st.columns(len(buckets))
        
        for i, bucket in enumerate(buckets):
            with b_cols[i]:
                st.markdown(f"**{bucket}**")
                if not view_df.empty:
                    b_tasks = view_df[view_df["bucket"] == bucket]
                    for _, row in b_tasks.iterrows():
                        with st.container(border=True):
                            p_color = priority_color(row.get("priority", "Low"))
                            st.markdown(f"**◈ {row['title']}**")
                            st.markdown(f"<span style='color:{p_color}; font-size:12px;'>■ {row.get('priority')}</span>", unsafe_allow_html=True)
                            
                            valid_statuses = ["Not Started", "In Progress", "Blocked", "In Review", "Completed", "Cancelled"]
                            current_stat = row.get("status", "Not Started")
                            if current_stat not in valid_statuses: valid_statuses.append(current_stat)
                            
                            new_stat = st.selectbox("Status", valid_statuses, index=valid_statuses.index(current_stat), key=f"stat_{row['task_id']}", label_visibility="collapsed")
                            if new_stat != current_stat:
                                update_df = pd.DataFrame([row.to_dict()])
                                update_df["status"] = new_stat
                                if new_stat == "Completed":
                                    update_df["completed_date"] = date.today().strftime("%Y-%m-%d")
                                    update_df["percent_complete"] = 100
                                save_planner_data(update_df, df_tasks, PLANNER_TASKS_COLS, "planner_tasks", "task_id")
                                st.rerun()

                            asign = row.get('assigned_to', 'Unassigned')
                            if asign != 'Unassigned' and not df_memb.empty:
                                mem_row = df_memb[df_memb['member_name'] == asign]
                                if not mem_row.empty:
                                    em = mem_row.iloc[0].get('email', '')
                                    st.caption(f"Assignee: {asign} ({em})")
                                else:
                                    st.caption(f"Assignee: {asign}")
                            else:
                                st.caption(f"Assignee: {asign}")
                            
                            dd = str(row.get('due_date', ''))
                            if dd: st.caption(f"Due: {dd}")
                            if str(row.get("delay_flag", "False")).lower() == "true":
                                st.markdown("<span style='color:#ef4444; font-size:12px;'>⚠ Overdue</span>", unsafe_allow_html=True)
                                
                            if st.button("View Details", key=f"btn_view_{row['task_id']}"):
                                st.session_state["selected_task_id"] = row["task_id"]
                                st.info("Task selected! Open '◈ Task Details' tab.")

    with tabs[1]:
        st.markdown("### ▦ Bulk Table Editor")
        st.markdown("Edit tasks in bulk. Stable IDs will automatically merge with Google Sheets.")
        
        display_df = view_df.copy()
        if display_df.empty:
            display_df = pd.DataFrame(columns=PLANNER_TASKS_COLS)
            
        display_df["start_date"] = pd.to_datetime(display_df["start_date"], errors="coerce").dt.date
        display_df["due_date"] = pd.to_datetime(display_df["due_date"], errors="coerce").dt.date
        display_df["completed_date"] = pd.to_datetime(display_df["completed_date"], errors="coerce").dt.date
        
        config = {
            "task_id": None,
            "created_at": None,
            "updated_at": None,
            "delay_flag": None,
            "delay_days": None,
            "title": st.column_config.TextColumn("Task Title", help="Short name or description of the task."),
            "status": st.column_config.SelectboxColumn("Status", options=["Not Started", "In Progress", "Blocked", "In Review", "Completed", "Cancelled"], help="Current progress state."),
            "bucket": st.column_config.SelectboxColumn("Bucket", options=["Backlog", "This Week", "In Progress", "Waiting / Blocked", "Review", "Completed"], help="Board column for visual organization."),
            "priority": st.column_config.SelectboxColumn("Priority", options=["Low", "Medium", "High", "Critical"], help="Urgency level."),
            "mission": st.column_config.SelectboxColumn("Mission", options=["Mars", "Luna", "General"], help="Which mission this belongs to."),
            "division": st.column_config.SelectboxColumn("Division", options=list(DIVISIONS), help="Which subteam is responsible."),
            "assigned_to": st.column_config.SelectboxColumn("Assigned To", options=member_opts if member_opts else [""], help="Team member assigned to complete the work."),
            "start_date": st.column_config.DateColumn("Start Date", format="YYYY-MM-DD", help="When the work should begin."),
            "due_date": st.column_config.DateColumn("Due Date", format="YYYY-MM-DD", help="Deadline for the task."),
            "completed_date": st.column_config.DateColumn("Completed Date", format="YYYY-MM-DD", help="When it was actually finished."),
            "gantt_dependency_type": st.column_config.SelectboxColumn("Gantt Dep.", options=["None", "Starts Gantt Task", "Blocks Gantt Task", "Completes Gantt Task", "Supports Gantt Task"], help="How this links to the master Gantt schedule.")
        }
        
        edited_view = st.data_editor(display_df, num_rows="dynamic", use_container_width=True, height=600, column_config=config)
        
        if st.button("☑ Save Tasks Bulk Editor", type="primary"):
            save_planner_data(edited_view, df_tasks, PLANNER_TASKS_COLS, "planner_tasks", "task_id")
            update_gantt_links(edited_view, df_links)
            st.rerun()

    with tabs[2]:
        selected_id = st.session_state.get("selected_task_id", None)
        if selected_id and not view_df.empty and selected_id in view_df["task_id"].values:
            t_row = view_df[view_df["task_id"] == selected_id].iloc[0]
            st.subheader(f"◈ {t_row['title']}")
            
            det_c1, det_c2 = st.columns([2, 1])
            with det_c1:
                st.markdown(f"**Description:** {t_row.get('description', 'No description')}")
                
                assignee_name = t_row.get('assigned_to', 'Unassigned')
                st.markdown(f"**Assigned To:** {assignee_name}")
                if assignee_name != 'Unassigned' and not df_memb.empty:
                    mem_info = df_memb[df_memb['member_name'] == assignee_name]
                    if not mem_info.empty:
                        m_email = mem_info.iloc[0].get("email", "No email")
                        m_role = mem_info.iloc[0].get("role", "No role")
                        st.caption(f"✉ {m_email} | ⚙ {m_role}")
                        
                st.markdown(f"**CC:** {t_row.get('cc_people', '')}")
                st.markdown(f"**Linked Gantt Task:** {t_row.get('linked_gantt_task', 'None')}")
                if t_row.get('deliverable_link'):
                    st.markdown(f"[↗ View Deliverable]({t_row['deliverable_link']})")
                
                st.markdown("---")
                st.markdown("#### Checklist")
                t_check = df_check[df_check["task_id"] == selected_id].copy() if not df_check.empty else pd.DataFrame(columns=PLANNER_CHECKLIST_COLS)
                if not t_check.empty: t_check["task_id"] = selected_id
                
                ed_check = st.data_editor(t_check, num_rows="dynamic", use_container_width=True, key=f"chk_{selected_id}")
                if st.button("Save Checklist"):
                    for idx, r in ed_check.iterrows():
                        if not r.get("checklist_item_id"):
                            ed_check.at[idx, "checklist_item_id"] = str(uuid.uuid4())
                        ed_check.at[idx, "task_id"] = selected_id
                    save_planner_data(ed_check, df_check, PLANNER_CHECKLIST_COLS, "planner_task_checklist", "checklist_item_id")
                    st.rerun()
                
            with det_c2:
                with st.container(border=True):
                    st.markdown("**Status & Timeline**")
                    p_color = priority_color(t_row.get("priority", "Low"))
                    s_color = status_color(t_row.get("status", "Not Started"))
                    st.markdown(f"**Priority:** <span style='color:{p_color}'>■ {t_row.get('priority')}</span>", unsafe_allow_html=True)
                    st.markdown(f"**Status:** <span style='color:{s_color}'>● {t_row.get('status')}</span>", unsafe_allow_html=True)
                    st.markdown(f"**% Complete:** {t_row.get('percent_complete', 0)}%")
                    st.markdown(f"**Due Date:** {t_row.get('due_date', '')}")
                    if str(t_row.get("delay_flag", "False")).lower() == "true":
                        st.markdown(f"<span style='color:#ef4444'>⚠ Delayed by {t_row.get('delay_days', 0)} days</span>", unsafe_allow_html=True)
                    
                    st.markdown("---")
                    st.markdown("**Actions**")
                    if st.button("↻ Queue Reminder Email", help="Prepares an email notification for a future send cycle."):
                        queue_notification(t_row, df_notif)
                        st.success("Reminder queued.")

            st.markdown("---")
            st.markdown("#### Comments")
            t_comm = df_comm[df_comm["task_id"] == selected_id] if not df_comm.empty else pd.DataFrame(columns=PLANNER_COMMENTS_COLS)
            for _, c in t_comm.iterrows():
                with st.chat_message("user"):
                    st.markdown(f"**{c['author']}** ({c['created_at']})")
                    st.markdown(c['comment'])
            
            with st.form("new_comment"):
                c_text = st.text_area("Add a comment")
                c_submit = st.form_submit_button("Post Comment")
                if c_submit and c_text:
                    new_c = pd.DataFrame([{
                        "comment_id": str(uuid.uuid4()),
                        "task_id": selected_id,
                        "author": "Current PM", 
                        "comment": c_text,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }])
                    save_planner_data(new_c, df_comm, PLANNER_COMMENTS_COLS, "planner_task_comments", "comment_id")
                    st.rerun()
        else:
            st.info("ⓘ Select a task from the Board View to see details.")
            
    with tabs[3]:
        st.markdown("### ❖ Team Directory")
        st.markdown("Manage contact info for team members. These names will populate the 'Assigned To' dropdown in task creation.")
        
        display_mem = df_memb.copy()
        if display_mem.empty:
            display_mem = pd.DataFrame(columns=PLANNER_MEMBERS_COLS)
        
        mem_config = {
            "member_id": None,
            "created_at": None,
            "updated_at": None,
            "member_name": st.column_config.TextColumn("Member Name", help="First and Last name"),
            "email": st.column_config.TextColumn("Email Address", help="Used for future notifications"),
            "division": st.column_config.SelectboxColumn("Division", options=list(DIVISIONS)),
            "mission": st.column_config.SelectboxColumn("Mission", options=["Mars", "Luna", "General"]),
            "role": st.column_config.TextColumn("Role", help="E.g., Structural Lead"),
            "active": st.column_config.CheckboxColumn("Active Team Member"),
        }
        
        edited_mem = st.data_editor(display_mem, num_rows="dynamic", use_container_width=True, height=500, column_config=mem_config)
        
        if st.button("☑ Save Directory", type="primary"):
            save_planner_data(edited_mem, df_memb, PLANNER_MEMBERS_COLS, "planner_members", "member_id")
            st.rerun()
