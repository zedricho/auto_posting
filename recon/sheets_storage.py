"""Google Sheets storage backend for stocktake data."""

import json
from datetime import date, datetime
from typing import Dict, List, Optional

import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

from recon.stocktake import BaseItem, StocktakeSession, StocktakeCount


# Google Sheets scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client():
    """Get authenticated Google Sheets client."""
    if not GSPREAD_AVAILABLE:
        raise ImportError("gspread not installed. Run: pip install gspread google-auth")

    # Get credentials from Streamlit secrets
    creds_dict = st.secrets.get("gcp_service_account")
    if not creds_dict:
        raise ValueError("No GCP service account credentials in Streamlit secrets")

    creds = Credentials.from_service_account_info(dict(creds_dict), scopes=SCOPES)
    return gspread.authorize(creds)


def get_spreadsheet():
    """Get the stocktake spreadsheet."""
    client = get_client()
    spreadsheet_id = st.secrets.get("stocktake_spreadsheet_id")
    if not spreadsheet_id:
        raise ValueError("No stocktake_spreadsheet_id in Streamlit secrets")
    return client.open_by_key(spreadsheet_id)


# ============ BASE ITEMS ============

def load_base_items_sheets() -> List[BaseItem]:
    """Load base items from Google Sheets."""
    try:
        spreadsheet = get_spreadsheet()

        # Get or create BASE sheet
        try:
            worksheet = spreadsheet.worksheet("BASE")
        except gspread.WorksheetNotFound:
            return []

        records = worksheet.get_all_records()
        items = []
        for row in records:
            if not row.get("item_code"):
                continue
            items.append(BaseItem(
                item_code=str(row.get("item_code", "")),
                name=str(row.get("name", "")),
                department=str(row.get("department", "")),
                jan26_inhouse=int(row.get("inhouse", 0) or 0),
                warehouse=int(row.get("warehouse", 0) or 0),
                total=int(row.get("total", 0) or 0),
            ))
        return items
    except Exception as e:
        st.error(f"Error loading base items: {e}")
        return []


def save_base_items_sheets(items: List[BaseItem]):
    """Save base items to Google Sheets."""
    try:
        spreadsheet = get_spreadsheet()

        # Get or create BASE sheet
        try:
            worksheet = spreadsheet.worksheet("BASE")
            worksheet.clear()
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="BASE", rows=1000, cols=10)

        # Write header
        header = ["item_code", "name", "department", "inhouse", "warehouse", "total"]
        worksheet.update("A1:F1", [header])

        # Write data
        if items:
            data = [
                [item.item_code, item.name, item.department,
                 item.jan26_inhouse, item.warehouse, item.total]
                for item in items
            ]
            worksheet.update(f"A2:F{len(data)+1}", data)

        return True
    except Exception as e:
        st.error(f"Error saving base items: {e}")
        return False


# ============ SESSIONS ============

def load_sessions_sheets() -> List[StocktakeSession]:
    """Load all sessions from Google Sheets."""
    try:
        spreadsheet = get_spreadsheet()

        # Get or create SESSIONS sheet
        try:
            worksheet = spreadsheet.worksheet("SESSIONS")
        except gspread.WorksheetNotFound:
            return []

        records = worksheet.get_all_records()
        sessions = []
        for row in records:
            if not row.get("session_id"):
                continue

            # Parse counts from JSON
            counts_json = row.get("counts", "{}")
            try:
                counts_dict = json.loads(counts_json) if counts_json else {}
            except json.JSONDecodeError:
                counts_dict = {}

            counts = {
                k: StocktakeCount(
                    item_code=k,
                    warehouse=v.get("warehouse", 0),
                    onsite=v.get("onsite", 0),
                )
                for k, v in counts_dict.items()
            }

            # Parse date
            date_str = str(row.get("session_date", ""))
            try:
                session_date = date.fromisoformat(date_str)
            except ValueError:
                session_date = date.today()

            sessions.append(StocktakeSession(
                session_id=str(row.get("session_id", "")),
                session_date=session_date,
                name=str(row.get("name", "")),
                location=str(row.get("location", "Both")),
                counts=counts,
                completed_by=str(row.get("completed_by", "")),
                status=str(row.get("status", "in_progress")),
                notes=str(row.get("notes", "")),
                created_at=str(row.get("created_at", "")),
                updated_at=str(row.get("updated_at", "")),
            ))
        return sessions
    except Exception as e:
        st.error(f"Error loading sessions: {e}")
        return []


def save_session_sheets(session: StocktakeSession):
    """Save a session to Google Sheets."""
    try:
        spreadsheet = get_spreadsheet()

        # Get or create SESSIONS sheet
        try:
            worksheet = spreadsheet.worksheet("SESSIONS")
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title="SESSIONS", rows=100, cols=15)
            # Write header
            header = ["session_id", "session_date", "name", "location", "status",
                      "completed_by", "notes", "created_at", "updated_at", "counts"]
            worksheet.update("A1:J1", [header])

        # Convert counts to JSON
        counts_dict = {k: v.to_dict() for k, v in session.counts.items()}
        counts_json = json.dumps(counts_dict)

        # Check if session already exists
        records = worksheet.get_all_records()
        row_num = None
        for i, row in enumerate(records, start=2):  # Start at 2 (after header)
            if row.get("session_id") == session.session_id:
                row_num = i
                break

        # Prepare row data
        row_data = [
            session.session_id,
            session.session_date.isoformat(),
            session.name,
            session.location,
            session.status,
            session.completed_by,
            session.notes,
            session.created_at,
            datetime.now().isoformat(),  # updated_at
            counts_json,
        ]

        if row_num:
            # Update existing row
            worksheet.update(f"A{row_num}:J{row_num}", [row_data])
        else:
            # Append new row
            worksheet.append_row(row_data)

        return True
    except Exception as e:
        st.error(f"Error saving session: {e}")
        return False


def get_session_sheets(session_id: str) -> Optional[StocktakeSession]:
    """Get a specific session by ID."""
    sessions = load_sessions_sheets()
    for s in sessions:
        if s.session_id == session_id:
            return s
    return None


# ============ WRAPPER FUNCTIONS ============

def is_sheets_enabled() -> bool:
    """Check if Google Sheets storage is enabled."""
    try:
        return bool(st.secrets.get("gcp_service_account")) and bool(st.secrets.get("stocktake_spreadsheet_id"))
    except Exception:
        return False
