"""Gmail API integration — OAuth2 authentication and email fetching.

Higher-level email classification and event detection are handled by
the services package (services/__init__.py and services/event_detector.py).
"""
import os
import base64
import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from config import Config
from database import (
    cache_email, get_cached_emails,
    mark_email_processed, is_email_processed,
)
from services import (
    JOB_KEYWORDS, INTERVIEW_KEYWORDS, CONFIRMATION_KEYWORDS,
)
from services.event_detector import auto_register_interview

logger = logging.getLogger(__name__)

# Backward-compatible alias (used by scheduler.py, routes/api_gmail.py, etc.)
_auto_register_interview = auto_register_interview


def get_gmail_service():
    """Get authenticated Gmail API service."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

        creds = None
        token_path = Config.GMAIL_TOKEN_PATH
        creds_path = Config.GMAIL_CREDENTIALS_PATH

        if not os.path.exists(creds_path):
            logger.error(f"Gmail credentials.json not found at {creds_path}")
            return None

        os.makedirs(os.path.dirname(token_path), exist_ok=True)

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=Config.GMAIL_OAUTH_PORT)
            with open(token_path, 'w') as token:
                token.write(creds.to_json())

        service = build('gmail', 'v1', credentials=creds)
        return service

    except Exception as e:
        logger.exception(f"Gmail service init error: {e}")
        return None


def fetch_recent_emails(query: str = 'newer_than:7d', max_results: int = 0):
    """Fetch emails via Gmail API with query and optional pagination.

    Args:
        query: Gmail search query (e.g. 'after:2026/02/01', 'newer_than:7d').
        max_results: Max emails to return. 0 = fetch ALL matching (paginated).

    Returns:
        List of email dicts in standard format.
    """
    service = get_gmail_service()
    if not service:
        return []

    try:
        # Collect all message IDs via pagination
        all_message_ids = []
        page_token = None
        # Gmail API maxResults per page is capped at 500
        page_size = min(max_results, 500) if max_results > 0 else 500

        while True:
            kwargs = {
                'userId': 'me',
                'q': query,
                'maxResults': page_size,
            }
            if page_token:
                kwargs['pageToken'] = page_token

            results = service.users().messages().list(**kwargs).execute()
            messages = results.get('messages', [])
            all_message_ids.extend(msg['id'] for msg in messages)

            # Check if we've reached the limit
            if max_results > 0 and len(all_message_ids) >= max_results:
                all_message_ids = all_message_ids[:max_results]
                break

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        logger.info(f"[gmail-api] Found {len(all_message_ids)} messages for query: {query}")

        if not all_message_ids:
            return []

        # Fetch each message's full content
        total = len(all_message_ids)
        emails = []
        errors = 0

        # Import progress tracker
        try:
            from services.gmail_progress import update_progress
        except ImportError:
            update_progress = None

        for idx, msg_id in enumerate(all_message_ids, 1):
            try:
                msg = service.users().messages().get(
                    userId='me',
                    id=msg_id,
                    format='full'
                ).execute()

                email_data = _parse_email(msg)
                if email_data:
                    emails.append(email_data)
            except Exception as e:
                errors += 1
                if errors <= 5:
                    logger.warning(f"[gmail-api] Error parsing message {msg_id}: {e}")

            # Progress logging every 50 messages
            if idx % 50 == 0 or idx == total:
                logger.info(
                    f"[gmail-api] Progress: {idx}/{total} messages "
                    f"({len(emails)} parsed, {errors} errors)"
                )
                # Update frontend progress
                if update_progress:
                    update_progress(
                        stage='downloading',
                        current=idx, total=total,
                        message=f'メール取得中: {idx}/{total}件',
                    )

        logger.info(f"[gmail-api] Done: {len(emails)} emails parsed from {total} messages")


        return emails

    except Exception as e:
        logger.exception(f"Error fetching emails: {e}")
        return []


def _parse_email(msg) -> dict:
    """Parse a Gmail message into our format with enhanced classification."""
    headers = {h['name'].lower(): h['value'] for h in msg['payload']['headers']}

    subject = headers.get('subject', '(No Subject)')
    sender = headers.get('from', '')
    date_str = headers.get('date', '')

    try:
        received_at = parsedate_to_datetime(date_str).isoformat()
    except Exception:
        received_at = datetime.now().isoformat()

    body = _get_body(msg['payload'])
    body_preview = body[:500] if body else ''
    full_body = body[:3000] if body else ''

    full_text = f"{subject} {sender} {full_body}"
    is_job_related = any(kw in full_text for kw in JOB_KEYWORDS)

    has_interview_kw = any(kw in full_text for kw in INTERVIEW_KEYWORDS)
    has_confirmation_kw = any(kw in full_text for kw in CONFIRMATION_KEYWORDS)
    is_interview = has_interview_kw or has_confirmation_kw

    return {
        'gmail_id': msg['id'],
        'subject': subject,
        'sender': sender,
        'body_preview': body_preview,
        'full_body': full_body,
        'received_at': received_at,
        'is_job_related': 1 if is_job_related else 0,
        'is_interview_invite': 1 if is_interview else 0,
    }


def _get_body(payload) -> str:
    """Extract email body text from Gmail API payload."""
    body_text = ''

    if payload.get('body', {}).get('data'):
        body_text = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='replace')
    elif payload.get('parts'):
        for part in payload['parts']:
            mime = part.get('mimeType', '')
            if mime == 'text/plain' and part.get('body', {}).get('data'):
                body_text = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                break
            elif mime == 'text/html' and part.get('body', {}).get('data') and not body_text:
                import re
                html = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                body_text = re.sub(r'<[^>]+>', '', html)
            elif mime.startswith('multipart/') and part.get('parts'):
                body_text = _get_body(part)
                if body_text:
                    break

    return body_text.strip()


# Legacy aliases for backward compatibility
def extract_dates_from_email(text):
    """Legacy wrapper."""
    from services import extract_dates_from_text
    return extract_dates_from_text(text)


def start_gmail_auth():
    """Initiate Gmail OAuth2 authentication flow."""
    service = get_gmail_service()
    if service:
        try:
            profile = service.users().getProfile(userId='me').execute()
            return True, profile.get('emailAddress', 'unknown')
        except Exception as e:
            return False, str(e)
    return False, "Could not initialize Gmail service"
