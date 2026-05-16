import os
import sys
import json
import uuid
import html
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import gspread
import pandas as pd
from google.oauth2 import service_account


# --- SECRETS SETUP ---
GCP_JSON = os.environ.get("GCP_SERVICE_ACCOUNT")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
SHEET_NAME = os.environ.get("SHEET_NAME", "AV PM Reports Database")

APP_URL = "https://project-av-pm-weekly.streamlit.app"


def esc(value):
    return html.escape(str(value if value is not None else ""))


def get_sheet_client():
    if not GCP_JSON:
        print("CRITICAL ERROR: GCP_SERVICE_ACCOUNT secret is missing or empty!")
        sys.exit(1)

    try:
        creds_dict = json.loads(GCP_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        return gspread.authorize(creds)

    except Exception as e:
        print(f"CRITICAL ERROR loading Google Credentials: {e}")
        sys.exit(1)


def render_email_wrapper(message_body):
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>

<body style="margin:0; padding:0; background:#05070d; font-family:Segoe UI, Arial, Helvetica, sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
    style="background:#05070d; padding:34px 14px;">
    <tr>
      <td align="center">

        <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
          style="max-width:720px; border-radius:30px; overflow:hidden; background:#101827; border:1px solid #2b3a55; box-shadow:0 28px 90px rgba(0,0,0,.65);">

          <tr>
            <td style="padding:0; background:#111827;">

              <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
                style="background:linear-gradient(145deg,#172235 0%,#0b1220 55%,#020617 100%);">
                <tr>
                  <td style="padding:40px 38px 30px 38px;">

                    <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                      <tr>
                        <td style="vertical-align:top;">

                          <p style="margin:0 0 22px 0; color:#93c5fd; font-size:12px; font-weight:900; letter-spacing:7px; text-transform:uppercase;">
                            PROJECT AV • OPERATIONS SYSTEM
                          </p>

                          <table cellpadding="0" cellspacing="0" role="presentation">
                            <tr>
                              <td style="font-family:Arial Black, Arial, Helvetica, sans-serif; font-size:76px; line-height:68px; font-weight:900; letter-spacing:-16px; font-style:italic; padding-right:22px; vertical-align:middle;">
                                <span style="color:#ef4444; text-shadow:6px 6px 0 #7f1d1d, 10px 10px 22px rgba(239,68,68,.25);">A</span><span style="color:#3b82f6; text-shadow:6px 6px 0 #1e3a8a, 10px 10px 22px rgba(59,130,246,.25);">V</span>
                              </td>
                              <td style="vertical-align:middle;">
                                <h1 style="margin:0; color:#ffffff; font-size:38px; line-height:1.03; font-weight:950; letter-spacing:-1.5px;">
                                  Mission<br>Task Update
                                </h1>
                              </td>
                            </tr>
                          </table>

                          <p style="margin:28px 0 0 0; color:#cbd5e1; font-size:16px; line-height:1.75;">
                            Automated Project AV planner notice generated from the PM operations dashboard.
                          </p>

                        </td>
                      </tr>
                    </table>

                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <tr>
            <td style="padding:34px; background:linear-gradient(180deg,#0b1220 0%,#070b12 100%);">
              {message_body}

              <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-top:34px;">
                <tr>
                  <td align="center">
                    <a href="{APP_URL}"
                      style="display:inline-block; background:#ef4444; color:#ffffff; text-decoration:none; padding:17px 34px; border-radius:16px; font-size:14px; font-weight:950; letter-spacing:1px; text-transform:uppercase; box-shadow:0 14px 34px rgba(239,68,68,.38); border:1px solid rgba(255,255,255,.14);">
                      Open PM Dashboard
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:24px 34px; background:#020617; border-top:1px solid #243044;">
              <p style="margin:0; color:#64748b; text-align:center; font-size:11px; line-height:1.75; letter-spacing:1.3px; text-transform:uppercase;">
                Automated System Message<br>
                Project AV Operations Database • Please do not reply
              </p>
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>
"""


def metadata_row(label, value):
    value = str(value or "").strip()
    if not value:
        return ""

    return f"""
      <tr>
        <td style="padding:9px 0; color:#94a3b8; font-size:12px; font-weight:900; letter-spacing:1.5px; text-transform:uppercase; width:155px; vertical-align:top;">
          {esc(label)}
        </td>
        <td style="padding:9px 0; color:#e2e8f0; font-size:14px; line-height:1.55; font-weight:650; vertical-align:top;">
          {esc(value)}
        </td>
      </tr>
    """


def badge(label, color="#3b82f6"):
    label = str(label or "").strip()
    if not label:
        return ""

    return f"""
      <span style="display:inline-block; margin:0 6px 8px 0; padding:8px 11px; border-radius:999px; background:{color}; color:#ffffff; font-size:11px; font-weight:900; letter-spacing:.8px; text-transform:uppercase; box-shadow:0 8px 18px rgba(0,0,0,.24);">
        {esc(label)}
      </span>
    """


def build_task_email(task, due_date_str, time_label):
    task_title = esc(task.get("title", "Unknown"))
    priority = esc(task.get("priority", "None"))
    status = esc(task.get("status", ""))
    assigned_to = esc(task.get("assigned_to", ""))
    cc_people = esc(task.get("cc_people", ""))

    mission = task.get("mission", "")
    cycle = task.get("cycle", "")
    division = task.get("division", "")
    subassembly = task.get("subassembly", "")
    linked_gantt_task = task.get("linked_gantt_task", "")
    linked_gantt_phase = task.get("linked_gantt_phase", "")
    description = task.get("description", "")
    deliverable_link = str(task.get("deliverable_link", "") or "").strip()
    due_date_raw = task.get("due_date", due_date_str)

    priority_raw = str(priority).lower()
    status_raw = str(status).lower()
    time_raw = str(time_label).lower()

    prio_color = "#3b82f6"
    prio_bg = "rgba(59,130,246,.14)"
    prio_label = "Standard Priority"

    if "critical" in priority_raw:
        prio_color = "#ef4444"
        prio_bg = "rgba(239,68,68,.16)"
        prio_label = "Critical Priority"
    elif "high" in priority_raw:
        prio_color = "#f97316"
        prio_bg = "rgba(249,115,22,.16)"
        prio_label = "High Priority"
    elif "medium" in priority_raw:
        prio_color = "#f59e0b"
        prio_bg = "rgba(245,158,11,.16)"
        prio_label = "Medium Priority"
    elif "low" in priority_raw:
        prio_color = "#64748b"
        prio_bg = "rgba(100,116,139,.16)"
        prio_label = "Low Priority"

    status_color = "#64748b"
    status_label = status or "Unspecified"

    if "completed" in status_raw:
        status_color = "#22c55e"
    elif "progress" in status_raw:
        status_color = "#3b82f6"
    elif "review" in status_raw:
        status_color = "#a855f7"
    elif "blocked" in status_raw:
        status_color = "#ef4444"
    elif "cancelled" in status_raw:
        status_color = "#64748b"
    elif "not started" in status_raw:
        status_color = "#94a3b8"

    is_late = "late" in time_raw or "overdue" in time_raw
    is_today = "today" in time_raw
    is_tomorrow = "tomorrow" in time_raw

    date_color = "#22c55e"
    date_bg = "rgba(34,197,94,.14)"
    date_label = "Upcoming"

    if is_late:
        date_color = "#ef4444"
        date_bg = "rgba(239,68,68,.16)"
        date_label = "Overdue"
    elif is_today:
        date_color = "#f59e0b"
        date_bg = "rgba(245,158,11,.16)"
        date_label = "Due Today"
    elif is_tomorrow:
        date_color = "#38bdf8"
        date_bg = "rgba(56,189,248,.16)"
        date_label = "Due Tomorrow"

    mission_badges = ""
    if mission:
        mission_badges += badge(mission, "#ef4444" if str(mission).lower() == "mars" else "#3b82f6")
    if cycle:
        mission_badges += badge(cycle, "#475569")
    if division:
        mission_badges += badge(division, "#334155")
    if linked_gantt_phase:
        mission_badges += badge(linked_gantt_phase, "#6366f1")
    if subassembly:
        mission_badges += badge(subassembly, "#0f766e")

    metadata_html = ""
    metadata_html += metadata_row("Assigned To", assigned_to)
    metadata_html += metadata_row("CC / Followers", cc_people)
    metadata_html += metadata_row("Status", status)
    metadata_html += metadata_row("Priority", priority)
    metadata_html += metadata_row("Mission", mission)
    metadata_html += metadata_row("Cycle", cycle)
    metadata_html += metadata_row("Division", division)
    metadata_html += metadata_row("Subassembly", subassembly)
    metadata_html += metadata_row("Gantt Task", linked_gantt_task)
    metadata_html += metadata_row("Gantt Phase", linked_gantt_phase)
    metadata_html += metadata_row("Due Date", due_date_raw)

    description_html = ""
    if str(description or "").strip():
        description_html = f"""
          <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-top:18px;">
            <tr>
              <td style="background:#0b1220; border:1px solid #273449; border-radius:18px; padding:19px;">
                <p style="margin:0 0 8px 0; color:#93c5fd; font-size:12px; font-weight:900; letter-spacing:1.6px; text-transform:uppercase;">
                  Task Brief
                </p>
                <p style="margin:0; color:#dbeafe; font-size:14px; line-height:1.7;">
                  {esc(description)}
                </p>
              </td>
            </tr>
          </table>
        """

    deliverable_html = ""
    if deliverable_link:
        safe_link = esc(deliverable_link)
        deliverable_html = f"""
          <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-top:18px;">
            <tr>
              <td style="background:#0f172a; border:1px solid #334155; border-radius:18px; padding:18px;">
                <p style="margin:0 0 12px 0; color:#94a3b8; font-size:12px; font-weight:900; letter-spacing:1.5px; text-transform:uppercase;">
                  Deliverable Link
                </p>
                <a href="{safe_link}" style="color:#60a5fa; font-size:14px; line-height:1.6; font-weight:800; text-decoration:none;">
                  {safe_link}
                </a>
              </td>
            </tr>
          </table>
        """

    return f"""
      <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
        <tr>
          <td>

            <p style="margin:0 0 10px 0; color:#93c5fd; font-size:12px; font-weight:900; letter-spacing:2px; text-transform:uppercase;">
              Hello Team,
            </p>

            <p style="margin:0 0 28px 0; color:#cbd5e1; font-size:16px; line-height:1.75;">
              A planner item requires attention. Review the task details below and update the PM dashboard when progress changes.
            </p>

            <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
              style="background:linear-gradient(145deg,#111c2e 0%,#0b1220 70%); border:1px solid #334155; border-radius:26px; overflow:hidden; box-shadow:0 18px 45px rgba(0,0,0,.36);">

              <tr>
                <td style="padding:26px 26px 22px 26px; border-left:7px solid {prio_color}; background:linear-gradient(135deg,#18243a 0%,#101827 100%);">

                  <p style="margin:0 0 12px 0; color:#94a3b8; font-size:12px; font-weight:900; letter-spacing:2.2px; text-transform:uppercase;">
                    Task Objective
                  </p>

                  <table cellpadding="0" cellspacing="0" role="presentation" width="100%">
                    <tr>
                      <td style="background:{prio_bg}; border:1px solid {prio_color}; border-radius:18px; padding:18px 20px; box-shadow:0 14px 30px rgba(0,0,0,.24);">
                        <h2 style="margin:0; color:#ffffff; font-size:27px; line-height:1.22; font-weight:950; letter-spacing:-.5px;">
                          {task_title}
                        </h2>
                      </td>
                    </tr>
                  </table>

                  <div style="margin-top:16px;">
                    {mission_badges}
                  </div>

                </td>
              </tr>

              <tr>
                <td style="padding:24px;">

                  <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                    <tr>

                      <td width="50%" style="padding-right:8px; vertical-align:top;">
                        <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
                          style="background:{date_bg}; border:1px solid {date_color}; border-radius:20px;">
                          <tr>
                            <td style="padding:22px; text-align:center;">
                              <p style="margin:0 0 9px 0; color:#cbd5e1; font-size:12px; font-weight:900; letter-spacing:1.7px; text-transform:uppercase;">
                                Deadline
                              </p>
                              <p style="margin:0; color:{date_color}; font-size:25px; line-height:1.1; font-weight:950;">
                                {esc(due_date_str)}
                              </p>
                              <p style="margin:11px 0 0 0;">
                                <span style="display:inline-block; background:{date_color}; color:#020617; padding:7px 11px; border-radius:999px; font-size:11px; font-weight:950; letter-spacing:.8px; text-transform:uppercase;">
                                  {esc(date_label)} • {esc(time_label)}
                                </span>
                              </p>
                            </td>
                          </tr>
                        </table>
                      </td>

                      <td width="50%" style="padding-left:8px; vertical-align:top;">
                        <table width="100%" cellpadding="0" cellspacing="0" role="presentation"
                          style="background:{prio_bg}; border:1px solid {prio_color}; border-radius:20px;">
                          <tr>
                            <td style="padding:22px; text-align:center;">
                              <p style="margin:0 0 9px 0; color:#cbd5e1; font-size:12px; font-weight:900; letter-spacing:1.7px; text-transform:uppercase;">
                                Priority
                              </p>
                              <p style="margin:0; color:{prio_color}; font-size:25px; line-height:1.1; font-weight:950; text-transform:uppercase;">
                                {priority}
                              </p>
                              <p style="margin:11px 0 0 0; color:#e2e8f0; font-size:13px; font-weight:750;">
                                {esc(prio_label)}
                              </p>
                            </td>
                          </tr>
                        </table>
                      </td>

                    </tr>
                  </table>

                  <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-top:16px;">
                    <tr>
                      <td style="background:#101827; border:1px solid #334155; border-radius:20px; padding:20px;">

                        <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                          <tr>
                            <td width="50%" style="padding-right:8px; vertical-align:top;">
                              <p style="margin:0 0 8px 0; color:#94a3b8; font-size:12px; font-weight:900; letter-spacing:1.5px; text-transform:uppercase;">
                                Current Status
                              </p>
                              <p style="margin:0; color:{status_color}; font-size:20px; font-weight:950;">
                                {esc(status_label)}
                              </p>
                            </td>
                            <td width="50%" style="padding-left:8px; vertical-align:top;">
                              <p style="margin:0 0 8px 0; color:#94a3b8; font-size:12px; font-weight:900; letter-spacing:1.5px; text-transform:uppercase;">
                                Assigned To
                              </p>
                              <p style="margin:0; color:#ffffff; font-size:18px; font-weight:850; line-height:1.35;">
                                {assigned_to if assigned_to else "Unassigned"}
                              </p>
                            </td>
                          </tr>
                        </table>

                      </td>
                    </tr>
                  </table>

                  <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin-top:18px;">
                    <tr>
                      <td style="background:#0b1220; border:1px solid #273449; border-radius:20px; padding:20px;">
                        <p style="margin:0 0 12px 0; color:#93c5fd; font-size:12px; font-weight:900; letter-spacing:1.8px; text-transform:uppercase;">
                          Mission Context
                        </p>

                        <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
                          {metadata_html}
                        </table>
                      </td>
                    </tr>
                  </table>

                  {description_html}
                  {deliverable_html}

                </td>
              </tr>

            </table>

          </td>
        </tr>
      </table>
    """


def send_email(to_email, cc_emails, subject, message_body):
    if not GMAIL_ADDRESS or not GMAIL_PASSWORD:
        return False, "Gmail Address or App Password secret is missing."

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Project AV Command <{GMAIL_ADDRESS}>"
    msg["To"] = to_email

    if cc_emails:
        msg["Cc"] = cc_emails

    msg["Subject"] = subject

    html_content = render_email_wrapper(message_body)
    msg.attach(MIMEText(html_content, "html"))

    all_recipients = [to_email]
    if cc_emails:
        all_recipients.extend([e.strip() for e in cc_emails.split(",") if e.strip()])

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, all_recipients, msg.as_string())
        server.quit()
        return True, ""

    except Exception as e:
        return False, str(e)


def process_queue():
    print("Starting Project AV Mailer Script...")

    client = get_sheet_client()

    try:
        sh = client.open(SHEET_NAME)
    except Exception as e:
        print(f"CRITICAL ERROR: Could not open sheet '{SHEET_NAME}'. Error: {e}")
        sys.exit(1)

    ws_notif = sh.worksheet("planner_notifications_queue")
    ws_tasks = sh.worksheet("planner_tasks")
    ws_memb = sh.worksheet("planner_members")

    df_notif = pd.DataFrame(ws_notif.get_all_records())
    df_tasks = pd.DataFrame(ws_tasks.get_all_records())
    df_memb = pd.DataFrame(ws_memb.get_all_records())

    if df_notif.empty:
        df_notif = pd.DataFrame(columns=[
            "notification_id", "task_id", "notification_type", "recipient",
            "cc_people", "subject", "message", "status", "created_at",
            "sent_at", "error",
        ])

    today = datetime.utcnow().date()
    today_str = today.strftime("%Y-%m-%d")

    if not df_tasks.empty:
        new_notifications = []

        for _, task in df_tasks.iterrows():
            status = str(task.get("status", ""))

            if status in ["Completed", "Cancelled", "Blocked"]:
                continue

            due_date_str = str(task.get("due_date", "")).strip()

            if not due_date_str:
                continue

            try:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                days_left = (due_date - today).days

                time_label = None

                if days_left == 7:
                    time_label = "in 1 week"
                elif days_left == 1:
                    time_label = "tomorrow"
                elif days_left == 0:
                    time_label = "today"
                elif days_left < 0:
                    time_label = f"late by {abs(days_left)} day(s)"

                if not time_label:
                    continue

                task_id = str(task.get("task_id", ""))

                already_queued = False

                if not df_notif.empty and "task_id" in df_notif.columns:
                    mask = (
                        (df_notif["task_id"].astype(str) == task_id) &
                        (df_notif["created_at"].astype(str).str.startswith(today_str, na=False))
                    )

                    if mask.any():
                        already_queued = True

                if already_queued:
                    continue

                task_title = str(task.get("title", "Unknown"))

                print(f"Auto-queuing reminder for task: {task_title}")

                inner_html = build_task_email(task, due_date_str, time_label)

                new_row = {
                    "notification_id": str(uuid.uuid4()),
                    "task_id": task_id,
                    "notification_type": "Deadline Reminder",
                    "recipient": task.get("assigned_to", ""),
                    "cc_people": task.get("cc_people", ""),
                    "subject": f"Project AV | Mission Task Update: {task_title}",
                    "message": inner_html,
                    "status": "Queued",
                    "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "sent_at": "",
                    "error": "",
                }

                new_notifications.append(new_row)

            except ValueError:
                continue

        if new_notifications:
            df_notif = pd.concat([df_notif, pd.DataFrame(new_notifications)], ignore_index=True)

    if df_notif.empty:
        print("Queue is entirely empty. Exiting.")
        return

    queued_mask = df_notif["status"] == "Queued"
    emails_to_send = df_notif[queued_mask]

    if emails_to_send.empty:
        print("No emails to send right now.")

    else:
        for idx, row in emails_to_send.iterrows():
            recipient_raw = str(row.get("recipient", ""))

            raw_targets = [r.strip() for r in recipient_raw.split(",") if r.strip()]
            resolved_emails = []

            for target in raw_targets:
                if "@" in target:
                    resolved_emails.append(target)

                elif not df_memb.empty:
                    match = df_memb[df_memb["member_name"] == target]

                    if not match.empty:
                        em = str(match.iloc[0].get("email", ""))

                        if "@" in em:
                            resolved_emails.append(em)

            resolved_emails = list(dict.fromkeys(resolved_emails))

            if not resolved_emails:
                df_notif.at[idx, "status"] = "Failed"
                df_notif.at[idx, "error"] = f"No valid email found for: {recipient_raw}"
                print(f"Skipped {recipient_raw} - no email found.")
                continue

            to_email = resolved_emails[0]

            existing_cc = str(row.get("cc_people", ""))
            cc_list = [c.strip() for c in existing_cc.split(",") if c.strip()]

            if len(resolved_emails) > 1:
                cc_list.extend(resolved_emails[1:])

            final_cc = ",".join(list(dict.fromkeys(cc_list)))

            print(f"Sending HTML email to {to_email} CC: {final_cc}")

            success, err_msg = send_email(
                to_email=to_email,
                cc_emails=final_cc,
                subject=row.get("subject", "Project AV Task Update"),
                message_body=row.get("message", ""),
            )

            if success:
                print(f"SUCCESS: Email sent to {to_email}")
                df_notif.at[idx, "status"] = "Sent"
                df_notif.at[idx, "sent_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            else:
                print(f"FAILED: Could not send to {to_email}. Error: {err_msg}")
                df_notif.at[idx, "status"] = "Failed"
                df_notif.at[idx, "error"] = err_msg

    df_notif.fillna("", inplace=True)

    data_to_write = [df_notif.columns.values.tolist()] + df_notif.values.tolist()

    ws_notif.clear()

    try:
        ws_notif.update(data_to_write, "A1")
    except TypeError:
        ws_notif.update("A1", data_to_write)

    print("Run complete. Google Sheets updated.")


if __name__ == "__main__":
    process_queue()
