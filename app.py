import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import json
import asyncio

# =========================
# LOAD ENV
# =========================
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
ALLOWED_GUILD_ID = int(os.getenv("ALLOWED_GUILD_ID"))

if LOG_CHANNEL_ID:
    LOG_CHANNEL_ID = int(LOG_CHANNEL_ID)
else:
    LOG_CHANNEL_ID = None

# =========================
# PERSISTENT DATABASE
# =========================
DB_FILE = "vip_database.json"

def load_vip_data():
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            # Convert expire strings back to datetime
            for uid, info in data.items():
                if "expire" in info:
                    info["expire"] = datetime.fromisoformat(info["expire"])
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_vip_data(data):
    # Convert datetime to string for JSON
    save_data = {}
    for uid, info in data.items():
        save_data[uid] = info.copy()
        if "expire" in save_data[uid]:
            save_data[uid]["expire"] = save_data[uid]["expire"].isoformat()
    with open(DB_FILE, "w") as f:
        json.dump(save_data, f, indent=4)

vip_users = load_vip_data()

# =========================
# BOT INTENTS
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# =========================
# BOT SETUP
# =========================
bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================
# BOT READY EVENT
# =========================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user.name}")
    print(f"✅ Bot ID: {bot.user.id}")
    print(f"✅ Guild ID: {ALLOWED_GUILD_ID}")
    print(f"✅ Log Channel: {LOG_CHANNEL_ID if LOG_CHANNEL_ID else 'Not Set'}")
    
    # Clean expired VIPs on startup
    await cleanup_expired_vips(notify=False)
    
    print(f"✅ Loaded {len(vip_users)} active VIP records")
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")
    
    # Start cleanup task
    bot.loop.create_task(auto_cleanup())

# =========================
# AUTO CLEANUP EXPIRED VIPs
# =========================
async def cleanup_expired_vips(notify=True):
    """Remove expired VIPs from database"""
    changed = False
    current_time = datetime.now()
    expired_list = []
    
    for uid, data in list(vip_users.items()):
        if data["expire"] < current_time:
            expired_list.append(uid)
            del vip_users[uid]
            changed = True
            print(f"🗑️ Removed expired VIP: {uid}")
    
    if changed:
        save_vip_data(vip_users)
        # Send log if any expired
        if notify and LOG_CHANNEL_ID:
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                embed = discord.Embed(
                    title="🔄 VIP CLEANUP",
                    description=f"Removed {len(expired_list)} expired VIP entries.",
                    color=0xFFA500
                )
                embed.add_field(
                    name="🗑️ REMOVED UIDs",
                    value="\n".join(expired_list[:10]) if expired_list else "None",
                    inline=False
                )
                await channel.send(embed=embed)
    
    return len(expired_list)

async def auto_cleanup():
    """Background task to cleanup expired VIPs"""
    while True:
        await asyncio.sleep(3600)  # Check every hour
        await cleanup_expired_vips(notify=True)

# =========================
# SAFE LOG FUNCTION
# =========================
async def send_log(embed):
    if not LOG_CHANNEL_ID:
        return

    channel = bot.get_channel(LOG_CHANNEL_ID)

    if channel:
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            print("❌ Bot has no permission to send messages in log channel")
        except Exception as e:
            print(f"❌ Log error: {e}")

# =========================
# GUILD CHECK FUNCTION
# =========================
async def guild_check(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Server only command.",
            ephemeral=True
        )
        return False

    if interaction.guild.id != ALLOWED_GUILD_ID:
        await interaction.response.send_message(
            "❌ This bot is not authorized for this server.",
            ephemeral=True
        )
        return False

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Admin permission required.",
            ephemeral=True
        )
        return False

    return True

# =========================
# CHECK UID EXISTS FUNCTION
# =========================
def check_uid_exists(uid):
    """Check if UID exists and is not expired"""
    if uid not in vip_users:
        return False, None
    
    data = vip_users[uid]
    if data["expire"] < datetime.now():
        # Remove expired UID if found
        del vip_users[uid]
        save_vip_data(vip_users)
        return False, None
    
    return True, data

def get_uid_info(uid):
    """Get UID information if exists"""
    return vip_users.get(uid)

