"""Shukatsu Agent - Flask Application."""
import os
import logging
from datetime import date, datetime
from flask import Flask, render_template, request
from config import Config
from database import (
    init_db, get_all_jobs, get_job_stats,
    get_upcoming_deadlines, get_jobs_by_deadline,
    get_honsen_urgent_deadlines,
    get_all_interviews, get_upcoming_interviews,
    get_unread_notifications, get_cached_emails, get_last_scrape,
    get_preferences
)
from scheduler import init_scheduler, shutdown_scheduler
from routes import register_blueprints

# Ensure data directory exists before logging setup
os.makedirs(os.path.join(Config.BASE_DIR, 'data'), exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(Config.BASE_DIR, 'data', 'app.log'), encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
app.config['JSON_AS_ASCII'] = False  # Allow unicode in JSON responses


@app.after_request
def set_utf8_charset(response):
    """Ensure all HTML/JSON responses declare UTF-8 charset in HTTP headers."""
    if 'text/html' in response.content_type and 'charset' not in response.content_type:
        response.content_type = response.content_type + '; charset=utf-8'
    return response

# Register all API blueprints
register_blueprints(app)


# ========== Page Routes ==========

@app.route('/')
def dashboard():
    today = date.today().isoformat()
    today_deadlines = get_jobs_by_deadline(today)
    upcoming = get_upcoming_deadlines(days=7)
    upcoming_interviews = get_upcoming_interviews(days=7)
    honsen_urgent = get_honsen_urgent_deadlines(days=3)
    stats = get_job_stats()
    notifications = get_unread_notifications()
    last_scrape_info = get_last_scrape('mynavi')
    return render_template('dashboard.html',
                           today=today,
                           today_deadlines=today_deadlines,
                           upcoming_deadlines=upcoming,
                           upcoming_interviews=upcoming_interviews,
                           honsen_urgent=honsen_urgent,
                           stats=stats,
                           notifications=notifications,
                           last_scrape=last_scrape_info,
                           page='dashboard')


@app.route('/jobs')
def jobs_page():
    status_filter = request.args.get('status', '')
    source_filter = request.args.get('source', '')
    deadline_days = request.args.get('deadline_days', '')
    industry_filter = request.args.get('industry', '')
    jobs = get_all_jobs(
        status=status_filter if status_filter else None,
        source=source_filter if source_filter else None
    )
    # Filter by deadline if requested
    if deadline_days:
        try:
            from datetime import timedelta
            cutoff = (date.today() + timedelta(days=int(deadline_days))).isoformat()
            today_str = date.today().isoformat()
            jobs = [j for j in jobs if j.get('deadline') and today_str <= j['deadline'] <= cutoff]
        except (ValueError, TypeError):
            pass
    # Filter by industry if requested
    if industry_filter:
        jobs = [j for j in jobs if industry_filter in (j.get('industry') or '')]
    stats = get_job_stats()
    notifications = get_unread_notifications()
    return render_template('jobs.html',
                           jobs=jobs,
                           stats=stats,
                           notifications=notifications,
                           current_status=status_filter,
                           current_source=source_filter,
                           current_industry=industry_filter,
                           deadline_filter=deadline_days,
                           page='jobs')


@app.route('/calendar')
def calendar_page():
    jobs = get_all_jobs()
    interviews = get_all_interviews()
    notifications = get_unread_notifications()
    return render_template('calendar.html',
                           jobs=jobs,
                           interviews=interviews,
                           notifications=notifications,
                           page='calendar')


@app.route('/emails')
def emails_page():
    job_related = request.args.get('filter', '') == 'job'
    emails = get_cached_emails(job_related_only=job_related)
    notifications = get_unread_notifications()
    gmail_authed = False
    try:
        from gmail_browser import is_gmail_browser_configured
        gmail_authed = is_gmail_browser_configured()
    except Exception:
        pass
    return render_template('emails.html',
                           emails=emails,
                           notifications=notifications,
                           filter_job=job_related,
                           gmail_authed=gmail_authed,
                           page='emails')


@app.route('/settings')
def settings_page():
    notifications = get_unread_notifications()
    last_scrape_info = get_last_scrape('mynavi')
    gmail_configured = os.path.exists(Config.GMAIL_CREDENTIALS_PATH)
    gmail_authed = os.path.exists(Config.GMAIL_TOKEN_PATH)
    from gmail_browser import is_gmail_browser_configured
    gmail_browser_ok = is_gmail_browser_configured()
    if gmail_browser_ok:
        gmail_configured = True
        gmail_authed = True
    preferences = get_preferences()
    from ai_parser import get_ai_status
    ai_status = get_ai_status()
    return render_template('settings.html',
                           notifications=notifications,
                           last_scrape=last_scrape_info,
                           gmail_configured=gmail_configured,
                           gmail_authed=gmail_authed,
                           config=Config,
                           preferences=preferences,
                           ai_status=ai_status,
                           page='settings')


@app.route('/chat')
def chat_page():
    notifications = get_unread_notifications()
    return render_template('chat.html',
                           notifications=notifications,
                           page='chat')


@app.route('/es')
def es_page():
    notifications = get_unread_notifications()
    from db.es import get_all_es_documents
    es_docs = get_all_es_documents()
    return render_template('es_management.html',
                           notifications=notifications,
                           es_docs=es_docs,
                           page='es')


@app.route('/mypage')
def mypage_page():
    notifications = get_unread_notifications()
    from db.jobs import get_all_jobs
    jobs = get_all_jobs()
    return render_template('mypage.html',
                           notifications=notifications,
                           jobs=jobs,
                           page='mypage')


# ========== Startup ==========

with app.app_context():
    init_db()

init_scheduler()

import atexit
atexit.register(shutdown_scheduler)

if __name__ == '__main__':
    logger.info("🚀 Shukatsu Agent starting...")
    logger.info(f"Dashboard: http://localhost:{Config.PORT}")
    app.run(debug=Config.DEBUG, host=Config.HOST, port=Config.PORT)
