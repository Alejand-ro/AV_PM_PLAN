import os
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
# GitHub Actions will pass these securely into the script
GCP_JSON = os.environ.get("GCP_SERVICE_ACCOUNT")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
SHEET_NAME = os.environ.get("SHEET_NAME", "AV PM Reports Database")

def get_sheet_client():
    creds_dict = json.loads(GCP_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

def send_email(to_email, cc_emails, subject, message_body):
    """Sends a styled HTML email using Gmail SMTP."""
    msg = MIMEMultipart()
    msg['From'] = GMAIL_ADDRESS
    msg['To'] = to_email
    if cc_emails:
        msg['Cc'] = cc_emails
    msg['Subject'] = subject

    # Dark futuristic HTML wrapper to match your app's vibe
    html_content = f"""
    <html>
      <body style="background-color: #0f172a; color: #f8fafc; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px;">
        <div style="max-width: 600px; margin: 0 auto; background-color: #1e293b; padding: 30px; border-radius: 12px; border: 1px solid #334155;">
          <h2 style="color: #6366f1; margin-top: 0;">⌖ Project AV Command</h2>
          <p style="font-size: 16px; line-height: 1.6;">{message_body}</p>
          <hr style="border-color: #334155; margin: 30px 0;">
          <p style="font-size: 12px; color: #94a3b8;">This is an automated notification from the Project AV Operations system. Do not reply directly to this email.</p>
        </div>
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
    sh = client.open(SHEET_NAME)
    
    # Load Sheets
    ws_notif = sh.worksheet("planner_notifications_queue")
    ws_tasks = sh.worksheet("planner_tasks")
    ws_memb = sh.worksheet("planner_members")
    
    df_notif = pd.DataFrame(ws_notif.get_all_records())
    df_tasks = pd.DataFrame(ws_tasks.get_all_records())
    df_memb = pd.DataFrame(ws_memb.get_all_records())
    
    # Force empty df_notif to have correct columns so we can concat safely
    if df_notif.empty:
        df_notif = pd.DataFrame(columns=[
            "notification_id", "task_id", "notification_type", "recipient", 
            "cc_people", "subject", "message", "status", "created_at", "sent_at", "error"
        ])

    # --- ADVANCED DEADLINE LOGIC ---
    today = datetime.utcnow().date()
    today_str = today.strftime("%Y-%m-%d")
    
    if not df_tasks.empty:
        new_notifications = []
        for _, task in df_tasks.iterrows():
            status = str(task.get("status", ""))
            
            # Skip if completed, cancelled, or blocked (Blocked acts as our 'Snooze')
            if status in ["Completed", "Cancelled", "Blocked"]:
                continue
                
            due_date_str = str(task.get("due_date", ""))
            if not due_date_str:
                continue
                
            try:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                days_left = (due_date - today).days
                
                time_label = None
                if days_left == 7:
                    time_label = "in 1 week"
                elif days_left == 1:
                    time_label = "TOMORROW"
                elif days_left == 0:
                    time_label = "TODAY"
                elif days_left < 0:
                    time_label = f"LATE ({abs(days_left)} days)"
                
                if time_label:
                    task_id = task.get("task_id", "")
                    
                    # Prevent Spam: Ensure we haven't already queued THIS SPECIFIC notification today
                    already_queued = False
                    if not df_notif.empty:
                        mask = (
                            (df_notif["task_id"] == task_id) & 
                            (df_notif["subject"].str.contains(time_label, regex=False, na=False)) &
                            (df_notif["created_at"].str.startswith(today_str, na=False))
                        )
                        if mask.any():
                            already_queued = True
                    
                    if not already_queued:
                        print(f"Auto-queuing {time_label} reminder for task: {task.get('title', 'Unknown')}")
                        
                        new_row = {
                            "notification_id": str(uuid.uuid4()),
                            "task_id": task_id,
                            "notification_type": "Automated Deadline",
                            "recipient": task.get("assigned_to", ""),
                            "cc_people": task.get("cc_people", ""),
                            "subject": f"⚠ TASK {time_label}: {task.get('title', 'Unknown')}",
                            "message": f"<strong>Task:</strong> {task.get('title', 'Unknown')}<br><strong>Due:</strong> {due_date_str}<br><strong>Priority:</strong> {task.get('priority', 'None')}<br><br>Please update your progress in the PM Command app.",
                            "status": "Queued",
                            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                            "sent_at": "",
                            "error": ""
                        }
                        new_notifications.append(new_row)
            except ValueError:
                pass # Invalid date string, skip it
        
        # Add newly generated deadline emails to the queue
        if new_notifications:
            df_notif = pd.concat([df_notif, pd.DataFrame(new_notifications)], ignore_index=True)

    # --- EMAIL SENDER SCRIPT ---
    if df_notif.empty:
        print("Queue is entirely empty. Exiting.")
        return

    # Isolate emails marked as "Queued"
    queued_mask = df_notif["status"] == "Queued"
    emails_to_send = df_notif[queued_mask]
    
    if emails_to_send.empty:
        print("No emails to send right now.")
    else:
        for idx, row in emails_to_send.iterrows():
            recipient_name = row.get("recipient", "")
            
            # Lookup email from Team Directory
            to_email = ""
            if not df_memb.empty and recipient_name:
                match = df_memb[df_memb["member_name"] == recipient_name]
                if not match.empty:
                    to_email = match.iloc[0].get("email", "")
            
            # If no email found, skip and log error
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
            
            # Update Status
            if success:
                df_notif.at[idx, "status"] = "Sent"
                df_notif.at[idx, "sent_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            else:
                df_notif.at[idx, "status"] = "Failed"
                df_notif.at[idx, "error"] = err_msg

    # Write results back to Google Sheets
    df_notif.fillna("", inplace=True)
    ws_notif.clear()
    ws_notif.update("1:1", [df_notif.columns.values.tolist()])
    if not df_notif.empty:
        ws_notif.update("A2", df_notif.values.tolist())
    print("Run complete. Google Sheets updated.")

if __name__ == "__main__":
    process_queue()
