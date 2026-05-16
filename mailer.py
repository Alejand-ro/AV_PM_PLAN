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
    msg['From'] = f"Project AV Operations <{GMAIL_ADDRESS}>"
    msg['To'] = to_email
    if cc_emails:
        msg['Cc'] = cc_emails
    msg['Subject'] = subject

    # Clean, lightweight, professional HTML that bypasses spam filters
    html_content = f"""
    <html>
      <body style="font-family: Arial, Helvetica, sans-serif; color: #222222; line-height: 1.6; max-width: 600px;">
        <p style="font-size: 14px;">Hello,</p>
        
        <p style="font-size: 14px;">
          This is a friendly automated reminder regarding an upcoming task deadline for <strong>Project AV</strong>:
        </p>
        
        <div style="margin: 20px 0; padding: 12px 15px; border-left: 4px solid #0056b3; background-color: #f8f9fa;">
          <span style="font-size: 14px;">{message_body}</span>
        </div>
        
        <p style="font-size: 14px;">
          Please review the details and update your progress at your earliest convenience. Let your lead know if you are facing any blockers.
        </p>
        
        <br>
        <p style="font-size: 13px; color: #555555; margin-bottom: 0;">
          Best regards,<br>
          <strong>Project AV Operations Team</strong>
        </p>
        <p style="font-size: 11px; color: #999999; margin-top: 5px;">
          ⌖ Automated PM Command System
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
                elif days_left == 1: time_label = "TOMORROW"
                elif days_left == 0: time_label = "TODAY"
                elif days_left < 0: time_label = f"LATE ({abs(days_left)} days)"
                
                if time_label:
                    task_id = task.get("task_id", "")
                    already_queued = False
                    if not df_notif.empty:
                        mask = (
                            (df_notif["task_id"] == task_id) & 
                            (df_notif["subject"].str.contains(time_label, regex=False, na=False)) &
                            (df_notif["created_at"].str.startswith(today_str, na=False))
                        )
                        if mask.any(): already_queued = True
                    
                    if not already_queued:
                        print(f"Auto-queuing {time_label} reminder for task: {task.get('title', 'Unknown')}")
                        new_row = {
                            "notification_id": str(uuid.uuid4()),
                            "task_id": task_id,
                            "notification_type": "Automated Deadline",
                            "recipient": task.get("assigned_to", ""),
                            "cc_people": task.get("cc_people", ""),
                            "subject": f"⚠ TASK {time_label}: {task.get('title', 'Unknown')}",
                            "message": f"<strong>Task:</strong> {task.get('title', 'Unknown')}<br><strong>Due:</strong> {due_date_str}<br><strong>Priority:</strong> {task.get('priority', 'None')}",
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
            recipient_name = row.get("recipient", "")
            
            to_email = ""
            if not df_memb.empty and recipient_name:
                match = df_memb[df_memb["member_name"] == recipient_name]
                if not match.empty:
                    to_email = match.iloc[0].get("email", "")
            
            if not to_email or "@" not in to_email:
                df_notif.at[idx, "status"] = "Failed"
                df_notif.at[idx, "error"] = f"No valid email found for {recipient_name}"
                print(f"Skipped {recipient_name} - no email found in directory.")
                continue

            print(f"Sending email to {to_email}...")
            success, err_msg = send_email(
                to_email=to_email,
                cc_emails=row.get("cc_people", ""),
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
    
    # Bulletproof gspread writing (handles both v5 and v6 of the library)
    try:
        ws_notif.update(data_to_write, "A1") 
    except TypeError:
        ws_notif.update("A1", data_to_write)
        
    print("Run complete. Google Sheets updated.")

if __name__ == "__main__":
    process_queue()
