import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import json

from src.scripts_soloq import (
    count_soloq,
    get_current_elo,
    format_players_report,
    build_player_rows,
    build_players_embed,
    hydrate_players_accounts,
)

# Load environment variables
load_dotenv()

# Create bot instance
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# APScheduler setup (Europe/Paris timezone)
paris_tz = pytz.timezone("Europe/Paris")
scheduler = AsyncIOScheduler(timezone=paris_tz)


async def send_daily_message():
    channel_id = int(os.getenv("CHANNEL_ID", "0"))
    channel = bot.get_channel(channel_id)

    # Load players JSON from env var 'players_json' (must be valid JSON string)
    players_json_text = os.getenv("players_json")
    if not players_json_text:
        print("players_json env var not set")
        return
    try:
        players_json = json.loads(players_json_text)
    except Exception as e:
        print("Invalid players_json:", e)
        return


    global_api_key = os.getenv("prod_api_key")


    rows = build_player_rows(players_json, global_api_key=global_api_key)

    # Build ASCII table message
    msg = format_players_report(rows)

    if channel:
        await channel.send(f"```{msg}```")
    else:
        print(f"Channel with ID {channel_id} not found.")


@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    # Start the scheduler only once — run daily at 11:00 Europe/Paris
    if not scheduler.running:
        scheduler.add_job(
            send_daily_message,
            CronTrigger(hour=11, minute=0),
            id="soloq_report",
            replace_existing=True,
        )
        scheduler.start()


@bot.command(name="send")
async def send_message(ctx, *, message):
    """Send a message to a specific channel"""
    channel_id = int(os.getenv("CHANNEL_ID", "0"))
    channel = bot.get_channel(channel_id)
    if channel:
        await channel.send(message)
        await ctx.send(f"Message sent to {channel.mention}")
    else:
        await ctx.send("Channel not found.")


# Run the bot
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("DISCORD_TOKEN not found in .env file")
