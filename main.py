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
    ("Ant queen ring", "👑"),
    ("Dynasty pole - Crit stun 150 WIND", "🦯"),
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
            # na novou: {item: [{"user_id": "...", "borrowed_at": int, "reminder_stage": 0}, ...]}
            migrated = False
            for item_name, _ in ITEMS_LIST:
                raw_list = data.get(item_name, [])
                new_list = []
                for entry in raw_list:
                    if isinstance(entry, str):
                        # starý formát – jen user_id
                        new_list.append(
                            {
                                "user_id": entry,
                                "borrowed_at": int(time.time()),
                                "reminder_stage": 0,
                            }
                        )
                        migrated = True
                    elif isinstance(entry, dict):
                        # nový formát – doplníme chybějící klíče, pokud něco chybí
                        user_id = str(entry.get("user_id"))
                        borrowed_at = int(entry.get("borrowed_at", int(time.time())))
                        reminder_stage = int(entry.get("reminder_stage", 0))
                        new_list.append(
                            {
                                "user_id": user_id,
                                "borrowed_at": borrowed_at,
                                "reminder_stage": reminder_stage,
                            }
                        )
                    else:
                        # neznámý formát – přeskočíme
                        continue
                data[item_name] = new_list

            # pokud v souboru chybí nějaký item z ITEMS_LIST, doplníme ho
            for item_name, _ in ITEMS_LIST:
                if item_name not in data:
                    data[item_name] = []

            # pokud soubor neobsahuje nic z ITEMS_LIST (nebo je broken), vrátíme prázdnou strukturu
            if not isinstance(data, dict):
                return _empty_loans_structure()

            if migrated:
                save_loans(data)

            return data
        except:
            pass

    return _empty_loans_structure()


def save_loans(loans):
    with open(LOANS_FILE, "w", encoding="utf-8") as f:
        json.dump(loans, f, ensure_ascii=False, indent=2)


def load_message_ids():
    if os.path.exists(MESSAGE_IDS_FILE):
        try:
            with open(MESSAGE_IDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"overview": None, "items": {}}


def save_message_ids(msg_ids):
    with open(MESSAGE_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(msg_ids, f, ensure_ascii=False, indent=2)


# -----------------------
# Pomocné funkce
# -----------------------

async def get_user_name(guild, user_id):
    try:
        member = guild.get_member(int(user_id))
        if member:
            return member.display_name
        return f"Unknown({user_id})"
    except:
        return f"Unknown({user_id})"


def find_loan_entry(loans, item_name, user_id):
    """Vrátí dict zápůjčky pro daný item a user_id nebo None."""
    entries = loans.get(item_name, [])
    for entry in entries:
        if entry.get("user_id") == user_id:
            return entry
    return None


def remove_loan_entry(loans, item_name, user_id):
    """Odstraní zápůjčku pro daný item a user_id."""
    entries = loans.get(item_name, [])
    new_entries = [e for e in entries if e.get("user_id") != user_id]
    loans[item_name] = new_entries


# -----------------------
# Embeds
# -----------------------

async def create_overview_embed(loans, guild):
    embed = discord.Embed(
        title="📦 CP Sdílené itemy k zapůjčení",
        description="Klikni na **[Půjčit]** nebo **[Vrátit]** u jednotlivých itemů",
        color=discord.Color.gold()
    )

    for item_name, emoji in ITEMS_LIST:
        borrowers_entries = loans.get(item_name, [])
        if borrowers_entries:
            names = []
            for entry in borrowers_entries:
                uid = entry.get("user_id")
                name = await get_user_name(guild, uid)
                names.append(name)
            status = f"🔴 Má: {', '.join(names)}"
        else:
            status = "🟢 Dostupný"

        embed.add_field(
            name=f"{emoji} {item_name}",
            value=status,
            inline=False
        )

    embed.set_footer(text="✅ Data se automaticky ukládají")
    return embed


async def create_item_embed(item_name, emoji, borrowers_entries, guild):
    if borrowers_entries:
        names = []
        for entry in borrowers_entries:
            uid = entry.get("user_id")
            name = await get_user_name(guild, uid)
            names.append(name)
        status = f"🔴 Má: {', '.join(names)}"
        color = discord.Color.red()
    else:
        status = "🟢 Dostupný"
        color = discord.Color.green()

    embed = discord.Embed(
        title=f"{emoji} {item_name}",
        description=status,
        color=color
    )
    return embed


# -----------------------
# View pro jednotlivý item
# -----------------------

class ItemLoanView(View):
    def __init__(self, item_name):
        super().__init__(timeout=None)
        self.item_name = item_name

    @discord.ui.button(label="Půjčit", style=discord.ButtonStyle.green, custom_id="borrow_btn")
    async def borrow_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_loan(interaction, self.item_name, "borrow")

    @discord.ui.button(label="Vrátit", style=discord.ButtonStyle.danger, custom_id="return_btn")
    async def return_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_loan(interaction, self.item_name, "return")


# -----------------------
# View pro DM připomínku
# -----------------------

class ReminderView(View):
    def __init__(self, item_name):
        super().__init__(timeout=None)
        self.item_name = item_name

    @discord.ui.button(label="Vrátit", style=discord.ButtonStyle.danger, custom_id="reminder_return_btn")
    async def return_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_loan(interaction, self.item_name, "return")

    @discord.ui.button(label="Stále mám", style=discord.ButtonStyle.secondary, custom_id="still_have_btn")
    async def still_have_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            f"👍 Díky za potvrzení, že **{self.item_name}** stále používáš.",
            ephemeral=True
        )


