import os
import configparser
from dotenv import load_dotenv

load_dotenv()

def _load_db_path(base_dir: str) -> str:
    """Load DB path from app_config.ini → .env → default."""
    ini_path = os.path.join(base_dir, 'data', 'app_config.ini')
    if os.path.exists(ini_path):
        cfg = configparser.ConfigParser()
        cfg.read(ini_path, encoding='utf-8')
        path = cfg.get('database', 'db_path', fallback='')
        if path and os.path.isabs(path):
            return path
    # Fallback: .env or default
    return os.getenv('DB_PATH', os.path.join(base_dir, 'data', 'jobs.db'))


class Config:
    """Application configuration — all values configurable via .env"""
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = _load_db_path(BASE_DIR)

    # Job Categories (Japanese keywords for parsing roles)
    JOB_CATEGORY_KEYWORDS = [
        "ITエンジニア", "システムエンジニア", "SE", "プログラマー", "PG",
        "インフラエンジニア", "ネットワークエンジニア", "データサイエンティスト", "AIエンジニア",
        "営業", "法人営業", "個人営業", "ルート営業",
        "コンサルタント", "ITコンサルタント", "経営企画",
        "総合職", "一般事務", "営業事務", "経理", "人事", "総務",
        "研究開発", "製品開発", "機械設計", "電気電子設計",
        "マーケティング", "企画", "広報"
    ]

    # Server
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', '5000'))
    DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

    # マイナビ
    MYNAVI_YEAR = os.getenv('MYNAVI_YEAR', '27')  # 卒業年 (e.g. 27 = 2027年卒)
    MYNAVI_EMAIL = os.getenv('MYNAVI_EMAIL', '')
    MYNAVI_PASSWORD = os.getenv('MYNAVI_PASSWORD', '')

    # Gmail
    GMAIL_ENABLED = os.getenv('GMAIL_ENABLED', 'false').lower() == 'true'
    GMAIL_CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')
    GMAIL_TOKEN_PATH = os.path.join(BASE_DIR, 'data', 'gmail_token.json')
    GMAIL_OAUTH_PORT = int(os.getenv('GMAIL_OAUTH_PORT', '8090'))

    # Scheduler
    SCRAPE_MORNING_HOUR = int(os.getenv('SCRAPE_MORNING_HOUR', '8'))
    SCRAPE_MORNING_MINUTE = int(os.getenv('SCRAPE_MORNING_MINUTE', '30'))
    SCRAPE_EVENING_HOUR = int(os.getenv('SCRAPE_EVENING_HOUR', '18'))
    SCRAPE_EVENING_MINUTE = int(os.getenv('SCRAPE_EVENING_MINUTE', '30'))
    EMAIL_CHECK_INTERVAL_MINUTES = int(os.getenv('EMAIL_CHECK_INTERVAL_MINUTES', '30'))
    MORNING_ALERT_HOUR = int(os.getenv('MORNING_ALERT_HOUR', '7'))
    MORNING_ALERT_MINUTE = int(os.getenv('MORNING_ALERT_MINUTE', '0'))
    TIMEZONE = os.getenv('TIMEZONE', 'Asia/Tokyo')

    # AI Email Parser
    AI_PROVIDER = os.getenv('AI_PROVIDER', '')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')

    # Browser automation
    HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
    BROWSER_LOCALE = os.getenv('BROWSER_LOCALE', 'ja-JP')

    # File uploads (ES documents)
    UPLOAD_DIR = os.path.join(BASE_DIR, 'data', 'uploads')
    MAX_UPLOAD_SIZE = int(os.getenv('MAX_UPLOAD_SIZE', str(16 * 1024 * 1024)))  # 16MB default
