from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st

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

# --- LOCAL RUNTIME STORAGE ---
# GitHub will not show empty folders, and Streamlit Cloud containers start fresh.
# These folders are created at runtime in the same folder as reporter.py/master.py.
APP_DIR = Path(__file__).resolve().parent
DRAFTS_DIR = APP_DIR / "reports_drafts"

def ensure_runtime_dirs() -> None:
    for directory in (DRAFTS_DIR, OUTBOX_DIR):
        Path(directory).mkdir(parents=True, exist_ok=True)

def safe_slug(value) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    return text.strip("_") or "blank"

def get_draft_path(pm, div, date_val):
    safe_pm = safe_slug(pm)
    safe_div = safe_slug(div)
    return DRAFTS_DIR / f"draft_{date_val}_{safe_div}_{safe_pm}.json"

ensure_runtime_dirs()

st.set_page_config(page_title="AV PM Weekly Reporter", page_icon="❖", layout="wide")

st.markdown(
    """
<style>
    :root {
        --bg-dark: #000000;
        --panel: #1e293b;
        --ink: #f8fafc;
        --muted: #94a3b8;
        --line: rgba(255, 255, 255, 0.12);
        --shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
    }
    
    /* Elegant Dark Gradient Background - Fading to Black */
    [data-testid="stAppViewContainer"] {
        background: radial-gradient(circle at top, #1e293b 0%, #000000 100%);
        background-attachment: fixed;
        color: var(--ink);
    }
    
    [data-testid="stHeader"] { background: rgba(15, 23, 42, 0); }
    
    /* Sidebar Gradient - Slate Blue to Cool Dark Grey */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e293b 0%, #111827 100%);
        border-right: 1px solid var(--line);
    }
    
    .block-container { padding-top: 2rem; max-width: 1440px; }
    
    .hero {
        position: relative;
        overflow: hidden;
        padding: 38px 42px;
        border-radius: 24px;
        background: var(--panel);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
        margin-bottom: 20px;
        color: #f8fafc;
    }
    .hero-content { position: relative; z-index: 2; max-width: 920px; }
    .eyebrow { color: #60a5fa; font-size: 13px; letter-spacing: .16em; text-transform: uppercase; font-weight: 800; }
    .title { font-size: clamp(32px, 4.5vw, 64px); font-weight: 900; letter-spacing: -.05em; line-height: 1; margin: 5px 0 15px 0; color: #ffffff; }
    .subtitle { color: #cbd5e1; font-size: 18px; max-width: 900px; line-height: 1.58; }
    
    /* AV Logo Styling */
    .av-logo-container { display: flex; align-items: center; gap: 20px; }
    .av-logo {
        font-family: 'Arial Black', sans-serif;
        font-size: 72px;
        letter-spacing: -14px;
        font-style: italic;
        line-height: 1;
        user-select: none;
    }
    .av-logo .a { color: #ef4444; text-shadow: 3px 3px 0px #7f1d1d; }
    .av-logo .v { color: #3b82f6; text-shadow: 3px 3px 0px #1e3a8a; mix-blend-mode: screen; }

    .glass {
        padding: 22px 24px;
        border-radius: 20px;
        background: var(--panel);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
        margin-bottom: 18px;
        color: var(--ink);
    }
    .division-pill {
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
    }
    .dot { width: 10px; height: 10px; border-radius: 999px; display: inline-block; }
    .metric-note { color: #94a3b8; font-size: 13px; margin-top: 10px;}
    
    /* Text overrides for dark mode */
    h1, h2, h3, p, label, span, div { text-shadow: none; color: var(--ink); }
    div[data-testid="stMarkdownContainer"] p, div[data-testid="stMarkdownContainer"] li { color: #cbd5e1; }
    div[data-testid="stMarkdownContainer"] h1, div[data-testid="stMarkdownContainer"] h2, div[data-testid="stMarkdownContainer"] h3 { color: #f8fafc; }
    .hero div[data-testid="stMarkdownContainer"] p, .hero p { color: #e2e8f0 !important; }
    
    /* Tabs Styling */
    button[data-baseweb="tab"] {
        color: #94a3b8 !important;
        font-weight: 700 !important;
        font-size: 16px !important;
        padding: 10px 20px !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #f8fafc !important;
    }
    div[data-baseweb="tab-highlight"] {
        background-color: #ef4444 !important; /* Red underline */
        height: 3px !important;
    }

    /* Solid Color Buttons */
    .stButton > button, [data-testid="stFormSubmitButton"] > button {
        background: #2563eb !important; /* Solid Blue */
        color: #ffffff !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
        box-shadow: 0 8px 20px rgba(37, 99, 235, 0.25) !important;
    }
    .stButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover { 
        background: #1d4ed8 !important; transform: translateY(-1px); 
    }
    
    .stDownloadButton > button {
        background: #ef4444 !important; /* Solid Red */
        color: #ffffff !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
        box-shadow: 0 8px 20px rgba(239, 68, 68, 0.25) !important;
    }
    .stDownloadButton > button:hover { background: #dc2626 !important; transform: translateY(-1px); }
    
    /* Fix inputs */
    input, textarea, [data-baseweb="select"] { color: #f8fafc !important; }
    [data-baseweb="base-input"], [data-baseweb="select"] > div {
        background: #0f172a !important;
        border-color: #334155 !important;
    }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="hero">
  <div class="hero-content">
    <div class="av-logo-container">
        <div class="av-logo"><span class="a">A</span><span class="v">V</span></div>
        <div>
            <div class="eyebrow">Project AV • PM input station</div>
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

with st.sidebar:
    st.header("Report setup")
    pm_name = st.text_input("PM name", placeholder="Ej. Alejandro / PM Robotic Arm")
    division = st.selectbox("Division", DIVISIONS, index=0)
    week_start = st.date_input("Week starting Monday", value=today_monday())
    if isinstance(week_start, tuple):
        week_start = week_start[0]
    if week_start.weekday() != 0:
        st.warning("La fecha seleccionada no es lunes. La app la acepta, pero para tracking semanal conviene usar lunes.")
    st.divider()
    st.caption("Score weights")
    for name, weight in METRIC_WEIGHTS.items():
        st.write(f"**{name.title()}**: {int(weight * 100)}%")

legend_html = "".join(
    f'<span class="division-pill"><span class="dot" style="background:{color}"></span>{division_name}</span>'
    for division_name, color in DIVISION_COLORS.items()
)
st.markdown(f'<div class="glass"><b>Official division legend</b><br><br>{legend_html}<div class="metric-note">Formula: {metric_weights_text()}</div></div>', unsafe_allow_html=True)


# --- DATA INITIALIZATION & DRAFT LOADING ---
init_df = pd.DataFrame(empty_input_rows())
if "hours_invested" not in init_df.columns:
    init_df["hours_invested"] = 0
if "communication_score" not in init_df.columns:
    init_df["communication_score"] = 0.0

current_draft_key = f"{pm_name}_{division}_{week_start}"
draft_path = get_draft_path(pm_name, division, week_start)

# Load draft safely
if "tracker_df" not in st.session_state or st.session_state.get("last_draft_key") != current_draft_key:
    if pm_name.strip() and draft_path.exists():
        try:
            with open(draft_path, "r") as f:
                draft_data = json.load(f)
            st.session_state.tracker_df = pd.DataFrame(draft_data)
        except Exception:
            st.session_state.tracker_df = init_df.copy()
    else:
        st.session_state.tracker_df = init_df.copy()
    
    st.session_state["last_draft_key"] = current_draft_key

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

# Side-by-side title and pop-over Help Icon
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

st.info("Type freely in any tab. The grids will NOT refresh or drop keystrokes until you click the save button below.")

# Wrapping the editors in a form stops Streamlit from rerunning the app while you type
with st.form("weekly_data_form"):
    tab1, tab2, tab3 = st.tabs(["❖ 1. Assignment", "❖ 2. Execution", "❖ 3. Performance"])

    with tab1:
        df1 = st.data_editor(
            st.session_state.tracker_df[["member_name", "role", "tasks_assigned", "hours_invested"]],
            key="editor_tab1",
            use_container_width=True,
            hide_index=True,
            column_config=col_config_base
        )
    with tab2:
        df2 = st.data_editor(
            st.session_state.tracker_df[["member_name", "tasks_completed", "tasks_on_time", "tasks_late", "blocked_tasks"]],
            key="editor_tab2",
            use_container_width=True,
            hide_index=True,
            column_config=col_config_locked
        )
    with tab3:
        df3 = st.data_editor(
            st.session_state.tracker_df[["member_name", "avg_quality_1_to_5", "meetings_required", "meetings_attended", "pm_confidence_1_to_5", "communication_score", "notes"]],
            key="editor_tab3",
            use_container_width=True,
            hide_index=True,
            column_config=col_config_locked
        )

    st.markdown("<br>", unsafe_allow_html=True)
    # The explicit save button to lock in edits
    submit_edits = st.form_submit_button("☑ Save Progress & Update Preview Below", use_container_width=True)

# Process the save event AFTER the form is submitted
if submit_edits:
    # df1 is the absolute truth for member_names. 
    st.session_state.tracker_df.update(df1)
    
    # Drop member_name from df2 and df3 so they don't overwrite the names with blanks
    st.session_state.tracker_df.update(df2.drop(columns=["member_name"]))
    st.session_state.tracker_df.update(df3.drop(columns=["member_name"]))
    
    if pm_name.strip():
        try:
            ensure_runtime_dirs()
            draft_path.parent.mkdir(parents=True, exist_ok=True)
            draft_path.write_text(
                json.dumps(st.session_state.tracker_df.to_dict(orient="records"), indent=4),
                encoding="utf-8",
            )
            st.session_state.show_success = True
        except Exception as exc:
            st.session_state.show_save_error = str(exc)
    else:
        st.session_state.show_warning = True
        
    # Force a refresh so Tab 2 and Tab 3 instantly show the new names you just typed
    st.rerun()

# Display the save messages outside the rerun cycle
if st.session_state.pop("show_success", False):
    st.success("Changes saved successfully to your local draft!")
if st.session_state.pop("show_warning", False):
    st.warning("Please enter your PM Name in the sidebar to backup your drafts locally.")
if st.session_state.get("show_save_error"):
    st.error(f"Draft save failed: {st.session_state.pop('show_save_error')}")

st.markdown('</div>', unsafe_allow_html=True)


# --- REPORT GENERATION ---
rows = st.session_state.tracker_df.fillna("").to_dict(orient="records")
report = make_report(pm_name=pm_name, division=division, week_start=week_start, rows=rows)
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
st.subheader("Export JSON")
st.write("The PM sends this JSON to leadership. If this is the same laptop, the saved file appears in `reports_outbox`.")

col_a, col_b = st.columns([1, 2])
with col_a:
    save_clicked = st.button("► Final Export & Submit Week", type="primary", use_container_width=True)
with col_b:
    st.code(str(OUTBOX_DIR), language="text")

if save_clicked:
    if not pm_name.strip():
        st.error("Falta el nombre del PM.")
    elif preview.empty:
        st.error("No hay miembros válidos para exportar.")
    else:
        try:
            ensure_runtime_dirs()
            path = save_report(report)
            st.success(f"Saved: {path.name}")
            st.info("Saved into the runtime `reports_outbox` folder. For permanent multi-user storage, the next step is Google Sheets/Supabase; this local file storage is only a temporary hosted test.")

            # Clear the draft file now that it's officially saved.
            if draft_path.exists():
                os.remove(draft_path)
        except Exception as exc:
            st.error(f"Final export failed: {exc}")

json_bytes = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
st.download_button(
    "Download this report JSON",
    data=json_bytes,
    file_name=f"{report['iso_year']}-W{report['iso_week']:02d}_{division.replace(' ', '_').replace('&', 'and')}_weekly_report.json",
    mime="application/json",
    use_container_width=True,
)
st.markdown('</div>', unsafe_allow_html=True)
