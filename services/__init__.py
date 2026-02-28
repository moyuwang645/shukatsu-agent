"""Email classification keywords and text extraction utilities.

Contains all regex patterns and keyword lists used to classify
job-related emails and extract structured data (dates, locations,
company names, interview types) from email text.
"""
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ===== Keyword Definitions =====

# General job-hunting keywords
JOB_KEYWORDS = [
    '面接', '面談', '選考', '内定', 'エントリー', '説明会',
    '書類選考', 'ES', 'Webテスト', 'SPI', '適性検査',
    '一次面接', '二次面接', '最終面接', 'グループディスカッション',
    'インターン', '会社説明会', '合否', '採用', '就活',
    'オファー', 'offer', '内々定', '承諾', '辞退',
    'マイナビ', 'リクナビ', 'mynavi', 'rikunabi',
]

# Keywords for interview invitation / selection process emails
INTERVIEW_KEYWORDS = [
    '面接', '面談', '選考のご案内', '日程', 'スケジュール',
    '一次', '二次', '最終', 'グループディスカッション',
    'Webテスト', '適性検査', '筆記試験',
]

# Keywords specifically for confirmation / reply emails from companies
CONFIRMATION_KEYWORDS = [
    '予約が確定', '予約を承りました', '面接の確認', '選考のご案内',
    '予約完了', '日程が確定', '日程の確認', 'ご予約ありがとう',
    '以下の内容で承りました', '下記の通り確定', '面接日程のお知らせ',
    '面談日程のお知らせ', '選考日程のご連絡', 'ご案内',
    '面接のご案内', '説明会のご案内', '参加を受け付けました',
    '予約を確認', 'ご参加ありがとう', 'エントリーを受け付け',
    '応募を受け付け', '書類選考の結果', '選考通過', '次のステップ',
    '面接のお願い', 'ご来社', 'ご参加', '日時のご連絡',
    'reservation confirmed', 'interview scheduled', 'booking confirmed',
]

# ES (Entry Sheet) deadline keywords
ES_DEADLINE_KEYWORDS = [
    'ES締切', 'ES提出期限', 'エントリーシート締切', 'エントリーシート提出',
    'ES提出', '書類提出期限', '提出期限', 'ES受付終了',
    '書類選考締切', '書類締切', 'ES受付',
    'エントリー締切', 'エントリー受付終了', '応募締切', '募集締切',
    '締め切り', '〆切', '提出締切', '受付終了',
]

# Interview type detection patterns
INTERVIEW_TYPE_PATTERNS = [
    (r'最終面接', '最終面接'),
    (r'三次面接', '三次面接'),
    (r'二次面接', '二次面接'),
    (r'一次面接', '一次面接'),
    (r'役員面接', '役員面接'),
    (r'グループディスカッション|GD', 'グループディスカッション'),
    (r'グループ面接|集団面接', 'グループ面接'),
    (r'カジュアル面談', 'カジュアル面談'),
    (r'Webテスト|WEBテスト|ウェブテスト', 'Webテスト'),
    (r'適性検査|SPI|筆記試験|筆記テスト', '適性検査'),
    (r'会社説明会|企業説明会|合同説明会', '説明会'),
    (r'面談', '面談'),
    (r'面接', '面接'),
]

# Date/time extraction patterns (ordered by specificity)
DATE_PATTERNS = [
    (r'(\d{4})年(\d{1,2})月(\d{1,2})日[（(]?[月火水木金土日]?[）)]?\s*(\d{1,2})[時:](\d{2})', 'ymdhm'),
    (r'(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})', 'ymdhm'),
    (r'(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})', 'ymdhm'),
    (r'(\d{1,2})月(\d{1,2})日[（(]?[月火水木金土日]?[）)]?\s*(\d{1,2})[時:](\d{2})', 'mdhm'),
    (r'(\d{4})年(\d{1,2})月(\d{1,2})日', 'ymd'),
    (r'(\d{1,2})月(\d{1,2})日', 'md'),
]

# Location extraction patterns
LOCATION_PATTERNS = [
    r'場所[：:]\s*(.+?)(?:\n|$)',
    r'会場[：:]\s*(.+?)(?:\n|$)',
    r'実施場所[：:]\s*(.+?)(?:\n|$)',
    r'面接場所[：:]\s*(.+?)(?:\n|$)',
    r'アクセス[：:]\s*(.+?)(?:\n|$)',
    r'住所[：:]\s*(.+?)(?:\n|$)',
    r'(?:東京都|大阪府|神奈川県|愛知県|福岡県|北海道|京都府|兵庫県).+?(?:\d+-\d+|\d+丁目)',
]

