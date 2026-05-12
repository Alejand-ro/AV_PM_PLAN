from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from av_common import (
    APP_NAME,
    DIVISION_COLORS,
    DIVISIONS,
    INBOX_DIR,
    OUTBOX_DIR,
    annotate_attendance_streaks,
    flags_to_text,
    load_reports,
    metric_weights_text,
    today_monday,
    week_label,
)

st.set_page_config(page_title="AV Performance Command", page_icon="🧭", layout="wide")

COLOR_MAP = DIVISION_COLORS

# -----------------------------------------------------------------------------
# Visual system: black/white command center with red/blue UI accents.
# Official division colors remain untouched and are emphasized anywhere division
# identity matters.
# -----------------------------------------------------------------------------
st.markdown(
    """
<style>
    :root {
        --bg:#020409;
        --panel:rgba(255,255,255,.055);
        --panel2:rgba(255,255,255,.085);
        --line:rgba(255,255,255,.18);
        --line-strong:rgba(255,255,255,.34);
        --text:#f8fafc;
        --muted:#a6b0c3;
        --blue:#2563eb;
        --red:#ef4444;
        --shadow:0 28px 90px rgba(0,0,0,.50);
    }
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 8% -10%, rgba(37,99,235,.34), transparent 30%),
            radial-gradient(circle at 94% 0%, rgba(239,68,68,.25), transparent 31%),
            radial-gradient(circle at 52% 110%, rgba(255,255,255,.10), transparent 34%),
            linear-gradient(180deg, #020409 0%, #07111f 47%, #020409 100%);
        color: var(--text);
    }
    [data-testid="stHeader"] { background: rgba(0,0,0,0); }
    [data-testid="stSidebar"] {
        background: rgba(2,4,9,.86);
        border-right: 1px solid rgba(255,255,255,.18);
        backdrop-filter: blur(24px);
    }
    .block-container { max-width: 1460px; padding-top: 2rem; padding-bottom: 4rem; }
    .hero {
        position:relative;
        overflow:hidden;
        border-radius: 40px;
        padding: 40px 44px;
        margin-bottom: 20px;
        background:
            linear-gradient(135deg, rgba(255,255,255,.10), rgba(255,255,255,.035)),
            radial-gradient(circle at 75% 16%, rgba(37,99,235,.33), transparent 34%),
            radial-gradient(circle at 93% 90%, rgba(239,68,68,.22), transparent 32%);
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
        mask-image: linear-gradient(90deg, transparent, black 18%, black 80%, transparent);
        opacity:.30;
    }
    .hero-content { position:relative; z-index:2; max-width: 1040px; }
    .eyebrow { color:#bfdbfe; font-size:13px; letter-spacing:.18em; text-transform:uppercase; font-weight:900; }
    .title { font-size: clamp(46px, 6vw, 88px); line-height:.90; letter-spacing:-.075em; font-weight:950; color:white; margin: 10px 0; }
    .subtitle { color:#dbeafe; font-size:18px; line-height:1.58; max-width:940px; }
    .hero-pills { display:flex; flex-wrap:wrap; gap:10px; margin-top:22px; }
    .hero-pill { padding:9px 13px; border-radius:999px; background:rgba(255,255,255,.10); border:1px solid rgba(255,255,255,.22); color:#f8fafc; font-weight:850; font-size:13px; }
    .panel, .kpi, .division-card, .mission-card {
        background: var(--panel);
        border: 1px solid var(--line);
        box-shadow: 0 20px 70px rgba(0,0,0,.30);
        backdrop-filter: blur(24px);
        color: var(--text);
    }
    .panel { padding: 22px 24px; border-radius: 30px; margin-bottom: 18px; }
    .kpi { padding: 22px; border-radius: 30px; min-height: 154px; position:relative; overflow:hidden; }
    .kpi:before { content:""; position:absolute; width:170px; height:160px; right:-58px; top:-62px; background: var(--glow); border-radius:999px; filter: blur(10px); opacity:.45; }
    .kpi-label { color:#a6b0c3; font-size:12px; font-weight:900; letter-spacing:.12em; text-transform:uppercase; position:relative; z-index:2; }
    .kpi-value { color:#ffffff; font-size:39px; font-weight:950; letter-spacing:-.06em; margin-top:8px; position:relative; z-index:2; }
    .kpi-sub { color:#a6b0c3; font-size:14px; margin-top:6px; position:relative; z-index:2; }
    .mission-strip { display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:14px; margin-bottom:18px; }
    .mission-card { min-height:118px; border-radius:28px; padding:18px; position:relative; overflow:hidden; }
    .mission-card:after { content:""; position:absolute; inset:auto -60px -70px auto; width:220px; height:150px; border-radius:999px; background:var(--glow); filter:blur(10px); opacity:.45; }
    .mission-title { font-weight:930; letter-spacing:-.03em; color:#fff; font-size:18px; }
    .mission-sub { color:#a6b0c3; font-size:13px; margin-top:6px; max-width:320px; line-height:1.45; }
    .division-card { border-radius:28px; padding:18px; min-height:146px; border-top: 5px solid var(--division-color); position:relative; overflow:hidden; }
    .division-card:after { content:""; position:absolute; inset:auto -70px -80px auto; width:230px; height:160px; border-radius:999px; background:var(--division-color); filter:blur(14px); opacity:.22; }
    .division-title { color:#fff; font-size:18px; font-weight:930; letter-spacing:-.03em; position:relative; z-index:2; }
    .division-score { color:#fff; font-size:34px; font-weight:950; letter-spacing:-.05em; margin-top:8px; position:relative; z-index:2; }
    .division-sub { color:#a6b0c3; font-size:13px; margin-top:5px; position:relative; z-index:2; }
    .division-pill, .chip {
        display:inline-flex; align-items:center; gap:8px; padding:8px 12px; border-radius:999px; margin:0 8px 8px 0;
        font-size:13px; font-weight:850; border:1px solid rgba(255,255,255,.28); background:rgba(255,255,255,.065); color:#fff;
    }
    .dot { width:11px; height:11px; border-radius:999px; display:inline-block; border:1px solid rgba(255,255,255,.95); box-shadow:0 0 16px rgba(255,255,255,.20); }
    .soft { color:#a6b0c3; }
    div[data-testid="stMarkdownContainer"] p, div[data-testid="stMarkdownContainer"] li { color: #cbd5e1; }
    div[data-testid="stMarkdownContainer"] h1, div[data-testid="stMarkdownContainer"] h2, div[data-testid="stMarkdownContainer"] h3 { color: #ffffff; }
    label, .stMultiSelect label, .stSelectbox label, .stCheckbox label { color:#e2e8f0 !important; font-weight:800 !important; }
    input, textarea, [data-baseweb="select"] { color:#f8fafc !important; }
    [data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
        background: rgba(255,255,255,.06) !important;
        border-color: rgba(255,255,255,.24) !important;
        border-radius: 14px !important;
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
    div[data-testid="stMetric"] { background: rgba(255,255,255,.055); border: 1px solid rgba(255,255,255,.18); border-radius: 22px; padding: 14px 16px; }
    div[data-testid="stMetricValue"] { color:white !important; }
    .stDataFrame { border:1px solid rgba(255,255,255,.16); border-radius:18px; overflow:hidden; }
</style>
""",
    unsafe_allow_html=True,
)


