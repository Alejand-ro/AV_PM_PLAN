from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from av_common import (
    APP_NAME,
    BASE_DIR,
    DIVISION_COLORS,
    DIVISIONS,
    METRIC_WEIGHTS,
    OUTBOX_DIR,
    clean_filename,
    flags_to_text,
    make_report,
    metric_weights_text,
    save_report,
    today_monday,
)

DRAFT_DIR = BASE_DIR / "report_drafts"
DRAFT_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="AV PM Weekly Reporter", page_icon="🛰️", layout="wide")

# -----------------------------------------------------------------------------
# Visual system
# -----------------------------------------------------------------------------
st.markdown(
    """
<style>
    :root {
        --bg:#020409;
        --panel:rgba(255,255,255,.055);
        --panel2:rgba(255,255,255,.085);
        --line:rgba(255,255,255,.18);
        --line-strong:rgba(255,255,255,.35);
        --text:#f8fafc;
        --muted:#a6b0c3;
        --blue:#2563eb;
        --red:#ef4444;
        --shadow:0 28px 90px rgba(0,0,0,.48);
    }
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 10% -8%, rgba(37,99,235,.34), transparent 30%),
            radial-gradient(circle at 94% 5%, rgba(239,68,68,.24), transparent 30%),
            radial-gradient(circle at 42% 108%, rgba(255,255,255,.10), transparent 35%),
            linear-gradient(180deg, #020409 0%, #07111f 48%, #020409 100%);
        color: var(--text);
    }
    [data-testid="stHeader"] { background: rgba(0,0,0,0); }
    [data-testid="stSidebar"] {
        background: rgba(2,4,9,.82);
        border-right: 1px solid rgba(255,255,255,.18);
        backdrop-filter: blur(24px);
    }
    .block-container { max-width: 1320px; padding-top: 2rem; padding-bottom: 4rem; }
    .hero {
        position:relative;
        overflow:hidden;
        border-radius: 38px;
        padding: 38px 42px;
        margin-bottom: 20px;
        background:
            linear-gradient(135deg, rgba(255,255,255,.10), rgba(255,255,255,.035)),
            radial-gradient(circle at 78% 18%, rgba(37,99,235,.34), transparent 32%),
            radial-gradient(circle at 90% 88%, rgba(239,68,68,.20), transparent 34%);
        border:1px solid var(--line-strong);
        box-shadow: var(--shadow);
        color:var(--text);
    }
    .hero:after {
        content:"";
        position:absolute;
        inset:0;
        background-image:
            linear-gradient(rgba(255,255,255,.075) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,.075) 1px, transparent 1px);
        background-size: 36px 36px;
        mask-image: linear-gradient(90deg, transparent, black 20%, black 78%, transparent);
        opacity:.28;
    }
    .hero-content { position:relative; z-index:2; max-width: 980px; }
    .eyebrow { color:#bfdbfe; font-size:13px; letter-spacing:.18em; text-transform:uppercase; font-weight:900; }
    .title { font-size: clamp(42px, 5.8vw, 82px); line-height:.90; letter-spacing:-.07em; font-weight:950; color:white; margin: 10px 0; }
    .subtitle { color:#dbeafe; font-size:18px; line-height:1.55; max-width:900px; }
    .panel, .member-card, .stage-card, .preview-card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 30px;
        box-shadow: 0 20px 70px rgba(0,0,0,.30);
        backdrop-filter: blur(22px);
        color: var(--text);
    }
    .panel { padding: 22px 24px; margin-bottom:18px; }
    .stage-card { padding: 20px 22px; min-height: 142px; position:relative; overflow:hidden; }
    .stage-card:before { content:""; position:absolute; inset:auto -45px -60px auto; width:180px; height:140px; border-radius:999px; background:var(--glow); filter:blur(10px); opacity:.45; }
    .stage-number { color:#bfdbfe; font-size:12px; letter-spacing:.16em; text-transform:uppercase; font-weight:900; }
    .stage-title { color:white; font-size:22px; font-weight:930; letter-spacing:-.035em; margin-top:6px; }
    .stage-copy { color:#a6b0c3; font-size:13px; line-height:1.45; margin-top:6px; }
    .member-card { padding: 20px 22px; margin: 18px 0; }
    .member-header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom: 12px; }
    .member-title { color:white; font-size:21px; font-weight:920; letter-spacing:-.035em; }
    .section-label { color:#e2e8f0; font-weight:900; font-size:14px; letter-spacing:.08em; text-transform:uppercase; margin:18px 0 8px; }
    .hint { color:#a6b0c3; font-size:13px; line-height:1.45; }
    .division-pill {
        display:inline-flex; align-items:center; gap:9px; padding:8px 12px; border-radius:999px;
        background: rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.26);
        color:white; margin:0 8px 8px 0; font-weight:850; font-size:13px;
    }
    .dot { width:11px; height:11px; border-radius:999px; display:inline-block; border:1px solid rgba(255,255,255,.9); box-shadow:0 0 14px rgba(255,255,255,.18); }
    .status-chip { display:inline-flex; padding:5px 9px; border-radius:999px; border:1px solid rgba(255,255,255,.22); color:white; background:rgba(255,255,255,.07); font-size:12px; font-weight:800; }
    div[data-testid="stMarkdownContainer"] p, div[data-testid="stMarkdownContainer"] li { color: #cbd5e1; }
    div[data-testid="stMarkdownContainer"] h1, div[data-testid="stMarkdownContainer"] h2, div[data-testid="stMarkdownContainer"] h3 { color: #ffffff; }
    label, .stTextInput label, .stNumberInput label, .stTextArea label, .stDateInput label, .stSelectbox label { color:#e2e8f0 !important; font-weight:800 !important; }
    input, textarea, [data-baseweb="select"] { color:#f8fafc !important; }
    [data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
        background: rgba(255,255,255,.06) !important;
        border-color: rgba(255,255,255,.24) !important;
        border-radius: 14px !important;
    }
    [data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within, [data-baseweb="select"]:focus-within > div {
        border-color: rgba(255,255,255,.85) !important;
        box-shadow: 0 0 0 3px rgba(37,99,235,.22) !important;
    }
    .stButton > button, .stDownloadButton > button {
        background: linear-gradient(135deg, #2563eb, #ef4444) !important;
        color: #ffffff !important;
        border: 1px solid rgba(255,255,255,.34) !important;
        border-radius: 16px !important;
        font-weight: 900 !important;
        box-shadow: 0 16px 40px rgba(37,99,235,.20) !important;
    }
    .stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-1px); color:white !important; }
    div[data-testid="stMetric"] {
        background: rgba(255,255,255,.055);
        border: 1px solid rgba(255,255,255,.18);
        border-radius: 22px;
        padding: 14px 16px;
    }
    div[data-testid="stMetricValue"] { color:white !important; }
    .stDataFrame { border:1px solid rgba(255,255,255,.16); border-radius:18px; overflow:hidden; }
</style>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Draft persistence helpers
# -----------------------------------------------------------------------------

def _session_defaults() -> None:
    st.session_state.setdefault("draft_id", uuid.uuid4().hex[:10])
    st.session_state.setdefault("pm_name", "")
    st.session_state.setdefault("division", DIVISIONS[0])
    st.session_state.setdefault("week_start", today_monday())
    st.session_state.setdefault("member_count", 3)
    st.session_state.setdefault("loaded_draft_path", "")


def _row_keys(index: int) -> Dict[str, str]:
    return {
        "member_name": f"member_name_{index}",
        "role": f"role_{index}",
        "tasks_assigned": f"tasks_assigned_{index}",
        "tasks_completed": f"tasks_completed_{index}",
        "tasks_on_time": f"tasks_on_time_{index}",
        "tasks_late": f"tasks_late_{index}",
        "blocked_tasks": f"blocked_tasks_{index}",
        "avg_quality_1_to_5": f"avg_quality_1_to_5_{index}",
        "meetings_required": f"meetings_required_{index}",
        "meetings_attended": f"meetings_attended_{index}",
        "pm_confidence_1_to_5": f"pm_confidence_1_to_5_{index}",
        "notes": f"notes_{index}",
    }


def _ensure_row_defaults(index: int, row: Dict[str, Any] | None = None) -> None:
    row = row or {}
    defaults = {
        "member_name": "",
        "role": "",
        "tasks_assigned": 0,
        "tasks_completed": 0,
        "tasks_on_time": 0,
        "tasks_late": 0,
        "blocked_tasks": 0,
        "avg_quality_1_to_5": 0.0,
        "meetings_required": 0,
        "meetings_attended": 0,
        "pm_confidence_1_to_5": 3.0,
        "notes": "",
    }
    for field, key in _row_keys(index).items():
        st.session_state.setdefault(key, row.get(field, defaults[field]))


def _current_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i in range(int(st.session_state.get("member_count", 0))):
        keys = _row_keys(i)
        rows.append({field: st.session_state.get(key, "") for field, key in keys.items()})
    return rows


def _current_draft_payload() -> Dict[str, Any]:
    week_start = st.session_state.get("week_start") or today_monday()
    if isinstance(week_start, datetime):
        week_start = week_start.date()
    if isinstance(week_start, str):
        try:
            week_start = datetime.fromisoformat(week_start).date()
        except Exception:
            week_start = today_monday()
    return {
        "schema_version": "draft-1.0",
        "app": APP_NAME,
        "draft_id": st.session_state.get("draft_id", uuid.uuid4().hex[:10]),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "pm_name": st.session_state.get("pm_name", ""),
        "division": st.session_state.get("division", DIVISIONS[0]),
        "week_start": week_start.isoformat(),
        "member_count": int(st.session_state.get("member_count", 3)),
        "rows": _current_rows(),
    }


def _draft_name(payload: Dict[str, Any]) -> str:
    pm = clean_filename(payload.get("pm_name") or "unnamed_pm")
    div = clean_filename(payload.get("division") or "division")
    week = clean_filename(payload.get("week_start") or "week")
    did = clean_filename(payload.get("draft_id") or uuid.uuid4().hex[:8])
    return f"DRAFT_{week}_{div}_{pm}_{did}.json"


def save_draft(manual: bool = False) -> Path:
    payload = _current_draft_payload()
    if manual:
        path = DRAFT_DIR / _draft_name(payload)
    else:
        path = DRAFT_DIR / f"AUTOSAVE_{payload['draft_id']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    st.session_state.loaded_draft_path = str(path)
    return path


def list_drafts() -> List[Path]:
    return sorted(DRAFT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_draft(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    st.session_state.draft_id = payload.get("draft_id", uuid.uuid4().hex[:10])
    st.session_state.pm_name = payload.get("pm_name", "")
    division = payload.get("division", DIVISIONS[0])
    st.session_state.division = division if division in DIVISIONS else DIVISIONS[0]
    try:
        st.session_state.week_start = datetime.fromisoformat(payload.get("week_start", today_monday().isoformat())).date()
    except Exception:
        st.session_state.week_start = today_monday()
    rows = payload.get("rows", []) if isinstance(payload.get("rows"), list) else []
    st.session_state.member_count = max(int(payload.get("member_count", len(rows) or 3)), len(rows), 1)
    for i in range(st.session_state.member_count):
        _ensure_row_defaults(i, rows[i] if i < len(rows) and isinstance(rows[i], dict) else {})
    st.session_state.loaded_draft_path = str(path)


def new_blank_draft() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith((
            "member_name_", "role_", "tasks_assigned_", "tasks_completed_", "tasks_on_time_", "tasks_late_",
            "blocked_tasks_", "avg_quality_1_to_5_", "meetings_required_", "meetings_attended_", "pm_confidence_1_to_5_", "notes_",
        )):
            del st.session_state[key]
    st.session_state.draft_id = uuid.uuid4().hex[:10]
    st.session_state.pm_name = ""
    st.session_state.division = DIVISIONS[0]
    st.session_state.week_start = today_monday()
    st.session_state.member_count = 3
    st.session_state.loaded_draft_path = ""
    for i in range(3):
        _ensure_row_defaults(i)


_session_defaults()
for i in range(int(st.session_state.member_count)):
    _ensure_row_defaults(i)

# -----------------------------------------------------------------------------
# Header
# -----------------------------------------------------------------------------
st.markdown(
    """
<div class="hero">
  <div class="hero-content">
    <div class="eyebrow">Project AV • PM input station</div>
    <div class="title">Weekly Performance Report</div>
    <div class="subtitle">
      This is not task assignment. PMs use this to document weekly execution, quality, attendance, blockers, and confidence so leadership can track performance without chasing people manually.
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Sidebar setup + draft controls
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("Report setup")
    st.text_input("PM name", key="pm_name", placeholder="Ej. Alejandro / Arm PM")
    st.selectbox("Division", DIVISIONS, key="division")
    st.date_input("Week starting Monday", key="week_start")
    if isinstance(st.session_state.week_start, date) and st.session_state.week_start.weekday() != 0:
        st.warning("For clean weekly tracking, use a Monday date.")

    st.divider()
    st.subheader("Drafts")
    drafts = list_drafts()
    if drafts:
        labels = [f"{p.name}  •  {datetime.fromtimestamp(p.stat().st_mtime).strftime('%b %d %I:%M %p')}" for p in drafts]
        selected = st.selectbox("Load saved draft", options=list(range(len(drafts))), format_func=lambda i: labels[i])
        if st.button("Load selected draft", use_container_width=True):
            load_draft(drafts[selected])
            st.rerun()
    else:
        st.caption("No drafts saved yet.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save draft", use_container_width=True):
            path = save_draft(manual=True)
            st.success(f"Saved: {path.name}")
    with c2:
        if st.button("New draft", use_container_width=True):
            new_blank_draft()
            st.rerun()

    if st.session_state.get("loaded_draft_path"):
        st.caption(f"Active: {Path(st.session_state.loaded_draft_path).name}")

    st.divider()
    st.caption("Score weights")
    for name, weight in METRIC_WEIGHTS.items():
        st.write(f"**{name.title()}**: {int(weight * 100)}%")

legend_html = "".join(
    f'<span class="division-pill"><span class="dot" style="background:{color}"></span>{division_name}</span>'
    for division_name, color in DIVISION_COLORS.items()
)
st.markdown(
    f'<div class="panel"><b>Official division legend</b><br><br>{legend_html}<div class="hint">Division colors are intentionally preserved for filtering. General UI uses black/white with red/blue accents. Formula: {metric_weights_text()}</div></div>',
    unsafe_allow_html=True,
)

stage_cols = st.columns(3)
with stage_cols[0]:
    st.markdown('<div class="stage-card" style="--glow:rgba(37,99,235,.32)"><div class="stage-number">Stage 01</div><div class="stage-title">Assigned workload</div><div class="stage-copy">Who was active this week, what sub-area they belong to, and how many tasks they were responsible for.</div></div>', unsafe_allow_html=True)
with stage_cols[1]:
    st.markdown('<div class="stage-card" style="--glow:rgba(239,68,68,.30)"><div class="stage-number">Stage 02</div><div class="stage-title">Execution</div><div class="stage-copy">How many tasks got completed, how many were on time, late, or blocked. Incomplete work gets no delivery credit.</div></div>', unsafe_allow_html=True)
with stage_cols[2]:
    st.markdown('<div class="stage-card" style="--glow:rgba(255,255,255,.18)"><div class="stage-number">Stage 03</div><div class="stage-title">Quality & judgment</div><div class="stage-copy">Quality score, meeting attendance, PM confidence, and notes that leadership should know before the next meeting.</div></div>', unsafe_allow_html=True)

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("Weekly member reports")
st.write("Scroll downward. Each member has their own structured report card, so PMs do not have to fight an Excel-style sideways table.")

controls = st.columns([1, 1, 4])
with controls[0]:
    if st.button("+ Add member", use_container_width=True):
        st.session_state.member_count = int(st.session_state.member_count) + 1
        _ensure_row_defaults(int(st.session_state.member_count) - 1)
        st.rerun()
with controls[1]:
    if st.button("Remove last", use_container_width=True) and int(st.session_state.member_count) > 1:
        st.session_state.member_count = int(st.session_state.member_count) - 1
        st.rerun()
with controls[2]:
    st.caption("Blank member names are ignored in the final report, so extra cards are safe.")
st.markdown('</div>', unsafe_allow_html=True)

for i in range(int(st.session_state.member_count)):
    _ensure_row_defaults(i)
    keys = _row_keys(i)
    member_label = st.session_state.get(keys["member_name"]) or f"Member card {i + 1}"
    st.markdown('<div class="member-card">', unsafe_allow_html=True)
    st.markdown(f'<div class="member-header"><div class="member-title">{member_label}</div><span class="status-chip">Weekly row {i + 1}</span></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-label">Stage 01 • Assigned workload</div>', unsafe_allow_html=True)
    a, b, c = st.columns([1.25, 1.0, .75])
    with a:
        st.text_input("Member name", key=keys["member_name"], placeholder="Full name")
    with b:
        st.text_input("Role / subteam", key=keys["role"], placeholder="Controls, CAD, science, wiring...")
    with c:
        st.number_input("Tasks assigned", min_value=0, step=1, key=keys["tasks_assigned"], help="Total tasks this member was expected to move this week.")

    st.markdown('<div class="section-label">Stage 02 • Execution and blockers</div>', unsafe_allow_html=True)
    d, e, f, g = st.columns(4)
    with d:
        st.number_input("Tasks completed", min_value=0, step=1, key=keys["tasks_completed"])
    with e:
        st.number_input("Completed on time", min_value=0, step=1, key=keys["tasks_on_time"])
    with f:
        st.number_input("Completed late", min_value=0, step=1, key=keys["tasks_late"])
    with g:
        st.number_input("Blocked tasks", min_value=0, step=1, key=keys["blocked_tasks"])

    st.markdown('<div class="section-label">Stage 03 • Quality, attendance, PM judgment</div>', unsafe_allow_html=True)
    h, j, k, l = st.columns(4)
    with h:
        st.number_input("Quality avg 1–5", min_value=0.0, max_value=5.0, step=0.1, key=keys["avg_quality_1_to_5"], help="Use 0 if no tasks were completed.")
    with j:
        st.number_input("Meetings required", min_value=0, step=1, key=keys["meetings_required"])
    with k:
        st.number_input("Meetings attended", min_value=0, step=1, key=keys["meetings_attended"])
    with l:
        st.number_input("PM confidence 1–5", min_value=1.0, max_value=5.0, step=0.5, key=keys["pm_confidence_1_to_5"], help="Your confidence that this member is on track next week.")
    st.text_area("Notes / blockers / context", key=keys["notes"], placeholder="What should leadership know? Blockers, missing parts, communication issues, wins, risks...")
    st.markdown('</div>', unsafe_allow_html=True)

# Autosave after widgets render.
autosave_path = save_draft(manual=False)
st.caption(f"Autosaved locally: {autosave_path.name}")

rows = _current_rows()
report = make_report(
    pm_name=st.session_state.pm_name,
    division=st.session_state.division,
    week_start=st.session_state.week_start,
    rows=rows,
)
preview = pd.DataFrame(report["records"])

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("Auto-calculated preview")
if preview.empty:
    st.info("No real member rows yet. Add at least one member name to preview metrics.")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Members", len(preview))
    c2.metric("Avg performance", f"{preview['performance_pct'].mean():.1f}%")
    c3.metric("Open blockers", int(preview["blocked_tasks"].sum()))
    c4.metric("Critical / Watch", int(preview["status"].isin(["Critical", "Watch"]).sum()))

    visible = preview[[
        "member_name", "role", "tasks_assigned", "tasks_completed", "avg_quality_1_to_5",
        "completion_score", "quality_score", "delivery_score", "attendance_score",
        "performance_pct", "status", "flags", "notes",
    ]].copy()
    for col in ["completion_score", "quality_score", "delivery_score", "attendance_score"]:
        visible[col] = (visible[col] * 100).round(1).astype(str) + "%"
    visible["flags"] = visible["flags"].apply(flags_to_text)
    st.dataframe(visible, use_container_width=True, hide_index=True)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("Submit final report")
st.write("Drafts are for work-in-progress. Final submit creates the JSON that leadership can load into the master dashboard.")

col_a, col_b = st.columns([1, 2])
with col_a:
    submit = st.button("Submit final JSON locally", type="primary", use_container_width=True)
with col_b:
    st.caption(f"Final reports save to `{OUTBOX_DIR}`. Drafts stay in `{DRAFT_DIR}` and are not read by the master dashboard.")

if submit:
    if not st.session_state.pm_name.strip():
        st.error("Add PM name before final submit.")
    elif preview.empty:
        st.error("Add at least one member name before final submit.")
    else:
        final_path = save_report(report, OUTBOX_DIR)
        save_draft(manual=True)
        st.success(f"Final report saved: {final_path.name}")
        st.download_button(
            "Download final JSON",
            data=json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=final_path.name,
            mime="application/json",
            use_container_width=True,
        )
st.markdown('</div>', unsafe_allow_html=True)
