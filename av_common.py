from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd

APP_NAME = "Project AV Performance OS"
BASE_DIR = Path(__file__).resolve().parent
OUTBOX_DIR = BASE_DIR / "reports_outbox"
INBOX_DIR = BASE_DIR / "reports_inbox"
ARCHIVE_DIR = BASE_DIR / "reports_archive"

for directory in (OUTBOX_DIR, INBOX_DIR, ARCHIVE_DIR):
    directory.mkdir(parents=True, exist_ok=True)

DIVISIONS = [
    "Power and Electrical Systems",
    "Vehicle Design & Structures",
    "Software & Hardware",
    "Astrobiology",
    "Robotic Arm",
]

DIVISION_COLORS = {
    "Power and Electrical Systems": "#FACC15",  # yellow
    "Vehicle Design & Structures": "#3B82F6",  # blue
    "Software & Hardware": "#EF4444",          # red
    "Astrobiology": "#22C55E",                 # green
    "Robotic Arm": "#A855F7",                  # purple
}

DIVISION_ALIASES = {
    "pes": "Power and Electrical Systems",
    "power": "Power and Electrical Systems",
    "power electrical": "Power and Electrical Systems",
    "power and electrical": "Power and Electrical Systems",
    "power and electrical systems": "Power and Electrical Systems",
    "electrical": "Power and Electrical Systems",
    "vehicle design": "Vehicle Design & Structures",
    "vehicle design structures": "Vehicle Design & Structures",
    "vehicle design & structures": "Vehicle Design & Structures",
    "design": "Vehicle Design & Structures",
    "structures": "Vehicle Design & Structures",
    "software": "Software & Hardware",
    "hardware": "Software & Hardware",
    "software hardware": "Software & Hardware",
    "software & hardware": "Software & Hardware",
    "astro": "Astrobiology",
    "astrobiology": "Astrobiology",
    "robotics": "Robotic Arm",
    "robotic arm": "Robotic Arm",
    "robotic-arm": "Robotic Arm",
    "arm": "Robotic Arm",
}

METRIC_WEIGHTS = {
    "completion": 0.30,
    "quality": 0.25,
    "delivery": 0.20,
    "attendance": 0.15,
    "confidence": 0.10,
}

REQUIRED_COLUMNS = [
    "record_id",
    "report_id",
    "created_at",
    "pm_name",
    "division",
    "week_start",
    "iso_year",
    "iso_week",
    "member_name",
    "role",
    "tasks_assigned",
    "tasks_completed",
    "avg_quality_1_to_5",
    "tasks_on_time",
    "tasks_late",
    "blocked_tasks",
    "meetings_required",
    "meetings_attended",
    "pm_confidence_1_to_5",
    "notes",
    "completion_score",
    "quality_score",
    "delivery_score",
    "attendance_score",
    "confidence_score",
    "performance_score",
    "performance_pct",
    "status",
    "flags",
    "source_file",
]

LEGACY_DEMO_CREATED_AT = "2026-05-11T18:00:01"


def today_monday() -> date:
    now = date.today()
    return now - timedelta(days=now.weekday())


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return None


def iso_parts(week_start: date | str | None) -> Tuple[int, int]:
    parsed = parse_date(week_start) or today_monday()
    iso = parsed.isocalendar()
    return int(iso.year), int(iso.week)


def week_label(week_start: Any) -> str:
    parsed = parse_date(week_start)
    if not parsed:
        return "Unknown week"
    y, w = iso_parts(parsed)
    return f"{y}-W{w:02d}"


