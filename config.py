import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') or 'dev-secret-key-change-in-production'
    FIREBASE_WEB_API_KEY = os.environ.get('FIREBASE_WEB_API_KEY')
