"""API routes for Notifications."""
from flask import Blueprint, jsonify
from database import (
    get_all_notifications, get_unread_notifications,
    mark_notification_read, mark_all_notifications_read,
)

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/api/notifications', methods=['GET'])
def api_get_notifications():
    notifications = get_all_notifications()
    return jsonify(notifications)


@notifications_bp.route('/api/notifications/unread', methods=['GET'])
def api_get_unread():
    notifications = get_unread_notifications()
    return jsonify(notifications)


@notifications_bp.route('/api/notifications/<int:nid>/read', methods=['POST'])
def api_mark_read(nid):
    mark_notification_read(nid)
    return jsonify({'message': 'Marked as read'})


@notifications_bp.route('/api/notifications/read-all', methods=['POST'])
def api_mark_all_read():
    mark_all_notifications_read()
    return jsonify({'message': 'All marked as read'})