def plotly_theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.025)",
        font=dict(color="#f8fafc"),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(255,255,255,.18)", borderwidth=1),
        margin=dict(l=20, r=20, t=50, b=30),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,.08)", zerolinecolor="rgba(255,255,255,.16)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,.08)", zerolinecolor="rgba(255,255,255,.16)")
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
# Header
# -----------------------------------------------------------------------------
st.markdown(
    """
<div class="hero">
  <div class="hero-content">
    <div class="eyebrow">Project AV • Leadership command dashboard</div>
    <div class="title">Performance Command</div>
    <div class="subtitle">
      A weekly operating picture for PM follow-up: division trends, member risk, attendance issues, blockers, missing reports, and performance movement over time.
    </div>
    <div class="hero-pills">
      <span class="hero-pill">No task assignment</span>
      <span class="hero-pill">PM report intake</span>
      <span class="hero-pill">JSON-based MVP</span>
      <span class="hero-pill">Formula: completion • quality • delivery • attendance • confidence</span>
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Data sources")
    include_inbox = st.checkbox("Read reports_inbox", value=True)
    include_outbox = st.checkbox("Read reports_outbox", value=True)
    include_legacy_demo = st.checkbox("Show legacy demo data", value=False, help="Keep this off unless you intentionally want fake bundled test reports.")
    read_dirs: list[Path] = []
    if include_inbox:
        read_dirs.append(INBOX_DIR)
    if include_outbox:
        read_dirs.append(OUTBOX_DIR)
    st.caption(f"Inbox: `{INBOX_DIR}`")
    st.caption(f"Outbox: `{OUTBOX_DIR}`")
    st.divider()
    st.caption("Score weights")
    for name, weight in {"completion": .30, "quality": .25, "delivery": .20, "attendance": .15, "confidence": .10}.items():
        st.write(f"**{name.title()}**: {int(weight * 100)}%")

raw_df, warnings = load_reports(read_dirs, include_legacy_demo=include_legacy_demo)
df = annotate_attendance_streaks(raw_df)

legend_html = "".join(
    f'<span class="division-pill"><span class="dot" style="background:{color}"></span>{division}</span>'
    for division, color in DIVISION_COLORS.items()
)
st.markdown(
    f'<div class="panel"><b>Official division legend</b><br><br>{legend_html}<div class="soft">These division colors are fixed and used on division cards, charts, filters, and markers. General UI remains black/white with red/blue accents. Formula: {metric_weights_text()}</div></div>',
    unsafe_allow_html=True,
)

if warnings:
    with st.expander("Import warnings / skipped files"):
        for warning in warnings:
            st.warning(warning)

if df.empty:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("No real reports loaded yet")
    st.write("The dashboard is clean. It will not invent placeholder data. Put final PM JSON files into `reports_inbox/` or create reports from the PM app into `reports_outbox/`.")
    st.code("streamlit run av_pm_reporter.py", language="powershell")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# -----------------------------------------------------------------------------
# Filters
# -----------------------------------------------------------------------------
all_weeks = sorted([w for w in df["week_start"].dropna().unique().tolist() if w])
all_divisions = [d for d in DIVISIONS if d in set(df["division"].dropna())]
all_statuses = sorted(df["status"].dropna().unique().tolist())

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("Filters")
f1, f2, f3 = st.columns([1.2, 1.4, 1])
with f1:
    selected_weeks = st.multiselect("Weeks", options=all_weeks, default=all_weeks[-6:] if len(all_weeks) > 6 else all_weeks, format_func=week_label)
with f2:
    selected_divisions = st.multiselect("Divisions", options=DIVISIONS, default=all_divisions or DIVISIONS)
with f3:
    selected_statuses = st.multiselect("Status", options=all_statuses, default=all_statuses)
st.markdown('</div>', unsafe_allow_html=True)

filtered = df.copy()
if selected_weeks:
    filtered = filtered[filtered["week_start"].isin(selected_weeks)]
if selected_divisions:
    filtered = filtered[filtered["division"].isin(selected_divisions)]
if selected_statuses:
    filtered = filtered[filtered["status"].isin(selected_statuses)]

if filtered.empty:
    st.warning("No records match the current filters.")
    st.stop()

current_week = max(filtered["week_start_dt"].dropna()) if filtered["week_start_dt"].notna().any() else None
current_week_str = current_week.date().isoformat() if current_week is not None else None
current_df = filtered[filtered["week_start"] == current_week_str] if current_week_str else filtered
previous_weeks = sorted([w for w in filtered["week_start"].unique().tolist() if current_week_str and w < current_week_str])
prev_df = filtered[filtered["week_start"] == previous_weeks[-1]] if previous_weeks else pd.DataFrame(columns=filtered.columns)

org_avg = float(current_df["performance_pct"].mean()) if not current_df.empty else None
prev_avg = float(prev_df["performance_pct"].mean()) if not prev_df.empty else None
risk_count = int(current_df["status"].isin(["Critical", "Watch"]).sum()) if not current_df.empty else 0
blockers = int(current_df["blocked_tasks"].sum()) if not current_df.empty else 0
attendance_flags = int((current_df["attendance_risk_streak"] >= 2).sum()) if not current_df.empty else 0
missing_reports = [d for d in DIVISIONS if current_week_str and d not in set(current_df["division"])]

# -----------------------------------------------------------------------------
# Mission cards and KPIs
# -----------------------------------------------------------------------------
st.markdown(
    """
<div class="mission-strip">
  <div class="mission-card" style="--glow:rgba(37,99,235,.32)"><div class="mission-title">Ask better PM questions</div><div class="mission-sub">Walk into leader meetings already knowing who is drifting, who is blocked, and which division needs attention.</div></div>
  <div class="mission-card" style="--glow:rgba(239,68,68,.28)"><div class="mission-title">Track trends, not vibes</div><div class="mission-sub">Compare current performance against past weeks using the same formula every time.</div></div>
  <div class="mission-card" style="--glow:rgba(255,255,255,.18)"><div class="mission-title">Keep PM work lightweight</div><div class="mission-sub">PMs submit weekly execution data; this dashboard turns it into leadership signal.</div></div>
</div>
""",
    unsafe_allow_html=True,
)

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(kpi_card("Current org average", f"{org_avg:.1f}%" if org_avg is not None else "—", metric_delta_text(org_avg, prev_avg), "rgba(37,99,235,.34)"), unsafe_allow_html=True)
with k2:
    st.markdown(kpi_card("Current risk members", str(risk_count), "Watch + Critical in selected latest week", "rgba(239,68,68,.34)"), unsafe_allow_html=True)
with k3:
    st.markdown(kpi_card("Open blockers", str(blockers), "Tasks marked blocked by PMs", "rgba(255,255,255,.18)"), unsafe_allow_html=True)
with k4:
    st.markdown(kpi_card("Attendance streak flags", str(attendance_flags), "2+ consecutive low-attendance weeks", "rgba(37,99,235,.24)"), unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Division cards
# -----------------------------------------------------------------------------
st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("Current division pulse")
st.write("These cards preserve the official division colors so you can scan/filter fast during meetings.")
cols = st.columns(5)
for idx, division in enumerate(DIVISIONS):
    div_df = current_df[current_df["division"] == division]
    score = div_df["performance_pct"].mean() if not div_df.empty else None
    members = len(div_df)
    risks = int(div_df["status"].isin(["Critical", "Watch"]).sum()) if not div_df.empty else 0
    blockers_div = int(div_df["blocked_tasks"].sum()) if not div_df.empty else 0
    with cols[idx % 5]:
        value = "No report" if score is None else f"{score:.1f}%"
        sub = "Missing current week" if score is None else f"{members} members • {risks} risks • {blockers_div} blockers"
        st.markdown(
            f'<div class="division-card" style="--division-color:{COLOR_MAP[division]}"><div class="division-title">{division}</div><div class="division-score">{value}</div><div class="division-sub">{sub}</div></div>',
            unsafe_allow_html=True,
        )
st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Charts
# -----------------------------------------------------------------------------
left, right = st.columns([1.25, 1])
with left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("Performance trend by division")
    weekly_div = filtered.groupby(["week_start", "division"], as_index=False)["performance_pct"].mean()
    fig = px.line(
        weekly_div,
        x="week_start",
        y="performance_pct",
        color="division",
        markers=True,
        color_discrete_map=COLOR_MAP,
        labels={"performance_pct": "Performance %", "week_start": "Week"},
    )
    fig.update_traces(line=dict(width=3), marker=dict(size=9, line=dict(width=1.5, color="#ffffff")))
    fig.update_yaxes(range=[0, 100])
    st.plotly_chart(plotly_theme(fig), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("Current week division average")
    bar_df = current_df.groupby("division", as_index=False)["performance_pct"].mean()
    bar_df["division"] = pd.Categorical(bar_df["division"], categories=DIVISIONS, ordered=True)
    bar_df = bar_df.sort_values("division")
    fig2 = px.bar(
        bar_df,
        x="division",
        y="performance_pct",
        color="division",
        color_discrete_map=COLOR_MAP,
        labels={"performance_pct": "Performance %", "division": "Division"},
    )
    fig2.update_traces(marker_line_color="#ffffff", marker_line_width=1.5)
    fig2.update_yaxes(range=[0, 100])
    fig2.update_layout(showlegend=False)
    st.plotly_chart(plotly_theme(fig2), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

m1, m2 = st.columns(2)
with m1:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("Metric breakdown by division")
    metric_df = current_df.groupby("division", as_index=False)[["completion_score", "quality_score", "delivery_score", "attendance_score", "confidence_score"]].mean()
    if not metric_df.empty:
        melted = metric_df.melt(id_vars="division", var_name="metric", value_name="score")
        melted["score"] = melted["score"] * 100
        fig3 = px.bar(
            melted,
            x="metric",
            y="score",
            color="division",
            barmode="group",
            color_discrete_map=COLOR_MAP,
            labels={"score": "Score %", "metric": "Metric"},
        )
        fig3.update_traces(marker_line_color="#ffffff", marker_line_width=.9)
        fig3.update_yaxes(range=[0, 100])
        st.plotly_chart(plotly_theme(fig3), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with m2:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("Status distribution")
    status_df = current_df.groupby(["division", "status"], as_index=False).size()
    if not status_df.empty:
        fig4 = px.bar(status_df, x="status", y="size", color="division", barmode="group", color_discrete_map=COLOR_MAP, labels={"size": "Members"})
        fig4.update_traces(marker_line_color="#ffffff", marker_line_width=.9)
        st.plotly_chart(plotly_theme(fig4), use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Risk review
# -----------------------------------------------------------------------------
st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("Leadership risk review")
risk_df = current_df[
    current_df["status"].isin(["Critical", "Watch"])
    | (current_df["blocked_tasks"] > 0)
    | (current_df["attendance_risk_streak"] >= 2)
].copy()
if risk_df.empty:
    st.success("No current risk rows under the selected filters.")
else:
    risk_df["flags_text"] = risk_df["flags"].apply(flags_to_text)
    risk_df = risk_df.sort_values(["performance_pct", "blocked_tasks"], ascending=[True, False])
    st.dataframe(
        risk_df[[
            "division", "member_name", "role", "performance_pct", "status", "blocked_tasks",
            "attendance_risk_streak", "flags_text", "notes", "pm_name",
        ]],
        use_container_width=True,
        hide_index=True,
    )
st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Missing reports and raw table
# -----------------------------------------------------------------------------
col_x, col_y = st.columns([.9, 1.1])
with col_x:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("Missing division reports")
    if missing_reports:
        for div in missing_reports:
            st.markdown(f'<span class="division-pill"><span class="dot" style="background:{COLOR_MAP[div]}"></span>{div}</span>', unsafe_allow_html=True)
        st.warning("These divisions have no report in the latest selected week.")
    else:
        st.success("All official divisions have a report in the latest selected week.")
    st.markdown('</div>', unsafe_allow_html=True)

with col_y:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("Meeting prompts")
    st.write("Use the dashboard to ask targeted questions instead of asking every PM for a generic update.")
    st.markdown(
        """
- **Healthy division:** “You are trending well. What is the plan for next week?”
- **Low completion:** “Which tasks were over-scoped or blocked?”
- **Low quality:** “What needs review before this becomes a bigger issue?”
- **Attendance streak:** “Is this member still active, unavailable, or slipping?”
"""
    )
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("Raw filtered data")
raw_view = filtered.copy()
raw_view["flags"] = raw_view["flags"].apply(flags_to_text)
raw_view = raw_view.sort_values(["week_start", "division", "member_name"], ascending=[False, True, True])
st.dataframe(raw_view, use_container_width=True, hide_index=True)
st.download_button(
    "Download filtered CSV",
    data=raw_view.to_csv(index=False).encode("utf-8"),
    file_name="av_performance_filtered.csv",
    mime="text/csv",
    use_container_width=True,
)
st.markdown('</div>', unsafe_allow_html=True)
