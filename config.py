import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD")
TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID")

