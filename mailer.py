import os
import sys
import json
import uuid
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

def get_sheet_client():
    if not GCP_JSON:
        print("CRITICAL ERROR: GCP_SERVICE_ACCOUNT secret is missing or empty!")
        sys.exit(1)
    try:
        creds_dict = json.loads(GCP_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        return gspread.authorize(creds)
    except Exception as e:
        print(f"CRITICAL ERROR loading Google Credentials: {e}")
        sys.exit(1)

def send_email(to_email, cc_emails, subject, message_body):
    if not GMAIL_ADDRESS or not GMAIL_PASSWORD:
        return False, "Gmail Address or App Password secret is missing."
        
    # RESTORED: Using your exact original Multipart logic
    msg = MIMEMultipart()
    msg['From'] = f"Project AV Command <{GMAIL_ADDRESS}>"
    msg['To'] = to_email
    if cc_emails:
        msg['Cc'] = cc_emails
    msg['Subject'] = subject

    # RESTORED: Building the HTML wrapper directly inside the send function
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; background-color: #020617; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #020617; padding: 40px 20px;">
        <tr>
          <td align="center">
            <table width="100%" max-width="600" cellpadding="0" cellspacing="0" style="max-width: 600px; background-color: #0f172a; border-radius: 12px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #1e293b;">
              
              <tr>
                <td style="background: linear-gradient(90deg, #1d4ed8 0%, #3b82f6 100%); padding: 25px; text-align: center;">
                  <h1 style="color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 2px; text-transform: uppercase;">Project AV Command</h1>
                </td>
              </tr>
              
              <tr>
                <td style="padding: 35px 30px;">
                  {message_body}
                  
                  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top: 25px;">
                    <tr>
                      <td align="center" style="padding: 20px 0;">
                        <a href="https://project-av-pm-weekly.streamlit.app" style="background-color: #3b82f6; color: #ffffff; padding: 14px 30px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 16px; display: inline-block; text-transform: uppercase; letter-spacing: 1px;">Access Dashboard</a>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
              
              <tr>
                <td style="background-color: #0b1120; padding: 20px; text-align: center; border-top: 1px solid #1e293b;">
                  <p style="color: #64748b; font-size: 12px; margin: 0; line-height: 1.5;">
                    ⚠️ <strong>AUTOMATED MESSAGE - DO NOT REPLY</strong> ⚠️<br>
                    This is a system-generated notification from the Project AV PM Database. Replies to this email address are not monitored.
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

    # RESTORED: Your exact original attach method
    msg.attach(MIMEText(html_content, 'html'))

    all_recipients = [to_email]
    if cc_emails:
        all_recipients.extend([e.strip() for e in cc_emails.split(",") if e.strip()])

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
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
        print(f"CRITICAL ERROR: Could not open sheet '{SHEET_NAME}'. Check spelling or sharing permissions. Error: {e}")
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
            "cc_people", "subject", "message", "status", "created_at", "sent_at", "error"
        ])

    today = datetime.utcnow().date()
    today_str = today.strftime("%Y-%m-%d")
    
    if not df_tasks.empty:
        new_notifications = []
        for _, task in df_tasks.iterrows():
            status = str(task.get("status", ""))
            if status in ["Completed", "Cancelled", "Blocked"]: continue
                
            due_date_str = str(task.get("due_date", ""))
            if not due_date_str: continue
                
            try:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                days_left = (due_date - today).days
                
                time_label = None
                if days_left == 7: time_label = "in 1 week"
                elif days_left == 1: time_label = "tomorrow"
                elif days_left == 0: time_label = "today"
                elif days_left < 0: time_label = f"late ({abs(days_left)} days)"
                
                if time_label:
                    task_id = task.get("task_id", "")
                    already_queued = False
                    
                    if not df_notif.empty:
                        mask = (
                            (df_notif["task_id"] == str(task_id)) & 
                            (df_notif["created_at"].str.startswith(today_str, na=False))
                        )
                        if mask.any(): 
                            already_queued = True
                    
                    if not already_queued:
                        print(f"Auto-queuing {time_label} reminder for task: {task.get('title', 'Unknown')}")
                        
                        task_title = task.get('title', 'Unknown')
                        priority = task.get('priority', 'None')
                        
                        # Determine colors for the inner HTML body
                        prio_color = "#3b82f6" 
                        if "high" in priority.lower() or "critical" in priority.lower(): prio_color = "#ef4444" 
                        elif "medium" in priority.lower(): prio_color = "#f59e0b" 
                            
                        date_color = "#ef4444" if "late" in time_label.lower() else "#10b981"

                        # This inner HTML gets passed as `message_body` to the wrapper
                        inner_html = f"""
                        <p style="color: #94a3b8; font-size: 16px; margin-top: 0;">Incoming Task Notification,</p>
                        <p style="color: #e2e8f0; font-size: 16px; line-height: 1.6;">You have an action item requiring your attention. Please review the task details below.</p>
                        
                        <div style="background-color: #1e293b; border-left: 5px solid {prio_color}; padding: 20px; margin: 30px 0; border-radius: 4px;">
                          <h2 style="color: #f8fafc; margin: 0 0 15px 0; font-size: 20px;">{task_title}</h2>
                          <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                              <td width="30%" style="color: #94a3b8; padding-bottom: 8px; font-weight: bold;">Status:</td>
                              <td style="color: #f8fafc; padding-bottom: 8px;">Due {time_label}</td>
                            </tr>
                            <tr>
                              <td width="30%" style="color: #94a3b8; padding-bottom: 8px; font-weight: bold;">Timeline:</td>
                              <td style="color: {date_color}; padding-bottom: 8px; font-weight: bold;">{due_date_str}</td>
                            </tr>
                            <tr>
                              <td width="30%" style="color: #94a3b8; font-weight: bold;">Priority:</td>
                              <td style="color: {prio_color}; font-weight: bold;">{priority}</td>
                            </tr>
                          </table>
                        </div>
                        """
                        
                        new_row = {
                            "notification_id": str(uuid.uuid4()),
                            "task_id": task_id,
                            "notification_type": "Deadline Reminder",
                            "recipient": task.get("assigned_to", ""),
                            "cc_people": task.get("cc_people", ""),
                            "subject": f"Project AV | Task Update: {task_title}",
                            "message": inner_html, 
                            "status": "Queued",
                            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                            "sent_at": "",
                            "error": ""
                        }
                        new_notifications.append(new_row)
            except ValueError:
                pass 
        
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

            print(f"Sending HTML email to {to_email} (CC: {final_cc})...")
            success, err_msg = send_email(
                to_email=to_email,
                cc_emails=final_cc,
                subject=row.get("subject", "Task Update"),
                message_body=row.get("message", "") 
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
