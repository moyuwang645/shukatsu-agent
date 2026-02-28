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


def fetch_recent_emails(max_results=50):
    """Fetch recent emails, classify them, and auto-register interviews."""
    service = get_gmail_service()
    if not service:
        return []

    # Check if AI parsing is available
    from ai import is_ai_configured
    from ai.email_parser import parse_email_with_ai
    use_ai = is_ai_configured()
    if use_ai:
        logger.info("[gmail] AI parsing enabled")

    try:
        results = service.users().messages().list(
            userId='me',
            maxResults=max_results,
            q='newer_than:7d'
        ).execute()

        messages = results.get('messages', [])
        emails = []

        cached = get_cached_emails(limit=500)
        cached_ids = {e['gmail_id'] for e in cached if e.get('gmail_id')}

        for msg_info in messages:
            try:
                if msg_info['id'] in cached_ids:
                    continue

                msg = service.users().messages().get(
                    userId='me',
                    id=msg_info['id'],
                    format='full'
                ).execute()

                email_data = _parse_email(msg)
                if email_data:
                    # AI-enhanced classification
                    if use_ai:
                        ai_result = parse_email_with_ai(
                            email_data.get('subject', ''),
                            email_data.get('sender', ''),
                            email_data.get('full_body', '')
                        )
                        if ai_result:
                            email_data['ai_result'] = ai_result
                            if ai_result.get('is_job_related'):
                                email_data['is_job_related'] = 1
                            if ai_result.get('event_type') in ('interview', 'es_deadline', 'webtest', 'seminar'):
                                email_data['is_interview_invite'] = 1

                    cache_email(email_data)

                    # Auto-detect events
                    if email_data.get('is_interview_invite'):
                        if not is_email_processed(email_data['gmail_id']):
                            auto_register_interview(email_data)
                            mark_email_processed(email_data['gmail_id'])

                    emails.append(email_data)
            except Exception as e:
                logger.debug(f"Error parsing message {msg_info['id']}: {e}")

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
