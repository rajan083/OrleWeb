import os
import sys
from dotenv import load_dotenv

load_dotenv()

class Config:
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
    IS_PRODUCTION = FLASK_ENV == 'production'

    SECRET_KEY = os.environ.get('SECRET_KEY')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///orle.db')
    if SQLALCHEMY_DATABASE_URI.startswith('postgres://'):  # NEW
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False    
    
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_USERNAME')

    RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID')
    RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET')
    RAZORPAY_WEBHOOK_SECRET = os.environ.get('RAZORPAY_WEBHOOK_SECRET')
    SENTRY_DSN = os.environ.get('SENTRY_DSN')
    REDIS_URL = os.environ.get('REDIS_URL')  # NEW

    # Cookie / session hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = IS_PRODUCTION  # requires HTTPS in production
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = IS_PRODUCTION

    @staticmethod
    def validate():
        """Fail loudly at startup instead of silently running with unsafe defaults."""
        required_in_production = {
            'SECRET_KEY': Config.SECRET_KEY,
            'JWT_SECRET_KEY': Config.JWT_SECRET_KEY,
            'MAIL_USERNAME': Config.MAIL_USERNAME,
            'MAIL_PASSWORD': Config.MAIL_PASSWORD,
            'RAZORPAY_KEY_ID': Config.RAZORPAY_KEY_ID,
            'RAZORPAY_KEY_SECRET': Config.RAZORPAY_KEY_SECRET,
            'RAZORPAY_WEBHOOK_SECRET': Config.RAZORPAY_WEBHOOK_SECRET,
            'SENTRY_DSN': Config.SENTRY_DSN,
            'REDIS_URL': Config.REDIS_URL,

        }

        if Config.IS_PRODUCTION:
            missing = [name for name, value in required_in_production.items() if not value]
            if missing:
                sys.exit(f"FATAL: missing required environment variables in production: {', '.join(missing)}")

            if Config.SQLALCHEMY_DATABASE_URI.startswith('sqlite'):
                sys.exit("FATAL: refusing to run in production with a SQLite database. Set DATABASE_URL to Postgres/MySQL.")
        else:
            # Dev-only fallbacks so local setup still works without a full .env
            if not Config.SECRET_KEY:
                Config.SECRET_KEY = 'dev-only-insecure-key'
            if not Config.JWT_SECRET_KEY:
                Config.JWT_SECRET_KEY = 'dev-only-insecure-jwt-key'