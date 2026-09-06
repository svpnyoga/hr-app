import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "hr.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
SECRET_KEY = os.environ.get("HR_SECRET_KEY", "dev-secret-change-me-in-production-hr9k2")
SESSION_COOKIE_NAME = "hr_session"
PERMANENT_SESSION_LIFETIME_MIN = 480  # 8 hours
