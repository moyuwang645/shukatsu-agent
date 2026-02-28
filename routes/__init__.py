"""Flask Blueprints for API routes."""
from .api_jobs import jobs_bp
from .api_notifications import notifications_bp
from .api_scraping import scraping_bp
from .api_settings import settings_bp
from .api_gmail import gmail_bp
from .api_chat import chat_bp
from .api_es import es_bp
from .api_applications import applications_bp
from .api_mypage import mypage_bp
from .api_scheduler import scheduler_bp


def register_blueprints(app):
    """Register all API blueprints with the Flask app."""
    app.register_blueprint(jobs_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(scraping_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(gmail_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(es_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(mypage_bp)
    app.register_blueprint(scheduler_bp)
