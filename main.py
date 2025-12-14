import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
import json
import os
import asyncio
import time

# Setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Konfigurace
SERVER_ID = 1397286059406000249
CHANNEL_ID = 1443362011957170216
ROLE_NAME = "Člen"
LOANS_FILE = "loans.json"
MESSAGE_IDS_FILE = "message_ids.json"

# Časové intervaly v sekundách
REMINDER_6H = 6 * 60 * 60
REMINDER_18H = 18 * 60 * 60
REMINDER_48H = 48 * 60 * 60

# Itemy (BEZ počtu kusů)
ITEMS_LIST = [
    ("Baium ring", "💍"),
    ("Frintezza necklace", "📿"),
    ("Freya necklace", "❄️"),
    ("Ant queen ring", "👑"),
]

# Flag pro pending updates
update_pending = False


# -----------------------
# Načtení/Uložení dat
# -----------------------

def _empty_loans_structure():
    # pro každý item prázdný list zápůjček
    return {item[0]: [] for item in ITEMS_LIST}


def load_loans():
    if os.path.exists(LOANS_FILE):
        try:
            with open(LOANS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Migrace staré struktury: {item: ["user_id", ...]}
            # na
