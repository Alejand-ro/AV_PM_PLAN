from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
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

st.set_page_config(page_title="AV Admin Command", page_icon="⚙️", layout="wide")

# GitHub does not store empty folders, and Streamlit Cloud starts with a fresh
# container. Create the runtime folders that this local-JSON MVP reads from.
for _runtime_dir in (INBOX_DIR, OUTBOX_DIR):
    Path(_runtime_dir).mkdir(parents=True, exist_ok=True)

COLOR_MAP = DIVISION_COLORS
STATUS_COLORS = {"Healthy": "#22c55e", "Watch": "#eab308", "Critical": "#ef4444"}

# -----------------------------------------------------------------------------
# Visual system: Slate/Black Gradients, Muted Accents, High Spacing
# -----------------------------------------------------------------------------
st.markdown(
    """
<style>
    :root {
        --panel: rgba(30, 41, 59, 0.45); 
        --panel-light: rgba(51, 65, 85, 0.35); 
        --ink: #f8fafc;
        --line: rgba(255, 255, 255, 0.12);
        --shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
        --blue: #2563eb;
        --red: #ef4444;
    }
    
    [data-testid="stAppViewContainer"] {
        background: radial-gradient(circle at top, #1e293b 0%, #000000 100%);
        background-attachment: fixed;
        color: var(--ink);
    }
    
    [data-testid="stHeader"] { background: rgba(0,0,0,0); }
    
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(30,41,59,0.65) 0%, rgba(17,24,39,0.85) 100%);
        border-right: 1px solid var(--line);
        backdrop-filter: blur(28px);
        -webkit-backdrop-filter: blur(28px);
    }
    
    /* Wider container and more padding */
    .block-container { max-width: 1560px; padding-top: 2.5rem; padding-bottom: 4rem; }
    
    .hero {
        position:relative;
        overflow:hidden;
        border-radius: 24px;
        padding: 48px 52px; 
        margin-bottom: 36px; 
        background: var(--panel);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
        color: var(--ink);
    }
    
    .av-logo-container { display:flex; align-items:center; gap:20px; margin-bottom: 10px;}
    
    /* 3D Logo Restored */
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
    
    .hero-content { position:relative; z-index:2; max-width: 1040px; }
    .eyebrow { color:#bfdbfe; font-size:13px; letter-spacing:.18em; text-transform:uppercase; font-weight:900; }
    
    .title { 
        font-size: clamp(42px, 5.5vw, 84px); /* Massively increased size */
        line-height:.90; 
        letter-spacing:-.04em; 
        font-weight:950; 
        color:white; 
        margin: 15px 0; 
        display: flex;
        align-items: center;
        gap: 20px;
        flex-wrap: wrap;
    }
    
    .admin-title {
        background: rgba(255, 255, 255, 0.30); /* Much lighter/brighter */
        backdrop-filter: blur(24px); 
        -webkit-backdrop-filter: blur(24px);
        color: #ffffff;
        padding: 10px 24px; /* Bolder padding */
        border-radius: 999px; 
        font-size: 0.38em; /* Balanced against the new huge title text */
        font-weight: 900;
        letter-spacing: 0.15em;
        border: 1px solid rgba(255, 255, 255, 0.60); /* Brighter rim */
        box-shadow: 0 8px 24px rgba(0,0,0,0.30), inset 0 2px 4px rgba(255,255,255,0.40); /* Pronounced inner & outer glow */
        text-transform: uppercase;
        display: inline-block;
        transform: translateY(-4px); 
    }

    .subtitle { color:#cbd5e1; font-size:18px; line-height:1.58; max-width:940px; margin-top: 15px;}
    
    .panel {
        background: var(--panel);
        backdrop-filter: blur(24px);
        -webkit-backdrop-filter: blur(24px);
        border: 1px solid var(--line);
        box-shadow: var(--shadow);
        color: var(--ink);
        padding: 32px 36px; 
        border-radius: 16px; 
        margin-bottom: 32px; 
    }
    
    .kpi { 
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
    }
    
    .kpi:before { content:""; position:absolute; width:170px; height:160px; right:-58px; top:-62px; background: var(--glow); border-radius:999px; filter: blur(25px); opacity:.08; }
    
    .kpi-label { color:#94a3b8; font-size:12px; font-weight:900; letter-spacing:.12em; text-transform:uppercase; position:relative; z-index:2; }
    .kpi-value { color:#ffffff; font-size:48px; font-weight:950; letter-spacing:-.06em; margin-top:8px; position:relative; z-index:2; }
    .kpi-sub { color:#cbd5e1; font-size:14px; margin-top:6px; position:relative; z-index:2; }
    
    /* Tabs Styling Sync */
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
        background-color: var(--red) !important;
        height: 3px !important;
    }

    .stDownloadButton > button {
        background: var(--red) !important; 
        color: #ffffff !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
        box-shadow: 0 8px 20px rgba(239, 68, 68, 0.25) !important;
    }
    .stDownloadButton > button:hover { background: #dc2626 !important; transform: translateY(-1px); }
    
    h1, h2, h3, p, li { color: var(--ink) !important; }
    .chart-desc { font-size: 14px; color: #94a3b8; margin-top: -10px; margin-bottom: 20px; border-left: 3px solid var(--blue); padding-left: 12px;}
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
# Admin Header
# -----------------------------------------------------------------------------
st.markdown(
    """
<div class="hero">
  <div class="hero-content">
    <div class="av-logo-container">
        <div class="av-logo"><span class="a">A</span><span class="v">V</span></div>
        <div class="eyebrow" style="margin-top: 15px;">Executive Level Operations</div>
    </div>
    <div class="title">Performance <span class="admin-title">Admin Command</span></div>
    <div class="subtitle">
      Comprehensive analytical breakdown of division trends, execution bottlenecks, communication gaps, and workforce health. 
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# Load data initially to get unique divisions for the sidebar
raw_df, warnings = load_reports([INBOX_DIR, OUTBOX_DIR], include_legacy_demo=False)
df = annotate_attendance_streaks(raw_df)

if "communication_score" not in df.columns:
    df["communication_score"] = 3.0
else:
    df["communication_score"] = df["communication_score"].fillna(3.0)

available_divisions = sorted([d for d in df["division"].unique() if pd.notna(d)]) if "division" in df.columns else []

with st.sidebar:
    st.header("⚙️ Data Configuration")
    include_inbox = st.checkbox("Read reports_inbox", value=True)
    include_outbox = st.checkbox("Read reports_outbox", value=True)
    include_legacy_demo = st.checkbox("Include Demo Data", value=False)
    
    st.divider()
    
    st.header("⌖ Division Toggle")
    st.caption("Isolate specific teams in the analytics")
    selected_divs = st.multiselect("Active Divisions", options=available_divisions, default=available_divisions)
    
    st.divider()
    st.caption("Algorithm Weights")
    for name, weight in {"completion": .30, "quality": .25, "delivery": .20, "attendance": .15, "confidence": .10}.items():
        st.write(f"**{name.title()}**: {int(weight * 100)}%")

# Reload based on actual user checks
read_dirs: list[Path] = []
if include_inbox: read_dirs.append(INBOX_DIR)
if include_outbox: read_dirs.append(OUTBOX_DIR)

raw_df, warnings = load_reports(read_dirs, include_legacy_demo=include_legacy_demo)
df = annotate_attendance_streaks(raw_df)

if "communication_score" not in df.columns:
    df["communication_score"] = 3.0
else:
    df["communication_score"] = df["communication_score"].fillna(3.0)

if df.empty:
    st.warning("No data found yet. The app created reports_inbox and reports_outbox automatically, but no JSON reports are currently available in this Streamlit runtime.")
    st.stop()

# -----------------------------------------------------------------------------
# Global Filters & KPIs
# -----------------------------------------------------------------------------
all_weeks = sorted([w for w in df["week_start"].dropna().unique().tolist() if w])

# Removed the panel div around the multiselect to give it breathing room
st.markdown('<div style="margin-bottom: 24px; max-width: 800px;">', unsafe_allow_html=True)
selected_weeks = st.multiselect("Timeline Filter (Affects entire dashboard)", options=all_weeks, default=all_weeks[-6:] if len(all_weeks) > 6 else all_weeks, format_func=week_label)
st.markdown('</div>', unsafe_allow_html=True)

# Apply filters
filtered = df[
    (df["week_start"].isin(selected_weeks) if selected_weeks else True) &
    (df["division"].isin(selected_divs) if selected_divs else True)
].copy()

if filtered.empty:
    st.warning("No records match the current Timeline and Division filters.")
    st.stop()

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
with k1: st.markdown(kpi_card("Current Filter Average", f"{org_avg:.1f}%" if org_avg is not None else "—", metric_delta_text(org_avg, prev_avg), "#2563eb"), unsafe_allow_html=True)
with k2: st.markdown(kpi_card("At-Risk Members", str(risk_count), "Watch + Critical statuses", "#ef4444"), unsafe_allow_html=True)
with k3: st.markdown(kpi_card("Active Blockers", str(blockers), "Total tasks currently blocked", "#ffffff"), unsafe_allow_html=True)
with k4: st.markdown(kpi_card("Attendance Risks", str(attendance_flags), "Consecutive absence streaks", "#3b82f6"), unsafe_allow_html=True)

st.markdown('<br>', unsafe_allow_html=True) # Extra breathing room before tabs

# -----------------------------------------------------------------------------
# TABBED DASHBOARD LAYOUT
# -----------------------------------------------------------------------------
tab_exec, tab_div, tab_ops, tab_action = st.tabs([
    "❖ Executive Overview", 
    "🔬 Division Intelligence", 
    "⛒ Bottlenecks & Health", 
    "⚠️ Action Center"
])

# ==========================================
# TAB 1: EXECUTIVE OVERVIEW
# ==========================================
with tab_exec:
    st.markdown('<br>', unsafe_allow_html=True) # Space inside tab
    r1c1, r1c2 = st.columns([1.5, 1])
    
    with r1c1:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.subheader("Historical Trajectory")
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
            
            fig5 = go.Figure()
            fig5.add_trace(go.Scatterpolar(
                r=org_means_list, theta=categories_loop, fill='toself',
                fillcolor='rgba(37, 99, 235, 0.4)', line=dict(color='#3b82f6', width=2), name='Filter Average'
            ))
            fig5.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100], gridcolor="rgba(255,255,255,0.1)")),
                showlegend=False, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=20, b=20, l=20, r=20)
            )
            st.plotly_chart(fig5, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 2: DIVISION INTELLIGENCE
# ==========================================
with tab_div:
    st.markdown('<br>', unsafe_allow_html=True)
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
    
    if not current_df.empty:
        divisions_present = sorted(current_df["division"].unique())
        cols = st.columns(len(divisions_present))
        
        heat_df = current_df.groupby("division")[["completion_score", "quality_score", "delivery_score", "attendance_score", "confidence_score"]].mean() * 20
        
        for idx, div_name in enumerate(divisions_present):
            with cols[idx]:
                st.markdown(f'<div class="panel" style="padding: 20px; text-align: center;">', unsafe_allow_html=True)
                st.markdown(f"<h4 style='color: {COLOR_MAP.get(div_name, '#ffffff')}; margin-bottom: 10px;'>{div_name}</h4>", unsafe_allow_html=True)
                
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
                st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 3: BOTTLENECKS & HEALTH
# ==========================================
with tab_ops:
    st.markdown('<br>', unsafe_allow_html=True)
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

# ==========================================
# TAB 4: ACTION CENTER & MATRIX
# ==========================================
with tab_action:
    st.markdown('<br>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("⚠️ Executive Intervention Required")
    st.markdown('<div class="chart-desc">Auto-filtered list of personnel who are in Critical/Watch status, have open blockers, or are flagging for consecutive absences.</div>', unsafe_allow_html=True)

    risk_df = current_df[
        current_df["status"].isin(["Critical", "Watch"])
        | (current_df["blocked_tasks"] > 0)
        | (current_df["attendance_risk_streak"] >= 2)
    ].copy()

    if risk_df.empty:
        st.success("No current personnel risks detected under the selected filters. Operations are nominal.")
    else:
        risk_df["flags_text"] = risk_df["flags"].apply(flags_to_text)
        risk_df = risk_df.sort_values(["status", "performance_pct"], ascending=[False, True])
        
        st.dataframe(
            risk_df[[
                "division", "member_name", "role", "performance_pct", "status", "blocked_tasks",
                "attendance_risk_streak", "communication_score", "flags_text", "notes"
            ]],
            use_container_width=True, hide_index=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("▦ Complete Data Matrix")
    st.markdown('<div class="chart-desc">The unfiltered, raw JSON outputs flattened into a tabular matrix for external export or auditing.</div>', unsafe_allow_html=True)

    raw_view = filtered.copy()
    raw_view["flags"] = raw_view["flags"].apply(flags_to_text)
    raw_view = raw_view.sort_values(["week_start", "division", "member_name"], ascending=[False, True, True])

    st.dataframe(raw_view, use_container_width=True, hide_index=True)

    st.download_button(
        "⬇ Export Matrix to CSV",
        data=raw_view.to_csv(index=False).encode("utf-8"),
        file_name=f"av_admin_export_{date.today().isoformat()}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)