# -----------------------
# Zpracování půjčky/vrácení
# -----------------------

async def handle_loan(interaction: discord.Interaction, item: str, action: str):
    global update_pending

    guild = interaction.guild
    
    # ✅ OPRAVA: Pokud je interakce z DM (guild je None), nastavíme si ji
    if not guild:
        guild = bot.get_guild(SERVER_ID)
    
    if not guild:
        await interaction.response.send_message(
            "❌ Chyba: Nemůžu se připojit k serveru!",
            ephemeral=True
        )
        return

    role = discord.utils.get(guild.roles, name=ROLE_NAME)

    # Kontrola role
    if not role or role not in interaction.user.roles:
        await interaction.response.send_message(
            f"❌ Nemáš roli **{ROLE_NAME}**!",
            ephemeral=True
        )
        return

    loans = load_loans()
    user_id = str(interaction.user.id)
    current_entries = loans.get(item, [])

    # PŮJČIT
    if action == "borrow":
        # Uživatel už ten item má
        if any(e.get("user_id") == user_id for e in current_entries):
            await interaction.response.send_message(
                f"⚠️ Už máš **{item}** zapůjčený!",
                ephemeral=True
            )
            return

        # Limit: jen 1 osoba může mít item
        if len(current_entries) >= 1:
            borrower_name = await get_user_name(guild, current_entries[0].get("user_id"))
            await interaction.response.send_message(
                f"❌ **{item}** už má **{borrower_name}**! Počkej, až ji vrátí.",
                ephemeral=True
            )
            return

        # Přidáme nový záznam s časem a resetnutým reminder_stage
        new_entry = {
            "user_id": user_id,
            "borrowed_at": int(time.time()),
            "reminder_stage": 0
        }
        current_entries.append(new_entry)
        loans[item] = current_entries
        message = f"✅ Vzal sis **{item}**! 🎮"

    # VRÁTIT
    else:
        # Najdeme loan entry
        entry = find_loan_entry(loans, item, user_id)
        if not entry:
            await interaction.response.send_message(
                f"❌ Nemáš **{item}** zapůjčený!",
                ephemeral=True
            )
            return

        # Odstraníme zápůjčku
        remove_loan_entry(loans, item, user_id)
        message = f"✅ Vrátil jsi **{item}** do banky! 🙏"

    # Uložení
    save_loans(loans)
    await interaction.response.send_message(message, ephemeral=True)

    # Plánuj aktualizaci (ne okamžitě)
    if not update_pending:
        update_pending = True
        await asyncio.sleep(3)
        update_pending = False
        await update_all_messages()


# -----------------------
# Aktualizace zpráv
# -----------------------

