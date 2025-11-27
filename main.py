import discord
from discord.ext import commands
from discord.ui import Button, View
import json
import os
import asyncio

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

# Itemy (BEZ počtu kusů)
ITEMS_LIST = [
    ("Baium ring", "💍"),
    ("Frintezza necklace", "📿"),
    ("Freya necklace", "❄️"),
    ("Ant queen ring", "👑"),
]

# Flag pro pending updates
update_pending = False

# Načtení dat
def load_loans():
    if os.path.exists(LOANS_FILE):
        try:
            with open(LOANS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {item[0]: [] for item in ITEMS_LIST}

# Uložení dat
def save_loans(loans):
    with open(LOANS_FILE, "w", encoding="utf-8") as f:
        json.dump(loans, f, ensure_ascii=False, indent=2)

# Načtení ID zpráv
def load_message_ids():
    if os.path.exists(MESSAGE_IDS_FILE):
        try:
            with open(MESSAGE_IDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"overview": None, "items": {}}

# Uložení ID zpráv
def save_message_ids(msg_ids):
    with open(MESSAGE_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(msg_ids, f, ensure_ascii=False, indent=2)

# Konverze user ID na jméno
async def get_user_name(guild, user_id):
    try:
        user = guild.get_member(int(user_id))
        if user:
            return user.display_name
        return f"Unknown({user_id})"
    except:
        return f"Unknown({user_id})"

# Vytvoření hlavního embed s přehledem
async def create_overview_embed(loans, guild):
    embed = discord.Embed(
        title="📦 CP Sdílené itemy k zapůjčení",
        description="Klikni na **[Půjčit]** nebo **[Vrátit]** u jednotlivých itemů",
        color=discord.Color.gold()
    )

    for item_name, emoji in ITEMS_LIST:
        borrowers = loans.get(item_name, [])
        if borrowers:
            names = []
            for uid in borrowers:
                name = await get_user_name(guild, uid)
                names.append(name)
            status = f"🔴 Má: {', '.join(names)}"
        else:
            status = f"🟢 Dostupný"

        embed.add_field(
            name=f"{emoji} {item_name}",
            value=status,
            inline=False
        )

    embed.set_footer(text="✅ Data se automaticky ukládají")
    return embed

# Vytvoření embed pro jednotlivý item
async def create_item_embed(item_name, emoji, borrowers, guild):
    if borrowers:
        names = []
        for uid in borrowers:
            name = await get_user_name(guild, uid)
            names.append(name)
        status = f"🔴 Má: {', '.join(names)}"
        color = discord.Color.red()
    else:
        status = f"🟢 Dostupný"
        color = discord.Color.green()

    embed = discord.Embed(
        title=f"{emoji} {item_name}",
        description=status,
        color=color
    )
    return embed

# View pro jednotlivý item
class ItemLoanView(View):
    def __init__(self, item_name):
        super().__init__(timeout=None)
        self.item_name = item_name

    @discord.ui.button(label="Půjčit", style=discord.ButtonStyle.green)
    async def borrow_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_loan(interaction, self.item_name, "borrow")

    @discord.ui.button(label="Vrátit", style=discord.ButtonStyle.danger)
    async def return_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await handle_loan(interaction, self.item_name, "return")

# Zpracování půjčky/vrácení
async def handle_loan(interaction: discord.Interaction, item: str, action: str):
    global update_pending

    # Kontrola role
    guild = interaction.guild
    role = discord.utils.get(guild.roles, name=ROLE_NAME)

    if not role or role not in interaction.user.roles:
        await interaction.response.send_message(
            f"❌ Nemáš roli **{ROLE_NAME}**!",
            ephemeral=True
        )
        return

    # Načtení dat
    loans = load_loans()
    user_id = str(interaction.user.id)
    current_borrowers = loans.get(item, [])

    # PŮJČIT
    if action == "borrow":
        if user_id in current_borrowers:
            await interaction.response.send_message(f"⚠️ Už máš **{item}** zapůjčený!", ephemeral=True)
            return

        # ✅ NOVÝ LIMIT: Pouze 1 osoba najednou!
        if len(current_borrowers) >= 1:
            borrower_name = await get_user_name(guild, current_borrowers[0])
            await interaction.response.send_message(
                f"❌ **{item}** už má **{borrower_name}**! Počkej, až ji vrátí.",
                ephemeral=True
            )
            return

        current_borrowers.append(user_id)
        loans[item] = current_borrowers
        message = f"✅ Vzal si si **{item}**! 🎮"

    # VRÁTIT
    else:
        if user_id not in current_borrowers:
            await interaction.response.send_message(f"❌ Nemáš **{item}** zapůjčený!", ephemeral=True)
            return

        current_borrowers.remove(user_id)
        loans[item] = current_borrowers
        message = f"✅ Vrátil si **{item}** do banky! 🙏"

    # Uložení
    save_loans(loans)
    await interaction.response.send_message(message, ephemeral=True)

    # Plánuj aktualizaci (ne okamžitě)
    if not update_pending:
        update_pending = True
        await asyncio.sleep(1)
        update_pending = False
        await update_all_messages()

# Aktualizace všech zpráv
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
                    borrowers = loans.get(item_name, [])
                    item_embed = await create_item_embed(item_name, emoji, borrowers, guild)
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
                borrowers = loans.get(item_name, [])
                item_embed = await create_item_embed(item_name, emoji, borrowers, guild)
                view = ItemLoanView(item_name)
                item_msg = await channel.send(embed=item_embed, view=view)
                msg_ids["items"][item_name] = str(item_msg.id)

        save_message_ids(msg_ids)

    except Exception as e:
        print(f"❌ Chyba při aktualizaci zpráv: {e}")

# Spuštění
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

token = os.getenv("DISCORD_TOKEN")
bot.run(token)
