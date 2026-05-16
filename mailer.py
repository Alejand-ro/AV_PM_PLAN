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

<body style="margin:0; padding:0; background:#070b12; font-family:Segoe UI, Arial, sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" style="background:#070b12; padding:34px 14px;">
    <tr>
      <td align="center">

        <table width="100%" cellpadding="0" cellspacing="0"
          style="max-width:680px; background:#172235; border:1px solid #314159; border-radius:28px; overflow:hidden; box-shadow:0 24px 70px rgba(0,0,0,.55);">

          <tr>
            <td style="padding:38px 34px 28px 34px; background:linear-gradient(145deg,#1b2940,#121b2b);">

              <p style="margin:0 0 18px 0; color:#60a5fa; font-size:13px; font-weight:800; letter-spacing:7px; text-transform:uppercase;">
                PROJECT AV • MARS MISSION MODE
              </p>

              <table cellpadding="0" cellspacing="0">
                <tr>
                  <td style="font-size:58px; line-height:56px; font-weight:900; letter-spacing:-5px; padding-right:16px;">
                    <span style="color:#ef4444; text-shadow:5px 5px 0 #991b1b;">A</span><span style="color:#3b82f6; text-shadow:5px 5px 0 #1e3a8a;">V</span>
                  </td>
                  <td>
                    <h1 style="margin:0; color:#ffffff; font-size:34px; line-height:1.06; font-weight:900;">
                      Mission<br>Task Update
                    </h1>
                  </td>
                </tr>
              </table>

              <p style="margin:26px 0 0 0; color:#cbd5e1; font-size:17px; line-height:1.7;">
                Automated Project AV operations notice generated from the PM planner system.
              </p>

            </td>
          </tr>

          <tr>
            <td style="padding:34px;">
              {message_body}

              <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:34px;">
                <tr>
                  <td align="center">
                    <a href="{APP_URL}"
                      style="display:inline-block; background:#ef4444; color:#ffffff; text-decoration:none; padding:16px 30px; border-radius:16px; font-size:15px; font-weight:900; letter-spacing:.8px; text-transform:uppercase; box-shadow:0 12px 30px rgba(239,68,68,.35);">
                      Open PM Dashboard
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:22px 34px; background:#0f172a; border-top:1px solid #334155;">
              <p style="margin:0; color:#64748b; text-align:center; font-size:12px; line-height:1.7; letter-spacing:1px; text-transform:uppercase;">
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


def build_task_email(task, due_date_str, time_label):
    task_title = esc(task.get("title", "Unknown"))
    priority = esc(task.get("priority", "None"))
    status = esc(task.get("status", ""))
    assigned_to = esc(task.get("assigned_to", ""))

    priority_raw = priority.lower()

    prio_color = "#3b82f6"
    prio_label = "Standard"

    if "critical" in priority_raw or "high" in priority_raw:
        prio_color = "#ef4444"
        prio_label = "High Priority"
    elif "medium" in priority_raw:
        prio_color = "#f59e0b"
        prio_label = "Medium Priority"

    is_late = "late" in time_label.lower()

    date_color = "#ef4444" if is_late else "#22c55e"
    date_label = "Overdue" if is_late else "Upcoming"

    return f"""
      <p style="margin:0 0 10px 0; color:#93c5fd; font-size:13px; font-weight:800; letter-spacing:2px; text-transform:uppercase;">
        Hello Team,
      </p>

      <p style="margin:0 0 28px 0; color:#e2e8f0; font-size:17px; line-height:1.7;">
        A planner item requires attention. Please review the task below and update the dashboard when progress changes.
      </p>

      <table width="100%" cellpadding="0" cellspacing="0"
        style="background:#0b1220; border:1px solid #334155; border-radius:24px; overflow:hidden;">

        <tr>
          <td style="padding:26px; border-left:6px solid {prio_color}; background:#111c2e;">

            <p style="margin:0 0 8px 0; color:#64748b; font-size:12px; font-weight:800; letter-spacing:2px; text-transform:uppercase;">
              Target Objective
            </p>

            <h2 style="margin:0; color:#ffffff; font-size:25px; line-height:1.2; font-weight:900;">
              {task_title}
            </h2>

          </td>
        </tr>

        <tr>
          <td style="padding:24px;">

            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>

                <td width="50%" style="padding-right:8px;">
                  <table width="100%" cellpadding="0" cellspacing="0"
                    style="background:#101827; border:1px solid #334155; border-radius:18px;">
                    <tr>
                      <td style="padding:20px; text-align:center;">
                        <p style="margin:0 0 8px 0; color:#94a3b8; font-size:12px; font-weight:800; letter-spacing:1.5px; text-transform:uppercase;">
                          Timeline
                        </p>
                        <p style="margin:0; color:{date_color}; font-size:22px; font-weight:900;">
                          {esc(due_date_str)}
                        </p>
                        <p style="margin:8px 0 0 0; color:#e2e8f0; font-size:13px; font-weight:700;">
                          {esc(date_label)} • Due {esc(time_label)}
                        </p>
                      </td>
                    </tr>
                  </table>
                </td>

                <td width="50%" style="padding-left:8px;">
                  <table width="100%" cellpadding="0" cellspacing="0"
                    style="background:#101827; border:1px solid #334155; border-radius:18px;">
                    <tr>
                      <td style="padding:20px; text-align:center;">
                        <p style="margin:0 0 8px 0; color:#94a3b8; font-size:12px; font-weight:800; letter-spacing:1.5px; text-transform:uppercase;">
                          Priority
                        </p>
                        <p style="margin:0; color:{prio_color}; font-size:22px; font-weight:900; text-transform:uppercase;">
                          {priority}
                        </p>
                        <p style="margin:8px 0 0 0; color:#e2e8f0; font-size:13px; font-weight:700;">
                          {prio_label}
                        </p>
                      </td>
                    </tr>
                  </table>
                </td>

              </tr>
            </table>

            <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;">
              <tr>
                <td style="background:#101827; border:1px solid #334155; border-radius:18px; padding:18px;">
                  <p style="margin:0; color:#94a3b8; font-size:13px; line-height:1.7;">
                    <strong style="color:#ffffff;">Assigned to:</strong> {assigned_to}<br>
                    <strong style="color:#ffffff;">Current status:</strong> {status}
                  </p>
                </td>
              </tr>
            </table>

          </td>
        </tr>

      </table>
    """


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