def safe_number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    return int(round(safe_number(value, default)))


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator is None or denominator == 0:
        return default
    return numerator / denominator


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_division(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return DIVISIONS[0]
    if text in DIVISIONS:
        return text
    key = " ".join(text.replace("&", " ").replace("/", " ").replace("-", " ").lower().split())
    return DIVISION_ALIASES.get(key, text)


def division_color(division: Any) -> str:
    return DIVISION_COLORS.get(normalize_division(division), "#64748B")


def metric_weights_text() -> str:
    return " · ".join(f"{name.title()} {int(weight * 100)}%" for name, weight in METRIC_WEIGHTS.items())


def empty_input_rows(count: int = 6) -> List[Dict[str, Any]]:
    return [
        {
            "member_name": "",
            "role": "",
            "tasks_assigned": 0,
            "tasks_completed": 0,
            "avg_quality_1_to_5": 0.0,
            "tasks_on_time": 0,
            "tasks_late": 0,
            "blocked_tasks": 0,
            "meetings_required": 0,
            "meetings_attended": 0,
            "pm_confidence_1_to_5": 3.0,
            "notes": "",
        }
        for _ in range(count)
    ]


def normalize_member_row(raw: Dict[str, Any], pm_name: str, division: str, week_start: date, report_id: str, index: int, created_at: str) -> Dict[str, Any]:
    member_name = clean_text(raw.get("member_name") or raw.get("Nombre") or raw.get("Member") or raw.get("Miembro"))
    role = clean_text(raw.get("role") or raw.get("Role") or "Member")
    division = normalize_division(division)

    tasks_assigned = max(0, safe_int(raw.get("tasks_assigned")))
    tasks_completed = max(0, safe_int(raw.get("tasks_completed")))
    tasks_completed = min(tasks_completed, tasks_assigned) if tasks_assigned > 0 else 0

    avg_quality = clamp(safe_number(raw.get("avg_quality_1_to_5"), 0.0), 0.0, 5.0)
    tasks_on_time = max(0, safe_int(raw.get("tasks_on_time")))
    tasks_on_time = min(tasks_on_time, tasks_completed)
    tasks_late = max(0, safe_int(raw.get("tasks_late")))
    tasks_late = min(tasks_late, max(0, tasks_completed - tasks_on_time))
    blocked_tasks = max(0, safe_int(raw.get("blocked_tasks")))

    meetings_required = max(0, safe_int(raw.get("meetings_required")))
    meetings_attended = max(0, safe_int(raw.get("meetings_attended")))
    meetings_attended = min(meetings_attended, meetings_required) if meetings_required > 0 else 0

    pm_confidence = clamp(safe_number(raw.get("pm_confidence_1_to_5"), 3.0), 1.0, 5.0)
    notes = clean_text(raw.get("notes") or raw.get("Notas") or "")

    completion_score = clamp(safe_div(tasks_completed, tasks_assigned, 0.0)) if tasks_assigned > 0 else 0.0
    quality_score = clamp(avg_quality / 5.0) if tasks_completed > 0 else 0.0
    delivery_score = clamp(safe_div(tasks_on_time, tasks_completed, 0.0)) if tasks_completed > 0 else 0.0
    attendance_score = clamp(safe_div(meetings_attended, meetings_required, 1.0)) if meetings_required > 0 else 1.0
    confidence_score = clamp(pm_confidence / 5.0)

    performance = clamp(
        METRIC_WEIGHTS["completion"] * completion_score
        + METRIC_WEIGHTS["quality"] * quality_score
        + METRIC_WEIGHTS["delivery"] * delivery_score
        + METRIC_WEIGHTS["attendance"] * attendance_score
        + METRIC_WEIGHTS["confidence"] * confidence_score
    )

    flags = build_flags(
        member_name=member_name,
        tasks_assigned=tasks_assigned,
        tasks_completed=tasks_completed,
        completion_score=completion_score,
        quality_score=quality_score,
        delivery_score=delivery_score,
        attendance_score=attendance_score,
        blocked_tasks=blocked_tasks,
        meetings_required=meetings_required,
    )
    status = status_from_score(performance, flags)
    iso_year, iso_week = iso_parts(week_start)

    fingerprint = hashlib.sha1(f"{report_id}|{division}|{week_start}|{member_name}|{index}".encode("utf-8")).hexdigest()[:16]
    return {
        "record_id": f"rec_{fingerprint}",
        "report_id": report_id,
        "created_at": created_at,
        "pm_name": clean_text(pm_name),
        "division": division,
        "week_start": week_start.isoformat(),
        "iso_year": iso_year,
        "iso_week": iso_week,
        "member_name": member_name,
        "role": role,
        "tasks_assigned": tasks_assigned,
        "tasks_completed": tasks_completed,
        "avg_quality_1_to_5": round(avg_quality, 2),
        "tasks_on_time": tasks_on_time,
        "tasks_late": tasks_late,
        "blocked_tasks": blocked_tasks,
        "meetings_required": meetings_required,
        "meetings_attended": meetings_attended,
        "pm_confidence_1_to_5": round(pm_confidence, 2),
        "notes": notes,
        "completion_score": round(completion_score, 4),
        "quality_score": round(quality_score, 4),
        "delivery_score": round(delivery_score, 4),
        "attendance_score": round(attendance_score, 4),
        "confidence_score": round(confidence_score, 4),
        "performance_score": round(performance, 4),
        "performance_pct": round(performance * 100, 1),
        "status": status,
        "flags": flags,
        "source_file": "",
    }


def build_flags(
    member_name: str,
    tasks_assigned: int,
    tasks_completed: int,
    completion_score: float,
    quality_score: float,
    delivery_score: float,
    attendance_score: float,
    blocked_tasks: int,
    meetings_required: int,
) -> List[str]:
    flags: List[str] = []
    if not member_name:
        flags.append("missing_member_name")
    if tasks_assigned == 0:
        flags.append("no_tasks_assigned")
    if tasks_assigned > 0 and completion_score < 0.50:
        flags.append("completion_red")
    elif tasks_assigned > 0 and completion_score < 0.75:
        flags.append("completion_yellow")

    if tasks_completed > 0 and quality_score < 0.60:
        flags.append("quality_red")
    elif tasks_completed > 0 and quality_score < 0.75:
        flags.append("quality_yellow")

    if tasks_completed > 0 and delivery_score < 0.60:
        flags.append("delivery_red")
    elif tasks_completed > 0 and delivery_score < 0.80:
        flags.append("delivery_yellow")

    if meetings_required > 0 and attendance_score < 0.50:
        flags.append("attendance_red")
    elif meetings_required > 0 and attendance_score < 0.75:
        flags.append("attendance_yellow")

    if blocked_tasks > 0:
        flags.append("blockers_open")
    return flags


def status_from_score(score: float, flags: Iterable[str]) -> str:
    flags_set = set(flags)
    red = any(flag.endswith("_red") for flag in flags_set)
    if score >= 0.85 and not red:
        return "Excellent"
    if score >= 0.70:
        return "Healthy"
    if score >= 0.55:
        return "Watch"
    return "Critical"


def make_report(pm_name: str, division: str, week_start: date, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    division = normalize_division(division)
    report_id = f"rpt_{uuid.uuid4().hex[:12]}"
    created_at = datetime.now().isoformat(timespec="seconds")
    records = [
        normalize_member_row(row, pm_name, division, week_start, report_id, index, created_at)
        for index, row in enumerate(rows, start=1)
        if clean_text(row.get("member_name"))
    ]
    return {
        "schema_version": "1.1",
        "app": APP_NAME,
        "report_id": report_id,
        "created_at": created_at,
        "pm_name": clean_text(pm_name),
        "division": division,
        "week_start": week_start.isoformat(),
        "iso_year": iso_parts(week_start)[0],
        "iso_week": iso_parts(week_start)[1],
        "records": records,
    }


def save_report(report: Dict[str, Any], target_dir: Path = OUTBOX_DIR) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    division = clean_filename(report.get("division", "division"))
    week = week_label(report.get("week_start", "week"))
    report_id = clean_filename(report.get("report_id", uuid.uuid4().hex[:8]))
    path = target_dir / f"{week}_{division}_{report_id}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def clean_filename(value: Any) -> str:
    text = clean_text(value) or "unknown"
    allowed = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            allowed.append(ch)
        elif ch.isspace() or ch in ("&", "/"):
            allowed.append("_")
    return "".join(allowed)[:80] or "unknown"


def empty_dataframe() -> pd.DataFrame:
    df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    df["week_start_dt"] = pd.to_datetime(pd.Series([], dtype="object"))
    df["attendance_risk_streak"] = pd.Series([], dtype="int64")
    return df


def is_legacy_bundled_demo(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    pm_name = clean_text(payload.get("pm_name"))
    created_at = clean_text(payload.get("created_at"))
    app_name = clean_text(payload.get("app"))
    return bool(
        app_name == APP_NAME
        and created_at == LEGACY_DEMO_CREATED_AT
        and pm_name.startswith("PM ")
        and normalize_division(payload.get("division")) in DIVISIONS
    )


def load_reports(paths: Iterable[Path] | None = None, include_legacy_demo: bool = False) -> Tuple[pd.DataFrame, List[str]]:
    search_dirs = list(paths) if paths is not None else [INBOX_DIR, OUTBOX_DIR]
    records: List[Dict[str, Any]] = []
    warnings: List[str] = []
    skipped_demo = 0

    for directory in search_dirs:
        directory = Path(directory)
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                warnings.append(f"{path.name}: invalid JSON ({exc})")
                continue

            if not include_legacy_demo and is_legacy_bundled_demo(payload):
                skipped_demo += 1
                continue

            if isinstance(payload, dict) and "records" in payload:
                for row in payload.get("records", []):
                    if isinstance(row, dict):
                        copied = dict(row)
                        copied["source_file"] = str(path)
                        copied["division"] = normalize_division(copied.get("division") or payload.get("division"))
                        records.append(copied)
            elif isinstance(payload, list):
                for row in payload:
                    if isinstance(row, dict):
                        copied = dict(row)
                        copied["source_file"] = str(path)
                        copied["division"] = normalize_division(copied.get("division"))
                        records.append(copied)
            else:
                warnings.append(f"{path.name}: schema not recognized")

    if skipped_demo:
        warnings.append(f"Skipped {skipped_demo} bundled demo report(s). Turn on 'Show legacy demo data' only if you intentionally want fake data.")

    if not records:
        return empty_dataframe(), warnings

    df = pd.DataFrame(records)
    for column in REQUIRED_COLUMNS:
        if column not in df.columns:
            df[column] = "" if column in {"record_id", "report_id", "created_at", "pm_name", "division", "week_start", "member_name", "role", "notes", "status", "source_file"} else 0

    if "flags" in df.columns:
        df["flags"] = df["flags"].apply(lambda x: x if isinstance(x, list) else ([] if pd.isna(x) or x == "" else [str(x)]))

    text_cols = ["record_id", "report_id", "created_at", "pm_name", "division", "week_start", "member_name", "role", "notes", "status", "source_file"]
    for col in text_cols:
        df[col] = df[col].fillna("").astype(str)
    df["division"] = df["division"].apply(normalize_division)

    for col in [
        "iso_year", "iso_week", "tasks_assigned", "tasks_completed", "tasks_on_time", "tasks_late",
        "blocked_tasks", "meetings_required", "meetings_attended",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    for col in [
        "avg_quality_1_to_5", "pm_confidence_1_to_5", "completion_score", "quality_score",
        "delivery_score", "attendance_score", "confidence_score", "performance_score", "performance_pct",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)

    # Safety clamp in case an older report had an impossible score.
    for col in ["completion_score", "quality_score", "delivery_score", "attendance_score", "confidence_score", "performance_score"]:
        df[col] = df[col].clip(lower=0.0, upper=1.0)
    df["performance_pct"] = df["performance_pct"].clip(lower=0.0, upper=100.0)

    df["week_start_dt"] = pd.to_datetime(df["week_start"], errors="coerce")
    df = df.drop_duplicates(subset=["record_id"], keep="last")
    df = df[REQUIRED_COLUMNS + ["week_start_dt"]]
    return df, warnings


def annotate_attendance_streaks(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        result = df.copy()
        result["attendance_risk_streak"] = pd.Series([], dtype="int64")
        return result
    result = df.copy()
    result["attendance_risk_streak"] = 0
    result = result.sort_values(["division", "member_name", "week_start_dt"])
    for _, idxs in result.groupby(["division", "member_name"], dropna=False).groups.items():
        streak = 0
        for idx in idxs:
            low = bool(result.at[idx, "meetings_required"] > 0 and result.at[idx, "attendance_score"] < 0.75)
            streak = streak + 1 if low else 0
            result.at[idx, "attendance_risk_streak"] = streak
    return result


def flags_to_text(flags: Any) -> str:
    if isinstance(flags, list):
        return ", ".join(flags)
    if flags is None:
        return ""
    return str(flags)


def sample_input_rows() -> List[Dict[str, Any]]:
    # Kept only for manual testing by developers. The production reporter does not call this.
    return [
        {
            "member_name": "Member A",
            "role": "Mechanical",
            "tasks_assigned": 4,
            "tasks_completed": 3,
            "avg_quality_1_to_5": 4.2,
            "tasks_on_time": 3,
            "tasks_late": 0,
            "blocked_tasks": 1,
            "meetings_required": 2,
            "meetings_attended": 2,
            "pm_confidence_1_to_5": 4,
            "notes": "Testing row only. Do not use as real data.",
        }
    ]
