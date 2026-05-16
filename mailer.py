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
        
    msg = MIMEMultipart()
    msg['From'] = f"Project AV <{GMAIL_ADDRESS}>"
    msg['To'] = to_email
    if cc_emails:
        msg['Cc'] = cc_emails
    msg['Subject'] = subject

    html_content = f"""
    <html>
      <body style="font-family: Arial, Helvetica, sans-serif; color: #222222; font-size: 14px; line-height: 1.5; max-width: 600px;">
        <p>Hi,</p>
        
        <p>Just sending a quick heads-up about an upcoming task for Project AV.</p>
        
        <div style="margin: 15px 0; padding: 10px 15px; border-left: 3px solid #2563eb; background-color: #fcfcfc;">
          {message_body}
        </div>
        
        <p>Please let the team lead know if you run into any blockers, and update your status on the board when you get a chance.</p>
        
        <p>
          Best,<br>
          <span style="color: #2563eb; font-weight: bold;">Project AV</span>
        </p>
      </body>
    </html>
    """
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
                            (df_notif["task_id"] == task_id) & 
                            (df_notif["subject"].str.lower().str.contains(time_label, regex=False, na=False)) &
                            (df_notif["created_at"].str.startswith(today_str, na=False))
                        )
                        if mask.any(): already_queued = True
                    
                    if not already_queued:
                        print(f"Auto-queuing {time_label} reminder for task: {task.get('title', 'Unknown')}")
                        new_row = {
                            "notification_id": str(uuid.uuid4()),
                            "task_id": task_id,
                            "notification_type": "Deadline Reminder",
                            "recipient": task.get("assigned_to", ""),
                            "cc_people": task.get("cc_people", ""),
                            "subject": f"Project AV Task Reminder: {task.get('title', 'Unknown')} ({time_label})",
                            "message": f"<span style='color: #666666;'>Task:</span> <b style='color: #000000;'>{task.get('title', 'Unknown')}</b><br><span style='color: #666666;'>Due:</span> <b style='color: #b30000;'>{due_date_str}</b><br><span style='color: #666666;'>Priority:</span> <b style='color: #000000;'>{task.get('priority', 'None')}</b>",
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
            
            # 1. SMART PARSING: Split multiple targets separated by commas
            raw_targets = [r.strip() for r in recipient_raw.split(",") if r.strip()]
            resolved_emails = []
            
            for target in raw_targets:
                if "@" in target:
                    # It's already an email, just add it!
                    resolved_emails.append(target)
                elif not df_memb.empty:
                    # It's a name, look it up in the directory
                    match = df_memb[df_memb["member_name"] == target]
                    if not match.empty:
                        em = str(match.iloc[0].get("email", ""))
                        if "@" in em:
                            resolved_emails.append(em)
            
            # Remove any duplicates
            resolved_emails = list(dict.fromkeys(resolved_emails))
            
            # If we still couldn't resolve any valid emails, skip it.
            if not resolved_emails:
                df_notif.at[idx, "status"] = "Failed"
                df_notif.at[idx, "error"] = f"No valid email found for: {recipient_raw}"
                print(f"Skipped {recipient_raw} - no email found.")
                continue

            # The first email goes to the "To:" line
            to_email = resolved_emails[0]
            
            # Any additional resolved emails are added to the "CC:" line
            existing_cc = str(row.get("cc_people", ""))
            cc_list = [c.strip() for c in existing_cc.split(",") if c.strip()]
            if len(resolved_emails) > 1:
                cc_list.extend(resolved_emails[1:])
            
            final_cc = ",".join(list(dict.fromkeys(cc_list)))

            print(f"Sending email to {to_email} (CC: {final_cc})...")
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