async def update_all_messages():
    try:
        channel = bot.get_channel(CHANNEL_ID)
        guild = bot.get_guild(SERVER_ID)
        if not channel or not guild:
            return

        loans = load_loans()
        msg_ids = load_message_ids()

        # Aktualizace přehledu
        if msg_ids["overview"]:
            try:
                overview_msg = await channel.fetch_message(int(msg_ids["overview"]))
                overview_embed = await create_overview_embed(loans, guild)
                await overview_msg.edit(embed=overview_embed)
            except:
                msg_ids["overview"] = None

        # Aktualizace jednotlivých itemů
        for item_name, emoji in ITEMS_LIST:
            if item_name in msg_ids["items"]:
                try:
                    item_msg = await channel.fetch_message(int(msg_ids["items"][item_name]))
                    borrowers_entries = loans.get(item_name, [])
                    item_embed = await create_item_embed(item_name, emoji, borrowers_entries, guild)
                    view = ItemLoanView(item_name)
                    await item_msg.edit(embed=item_embed, view=view)
                except:
                    msg_ids["items"][item_name] = None

        # Pokud něco chybí, vytvoříme nové zprávy
        if not msg_ids["overview"]:
            overview_embed = await create_overview_embed(loans, guild)
            overview_msg = await channel.send(embed=overview_embed)
            msg_ids["overview"] = str(overview_msg.id)

        for item_name, emoji in ITEMS_LIST:
            if item_name not in msg_ids["items"] or not msg_ids["items"][item_name]:
                borrowers_entries = loans.get(item_name, [])
                item_embed = await create_item_embed(item_name, emoji, borrowers_entries, guild)
                view = ItemLoanView(item_name)
                item_msg = await channel.send(embed=item_embed, view=view)
                msg_ids["items"][item_name] = str(item_msg.id)

        save_message_ids(msg_ids)

    except Exception as e:
        print(f"❌ Chyba při aktualizaci zpráv: {e}")


# -----------------------
# Background reminder loop
# -----------------------

@tasks.loop(minutes=10)
async def reminder_loop():
    await bot.wait_until_ready()
    guild = bot.get_guild(SERVER_ID)
    channel = bot.get_channel(CHANNEL_ID)

    if not guild or not channel:
        return

    loans = load_loans()
    now = int(time.time())
    changed = False

    for item_name, _ in ITEMS_LIST:
        entries = loans.get(item_name, [])
        for entry in entries:
            user_id = entry.get("user_id")
            borrowed_at = int(entry.get("borrowed_at", now))
            stage = int(entry.get("reminder_stage", 0))
            elapsed = now - borrowed_at

            member = guild.get_member(int(user_id))
            if not member:
                continue

            # 6h – první DM s tlačítky
            if elapsed >= REMINDER_6H and stage < 1:
                try:
                    view = ReminderView(item_name)
                    await member.send(
                        f"Ahoj! Máš **{item_name}**, co jsi si půjčil/a. "
                        f"Můžeš si jej vrátit a nebo jej ještě potřebuješ?",
                        view=view
                    )
                    entry["reminder_stage"] = 1
                    changed = True
                except:
                    pass

            # 18h – druhé DM připomenutí
            if elapsed >= REMINDER_18H and stage < 2:
                try:
                    await member.send(
                        f"Upozornění: Máš půjčený **{item_name}** již 18 hodin! "
                        f"Nezapomněl/a jsi ho vrátit?"
                    )
                    entry["reminder_stage"] = 2
                    changed = True
                except:
                    pass

            # 48h – veřejný alert v kanálu
            if elapsed >= REMINDER_48H and stage < 3:
                try:
                    await channel.send(
                        f"🚨 **URGENTNÍ:** {member.mention}, vrať itemy! "
                        f"Všichni na serveru vidí, že máš **{item_name}** už dva dny "
                        f"a řádně je nevracíš! Ostatní si je chtějí taky půjčit."
                    )
                    entry["reminder_stage"] = 3
                    changed = True
                except:
                    pass

    if changed:
        save_loans(loans)


# -----------------------
# Spuštění
# -----------------------

@bot.event
async def on_ready():
    print(f"✅ Bot je online jako {bot.user}")
    guild = bot.get_guild(SERVER_ID)
    if guild:
        print(f"✅ Server: {guild.name}")
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            print(f"✅ Kanál: {channel.name}")
            await update_all_messages()
            print("✅ Systém připraven!")

    if not reminder_loop.is_running():
        reminder_loop.start()
        print("✅ Reminder loop spuštěn!")


token = os.getenv("DISCORD_TOKEN")
bot.run(token)