# Online meeting URL patterns
ONLINE_URL_PATTERNS = [
    r'(https?://[\w.-]+\.zoom\.us/\S+)',
    r'(https?://meet\.google\.com/\S+)',
    r'(https?://teams\.microsoft\.com/\S+)',
    r'(https?://[\w.-]+\.webex\.com/\S+)',
    r'(https?://whereby\.com/\S+)',
]


# ===== Extraction Functions =====

def extract_company_name(sender: str, subject: str, body: str) -> str | None:
    """Extract company name from email sender, subject, or body."""
    # Try extracting from sender display name
    sender_name_match = re.match(r'^"?(.+?)"?\s*<', sender)
    if sender_name_match:
        name = sender_name_match.group(1).strip()
        generic_names = [
            'no-reply', 'noreply', 'info', 'admin', 'support',
            'マイナビ', 'リクナビ', 'mynavi', 'rikunabi',
            'Indeed', 'Wantedly', 'Green', 'ビズリーチ',
        ]
        if not any(g.lower() in name.lower() for g in generic_names):
            return name

    # Try extracting from subject patterns
    company_patterns = [
        r'【(.+?)】',
        r'＜(.+?)＞',
        r'\[(.+?)\]',
        r'(.+?(?:株式会社|有限会社|合同会社|Inc\.|Corp\.|Co\.,?\s*Ltd\.?))',
    ]
    for pattern in company_patterns:
        match = re.search(pattern, subject)
        if match:
            name = match.group(1).strip()
            if 2 <= len(name) <= 50:
                return name

    # Try body for company name
    body_patterns = [
        r'(?:株式会社|有限会社|合同会社)[\w\u3000-\u9fff]+',
        r'[\w\u3000-\u9fff]+(?:株式会社|有限会社|合同会社)',
    ]
    for pattern in body_patterns:
        match = re.search(pattern, body)
        if match:
            return match.group(0).strip()

    # Fallback: extract from sender email domain
    domain_match = re.search(r'@([\w.-]+)', sender)
    if domain_match:
        domain = domain_match.group(1)
        skip_domains = ['gmail.com', 'yahoo.co.jp', 'outlook.com', 'hotmail.com',
                       'mynavi.jp', 'rikunabi.com', 'icloud.com']
        if domain not in skip_domains:
            return domain.split('.')[0].replace('-', ' ').title()

    return None


def detect_interview_type(text: str) -> str:
    """Detect the type of interview from email text."""
    for pattern, label in INTERVIEW_TYPE_PATTERNS:
        if re.search(pattern, text):
            return label
    return '面接'


def extract_location(text: str) -> str | None:
    """Extract physical location from email text."""
    for pattern in LOCATION_PATTERNS:
        match = re.search(pattern, text)
        if match:
            location = match.group(1).strip() if match.lastindex else match.group(0).strip()
            location = re.sub(r'\s+', ' ', location)
            if len(location) > 5:
                return location[:100]
    return None


def extract_online_url(text: str) -> str | None:
    """Extract online meeting URL from email text."""
    for pattern in ONLINE_URL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def extract_dates_from_text(text: str) -> list:
    """Extract date/time information from text."""
    dates = []
    now = datetime.now()

    for pattern, fmt_type in DATE_PATTERNS:
        for match in re.finditer(pattern, text):
            groups = match.groups()
            try:
                if fmt_type == 'ymdhm':
                    y, m, d, h, mi = [int(g) for g in groups]
                    if y < 100:
                        y += 2000
                    dates.append(datetime(y, m, d, h, mi))
                elif fmt_type == 'mdhm':
                    m, d, h, mi = [int(g) for g in groups]
                    year = now.year if m >= now.month else now.year + 1
                    dates.append(datetime(year, m, d, h, mi))
                elif fmt_type == 'ymd':
                    y, m, d = [int(g) for g in groups]
                    dates.append(datetime(y, m, d))
                elif fmt_type == 'md':
                    m, d = [int(g) for g in groups]
                    year = now.year if m >= now.month else now.year + 1
                    dates.append(datetime(year, m, d))
            except (ValueError, TypeError):
                continue

    return dates


# Legacy alias
extract_dates_from_email = extract_dates_from_text
