import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = os.getenv("ADMIN_ID", 123456789)  # Саша's ID

USER_LIST = [
    "lemme_nap",
    "NakaiAgni",
    "Kir_Borisov",
    "Ivan_Chg",
    "Roman_Plkv",
    "zeret_mara",
    "grafkin"
]

POINTS = {
    "contract": 2000,
    "integration": 1000
}

DATA_DIR = "data"
CURRENT_STAT_FILE = f"{DATA_DIR}/current_stat.json"
ALL_STAT_FILE = f"{DATA_DIR}/all_stat.json"
USERS_STATE_FILE = f"{DATA_DIR}/users_state.json"
REQUESTS_FILE = f"{DATA_DIR}/requests.json"
DUPLICATES_FILE = f"{DATA_DIR}/duplicates.json"

os.makedirs(DATA_DIR, exist_ok=True)
