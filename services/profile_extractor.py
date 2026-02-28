"""Profile extractor — extracts personal info from ES documents using LLM.

Parses the raw text from an uploaded ES (PDF/DOCX/image) and extracts
structured personal information like name, kana, university, address, etc.
"""
import json
import logging

logger = logging.getLogger(__name__)


_DEFAULT_PROFILE_PROMPT = """以下はES(エントリーシート)または履歴書から抽出されたテキストです。
ここから就活生の基本的な個人情報をJSON形式で抽出してください。

必ず以下のJSON形式のみで返答し、該当情報がない場合は空文字列にしてください。

{{"name": "氏名（漢字）", "name_kana": "氏名（フリガナ）", "email": "メールアドレス", "phone": "電話番号", "postcode": "郵便番号", "address": "住所", "university": "大学名", "faculty": "学部", "department": "学科・専攻", "graduation_year": "卒業予定年（例: 2027）", "graduation_month": "卒業予定月（例: 3）", "gpa": "GPA（あれば）", "gender": "性別"}}

--- 抽出テキスト ---
{text}"""


def extract_profile_from_text(raw_text: str) -> dict:
    """Extract user profile info from ES raw text using LLM.

    Returns a dict with personal fields, or empty dict on failure.
    """
    from ai import call_llm, is_ai_configured, clean_json_response

    if not raw_text or not raw_text.strip():
        return {}

    if not is_ai_configured():
        logger.debug("[profile] AI not configured, skipping profile extraction")
        return {}

    prompt = _DEFAULT_PROFILE_PROMPT.format(text=raw_text[:4000])

    try:
        raw_result = call_llm(prompt)
        cleaned = clean_json_response(raw_result)
        profile = json.loads(cleaned)

        # Ensure all expected keys exist
        expected = ['name', 'name_kana', 'email', 'phone', 'postcode',
                    'address', 'university', 'faculty', 'department',
                    'graduation_year', 'graduation_month', 'gpa', 'gender']
        for key in expected:
            profile.setdefault(key, '')

        # Filter out empty values for cleaner storage
        non_empty = {k: v for k, v in profile.items() if v}
        logger.info(f"[profile] Extracted {len(non_empty)} fields: "
                    f"{', '.join(non_empty.keys())}")
        return profile

    except json.JSONDecodeError as e:
        logger.warning(f"[profile] JSON parse error: {e}")
        return {}
    except Exception as e:
        logger.warning(f"[profile] Extraction failed: {e}")
        return {}


def extract_and_save_profile(raw_text: str) -> dict:
    """Extract profile from text and save to DB."""
    from db.user_profile import save_user_profile, get_user_profile

    profile = extract_profile_from_text(raw_text)
    if not profile:
        return {}

    # Merge with existing profile (don't overwrite non-empty fields)
    existing = get_user_profile()
    if existing and existing.get('parsed'):
        merged = existing['parsed'].copy()
        for key, val in profile.items():
            if val:  # Only overwrite if new value is non-empty
                merged[key] = val
        profile = merged

    save_user_profile(profile)
    logger.info(f"[profile] Profile saved to DB")
    return profile


def extract_mypage_credentials_from_email(subject: str, body: str) -> dict | None:
    """Extract MyPage login credentials from an email body using LLM.

    Returns dict with: login_url, username, password, company_name
    Or None if no credentials found.
    """
    from ai import call_llm, is_ai_configured, clean_json_response

    # Quick keyword checks before burning an LLM call
    keywords = ['マイページ', 'MyPage', 'mypage', 'ログイン', 'ID', 'パスワード']
    text = subject + body
    if not any(kw in text for kw in keywords):
        return None

    if not is_ai_configured():
        return None

    prompt = f"""以下の就活関連メールからマイページのログイン情報を抽出して、JSON形式で返してください。
マイページURL、ログインIDまたはメールアドレス、初期パスワードが含まれている場合のみ抽出してください。

必ず以下のJSON形式のみで回答。マイページ情報がない場合は {{"found": false}} を返してください。

{{"found": true, "login_url": "マイページURL", "username": "ログインID/メールアドレス", "password": "初期パスワード", "company_name": "企業名"}}

--- メール件名 ---
{subject}

--- メール本文 ---
{body[:3000]}"""

    try:
        raw = call_llm(prompt)
        cleaned = clean_json_response(raw)
        result = json.loads(cleaned)

        if not result.get('found'):
            return None

        if not result.get('login_url') and not result.get('username'):
            return None

        logger.info(f"[profile] MyPage credentials found for: "
                    f"{result.get('company_name', 'unknown')}")
        return result

    except Exception as e:
        logger.warning(f"[profile] Credential extraction failed: {e}")
        return None
