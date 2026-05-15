import time
from gspread.exceptions import APIError, WorksheetNotFound

def ensure_worksheet_safe(sh, title, columns, retries=3):
    """Safely fetches a worksheet with automatic retries to prevent Google API crashes."""
    for attempt in range(retries):
        try:
            return sh.worksheet(title)
        except WorksheetNotFound:
            # If the sheet doesn't exist, create it
            ws = sh.add_worksheet(title=title, rows=1000, cols=len(columns))
            ws.append_row(columns)
            return ws
        except APIError as e:
            # If Google rate-limits us, wait a couple seconds and try again
            if attempt == retries - 1:
                raise e
            time.sleep(2)

def get_worksheet_df(client, title, columns, retries=3):
    """Fetches the worksheet and dataframe with a backoff system."""
    for attempt in range(retries):
        try:
            # Connect to the main sheet
            sheet_name = st.secrets.get("SHEET_NAME", "AV PM Reports Database")
            sh = client.open(sheet_name)
            
            # Safely get the specific tab
            ws = ensure_worksheet_safe(sh, title, columns)
            data = ws.get_all_records()
            
            # Convert to Pandas DataFrame
            if not data:
                df = pd.DataFrame(columns=columns)
            else:
                df = pd.DataFrame(data)
                
            return ws, df
            
        except APIError as e:
            if attempt == retries - 1:
                st.error(f"Google Sheets API is overloaded. Failed to load {title}. Please wait a moment and refresh.")
                raise e
            time.sleep(2.5) # Wait 2.5 seconds before retrying the whole fetch