# =========================
# OWNER COMMAND
# =========================
@bot.tree.command(
    name="owner",
    description="Premium Access"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    user="Select User",
    uid="Enter UID",
    days="Enter Active Days"
)
async def owner(interaction: discord.Interaction, user: discord.Member, uid: str, days: int):

    if not await guild_check(interaction):
        return

    # Check if UID already exists and is active
    exists, data = check_uid_exists(uid)
    
    if exists:
        existing_expire = data["expire"].strftime("%d-%m-%Y %H:%M")
        
        embed = discord.Embed(
            title="⚠️ UID ALREADY EXISTS",
            description=f"UID `{uid}` is already registered and active.",
            color=0xFFA500
        )
        embed.add_field(
            name="📋 CURRENT STATUS",
            value=f"👤 User: <@{data['user']}>\n📅 Days: {data['days']} days\n⏰ Expires: {existing_expire}",
            inline=False
        )
        embed.add_field(
            name="💡 SUGGESTION",
            value="Use `/extend` to add more days or `/remove` to delete this UID first.",
            inline=False
        )
        embed.set_footer(text="AXB PREMIUM SECURITY")
        
        await interaction.response.send_message(embed=embed)
        return

    expire_date = datetime.now() + timedelta(days=days)
    formatted_expire = expire_date.strftime("%d-%m-%Y %H:%M")

    vip_users[uid] = {
        "user": user.id,
        "days": days,
        "expire": expire_date
    }
    save_vip_data(vip_users)

    embed = discord.Embed(
        title="💎 UID ACTIVATED",
        description="AXB COMMENTY",
        color=0x8a2be2
    )

    embed.set_thumbnail(url=user.display_avatar.url)

    embed.add_field(name="🆔 UID", value=f"{uid}", inline=True)
    embed.add_field(name="🟢 STATUS", value="ACTIVE", inline=True)
    embed.add_field(name="👑 ACCESS", value="PREMIUM", inline=True)

    embed.add_field(name="👤 USER", value=user.mention, inline=True)
    embed.add_field(name="📅 ACTIVE DAYS", value=f"{days} DAYS", inline=True)
    embed.add_field(name="⏰ EXPIRES ON", value=formatted_expire, inline=True)

    embed.set_footer(text="AXB PREMIUM SECURITY")

    await interaction.response.send_message(embed=embed)
    await send_log(embed)

# =========================
# UID ADD COMMAND
# =========================
@bot.tree.command(
    name="uid_add",
    description="Add UID For 1 Day"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(uid="Enter UID")
async def uid_add(interaction: discord.Interaction, uid: str):

    if not await guild_check(interaction):
        return

    # Check if UID already exists and is active
    exists, data = check_uid_exists(uid)
    
    if exists:
        existing_expire = data["expire"].strftime("%d-%m-%Y %H:%M")
        
        embed = discord.Embed(
            title="⚠️ UID ALREADY EXISTS",
            description=f"UID `{uid}` is already registered and active.",
            color=0xFFA500
        )
        embed.add_field(
            name="📋 CURRENT STATUS",
            value=f"👤 User: {data['user']}\n📅 Days: {data['days']} days\n⏰ Expires: {existing_expire}",
            inline=False
        )
        embed.add_field(
            name="💡 SUGGESTION",
            value="Use `/extend` to add more days or `/remove` to delete this UID first.",
            inline=False
        )
        embed.set_footer(text="AXB PREMIUM SECURITY")
        
        await interaction.response.send_message(embed=embed)
        return

    expire_date = datetime.now() + timedelta(days=1)
    formatted_expire = expire_date.strftime("%d-%m-%Y %H:%M")

    vip_users[uid] = {
        "user": "AXB",
        "days": 1,
        "expire": expire_date
    }
    save_vip_data(vip_users)

    embed = discord.Embed(
        title="✅ UID ACTIVATED",
        description="AXB COMMENTY",
        color=0x8a2be2
    )

    embed.set_thumbnail(url=bot.user.display_avatar.url)

    embed.add_field(name="🆔 UID", value=f"{uid}", inline=True)
    embed.add_field(name="🟢 STATUS", value="ACTIVE", inline=True)
    embed.add_field(name="👑 ACCESS", value="PREMIUM", inline=True)

    embed.add_field(name="👤 USER", value="AXB", inline=True)
    embed.add_field(name="📅 ACTIVE DAYS", value="1 DAY", inline=True)
    embed.add_field(name="⏰ EXPIRES ON", value=formatted_expire, inline=True)

    embed.set_footer(text="AXB PREMIUM SECURITY")

    await interaction.response.send_message(embed=embed)
    await send_log(embed)

# =========================
# EXTEND VIP COMMAND
# =========================
@bot.tree.command(
    name="extend",
    description="Extend  UID DAY"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    uid="Enter UID to extend",
    days="Number of days to add"
)
async def extend(interaction: discord.Interaction, uid: str, days: int):

    if not await guild_check(interaction):
        return

    # Check if UID exists and is active
    exists, data = check_uid_exists(uid)
    
    if not exists:
        embed = discord.Embed(
            title="❌ UID NOT FOUND OR EXPIRED",
            description=f"UID `{uid}` is not registered or has already expired.\n\n💡 Use `/owner` or `/uid_add` to add a new VIP.",
            color=0xFF0000
        )
        await interaction.response.send_message(embed=embed)
        return

    # Extend the expiration
    new_expire = data["expire"] + timedelta(days=days)
    total_days = data["days"] + days

    # Update the data
    vip_users[uid]["expire"] = new_expire
    vip_users[uid]["days"] = total_days
    save_vip_data(vip_users)

    embed = discord.Embed(
        title="⏰ UID DAY EXTENDED",
        description=f" UID `{uid}` has been extended successfully.",
        color=0x00FF00
    )

    user_display = f"<@{vip_users[uid]['user']}>" if isinstance(vip_users[uid]['user'], int) else vip_users[uid]['user']
    
    embed.add_field(name="👤 USER", value=user_display, inline=True)
    embed.add_field(name="📅 TOTAL DAYS", value=f"{total_days} DAYS", inline=True)
    embed.add_field(
        name="📅 NEW EXPIRY",
        value=new_expire.strftime("%d-%m-%Y %H:%M"),
        inline=True
    )
    embed.add_field(
        name="📊 DAYS ADDED",
        value=f"+{days} days",
        inline=True
    )

    embed.set_footer(text="AXB PREMIUM SECURITY")

    await interaction.response.send_message(embed=embed)
    await send_log(embed)

# =========================
# STATUS COMMAND
# =========================
@bot.tree.command(
    name="status",
    description="Check UID Status"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(uid="Enter UID")
async def status(interaction: discord.Interaction, uid: str):

    if not await guild_check(interaction):
        return

    # Check if UID exists and is active
    exists, data = check_uid_exists(uid)
    
    if not exists:
        embed = discord.Embed(
            title="❌ UID NOT FOUND OR EXPIRED",
            description=f"UID `{uid}` is not registered or has expired.\n\n💡 Use `/owner` or `/uid_add` to add a new VIP.",
            color=0xFF0000
        )
        await interaction.response.send_message(embed=embed)
        return

    # Calculate remaining days
    remaining = (data["expire"] - datetime.now()).days
    remaining_text = f"{remaining} days left"
    
    embed = discord.Embed(
        title="🔍 UID STATUS",
        description="UID Status Information",
        color=0x8a2be2
    )

    embed.set_thumbnail(url=bot.user.display_avatar.url)

    embed.add_field(name="🆔 UID", value=f"{uid}", inline=True)
    embed.add_field(name="🟢 STATUS", value="ACTIVE ✅", inline=True)
    embed.add_field(name="👑 ACCESS", value="PREMIUM", inline=True)

    # User info
    user_display = f"<@{data['user']}>" if isinstance(data['user'], int) else data['user']
    embed.add_field(name="👤 USER", value=user_display, inline=True)
    embed.add_field(name="📅 TOTAL DAYS", value=f"{data['days']} DAYS", inline=True)
    embed.add_field(
        name="⏰ EXPIRES ON",
        value=data["expire"].strftime("%d-%m-%Y %H:%M"),
        inline=True
    )
    embed.add_field(
        name="📊 REMAINING",
        value=remaining_text,
        inline=False
    )

    embed.set_footer(text="AXB PREMIUM SECURITY")

    await interaction.response.send_message(embed=embed)

# =========================
# REMOVE COMMAND
# =========================
@bot.tree.command(
    name="remove",
    description="Remove UID"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(uid="Enter UID to remove")
async def remove(interaction: discord.Interaction, uid: str):

    if not await guild_check(interaction):
        return

    # Check if UID exists
    exists, data = check_uid_exists(uid)
    
    if not exists:
        # Check if UID is in database but expired (already removed by cleanup)
        embed = discord.Embed(
            title="❌ UID NOT FOUND",
            description=f"UID `{uid}` is not in the system or has already been removed.",
            color=0xFFA500
        )
        await interaction.response.send_message(embed=embed)
        return

    user_display = f"<@{data['user']}>" if isinstance(data['user'], int) else data['user']
    
    # Remove the UID
    del vip_users[uid]
    save_vip_data(vip_users)

    embed = discord.Embed(
        title="🗑️ UID REMOVED",
        description=f"UID `{uid}` has been removed successfully.",
        color=0x00FF00
    )
    
    embed.add_field(
        name="📋 REMOVED INFO",
        value=f"👤 User: {user_display}\n📅 Had {data['days']} days",
        inline=False
    )

    embed.set_footer(text="AXB PREMIUM SECURITY")

    await interaction.response.send_message(embed=embed)
    await send_log(embed)

# =========================
# LIST ALL VIPs COMMAND
# =========================
@bot.tree.command(
    name="list_vips",
    description="List all active VIP users"
)
@app_commands.default_permissions(administrator=True)
async def list_vips(interaction: discord.Interaction):

    if not await guild_check(interaction):
        return

    if not vip_users:
        embed = discord.Embed(
            title="📋 VIP LIST",
            description="No active VIP users registered.",
            color=0xFFA500
        )
        await interaction.response.send_message(embed=embed)
        return

    current_time = datetime.now()
    
    embed = discord.Embed(
        title="📋 VIP LIST",
        description=f"Total Active VIPs: {len(vip_users)}",
        color=0x8a2be2
    )

    vip_list = ""
    for uid, data in list(vip_users.items())[:10]:  # Show first 10
        user_display = f"<@{data['user']}>" if isinstance(data['user'], int) else data['user']
        remaining = (data["expire"] - current_time).days
        vip_list += f"🆔 `{uid}` | 👤 {user_display} | ⏰ {remaining}d left\n"
    
    if len(vip_users) > 10:
        vip_list += f"\n... and {len(vip_users) - 10} more VIPs"

    embed.add_field(name="✅ ACTIVE VIPs", value=vip_list, inline=False)
    embed.set_footer(text=f"Showing {min(len(vip_users), 10)} of {len(vip_users)} VIPs")

    await interaction.response.send_message(embed=embed)

# =========================
# SEARCH VIP COMMAND
# =========================
@bot.tree.command(
    name="search",
    description="Search for a VIP by UID or User"
)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    query="UID or Username to search"
)
async def search(interaction: discord.Interaction, query: str):

    if not await guild_check(interaction):
        return

    results = []
    query_lower = query.lower()
    
    for uid, data in vip_users.items():
        if query_lower in uid.lower():
            results.append((uid, data))
        elif isinstance(data['user'], int):
            try:
                user = await bot.fetch_user(data['user'])
                if query_lower in user.name.lower():
                    results.append((uid, data))
            except:
                pass

    if not results:
        embed = discord.Embed(
            title="🔍 SEARCH RESULTS",
            description=f"No active VIPs found for `{query}`",
            color=0xFFA500
        )
        await interaction.response.send_message(embed=embed)
        return

    embed = discord.Embed(
        title="🔍 SEARCH RESULTS",
        description=f"Found {len(results)} active VIP(s) for `{query}`",
        color=0x8a2be2
    )

    for uid, data in results[:10]:
        user_display = f"<@{data['user']}>" if isinstance(data['user'], int) else data['user']
        remaining = (data["expire"] - datetime.now()).days
        embed.add_field(
            name=f"🆔 {uid}",
            value=f"👤 {user_display}\n📅 {data['days']} days\n⏰ {remaining}d left",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

# =========================
# HELP COMMAND
# =========================
@bot.tree.command(
    name="help",
    description="Show all available commands"
)
async def help_command(interaction: discord.Interaction):
    
    embed = discord.Embed(
        title="🤖 BOT COMMANDS",
        description="Here are all available commands:",
        color=0x8a2be2
    )

    commands_list = {
        "/owner": "Add VIP with custom days (User, UID, Days)",
        "/uid_add": "Add VIP for 1 day (UID only)",
        "/extend": "Extend VIP days (adds to existing)",
        "/status": "Check UID status with remaining days",
        "/remove": "Remove VIP access",
        "/list_vips": "Show all active VIPs",
        "/search": "Search VIP by UID or Username",
        "/help": "Show this help menu"
    }

    for cmd, desc in commands_list.items():
        embed.add_field(name=cmd, value=desc, inline=False)

    embed.set_footer(text="AXB PREMIUM SECURITY | Admin Only")

    await interaction.response.send_message(embed=embed)

# =========================
# RUN BOT
# =========================
if __name__ == "__main__":
    bot.run(TOKEN)
