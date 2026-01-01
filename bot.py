import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import json
import logging
import traceback

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

# Basic logging so Railway captures output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def send_daily_message():
    logger.info("send_daily_message: starting")
    try:
        channel_id = int(os.getenv("CHANNEL_ID", "0"))
        # Try cache first, then fetch if missing
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                channel = None

        # Load players JSON from env var 'players_json' (must be valid JSON string)
        players_json_text = os.getenv("players_json")
        if not players_json_text:
            logger.info("players_json env var not set")
            return
        try:
            players_json = json.loads(players_json_text)
        except Exception as e:
            logger.exception("Invalid players_json")
            return

        global_api_key = os.getenv("prod_api_key")

        rows = build_player_rows(players_json, global_api_key=global_api_key)

        # Build ASCII table message
        msg = format_players_report(rows)

        if channel:
            await channel.send(f"```{msg}```")
            logger.info("send_daily_message: message sent")
        else:
            logger.warning(f"Channel with ID {channel_id} not found.")
    except Exception:
        logger.exception("Unhandled exception in send_daily_message")


@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")
    # Start the scheduler only once — run daily at 11:00 Europe/Paris
    if not scheduler.running:
        scheduler.add_job(
            send_daily_message,
            CronTrigger(hour=12, minute=5, timezone=paris_tz),
            # CronTrigger(minute="*/2"),
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


@bot.group(name="todos", invoke_without_command=True)
async def todos(ctx):
    """List current todos when called without a subcommand."""
    todos_path = os.path.join("data", "todos.json")
    try:
        with open(todos_path, "r", encoding="utf-8") as f:
            items = json.load(f)
    except Exception:
        items = []

    if not items:
        await ctx.send("No todos yet. Add one with `!todos add <item>`")
        return

    lines = [f"{i+1}. {it}" for i, it in enumerate(items)]
    # Discord messages have length limits; join safely.
    await ctx.send("\n".join(lines))


@todos.command(name="add")
async def todos_add(ctx, *, item: str):
    """Add a todo item: !todos add Buy milk"""
    todos_path = os.path.join("data", "todos.json")
    try:
        with open(todos_path, "r", encoding="utf-8") as f:
            items = json.load(f)
    except Exception:
        items = []

    items.append(item)
    os.makedirs(os.path.dirname(todos_path), exist_ok=True)
    with open(todos_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    await ctx.send(f"Added todo #{len(items)}: {item}")


@todos.command(name="remove")
async def todos_remove(ctx, index: int):
    """Remove a todo by 1-based index: !todos remove 2"""
    todos_path = os.path.join("data", "todos.json")
    try:
        with open(todos_path, "r", encoding="utf-8") as f:
            items = json.load(f)
    except Exception:
        await ctx.send("No todos to remove.")
        return

    if index < 1 or index > len(items):
        await ctx.send("Invalid index.")
        return

    removed = items.pop(index - 1)
    with open(todos_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    await ctx.send(f"Removed todo #{index}: {removed}")


@bot.event
async def on_command_error(ctx, error):
    """Provide a friendly message for unknown commands and log others."""
    from discord.ext.commands import CommandNotFound

    if isinstance(error, CommandNotFound):
        await ctx.send("Command not found. Try `!help` or check command spelling.")
        return

    # For other errors, re-raise so they appear in logs (and optionally get handled elsewhere)
    raise error


@bot.command(name="run_daily")
async def run_daily(ctx):
    """Manually trigger the daily report (for testing)."""
    await ctx.send("Triggering daily report...")
    try:
        await send_daily_message()
        await ctx.send("Triggered.")
    except Exception as e:
        await ctx.send(f"Error triggering daily report: {e}")


# Run the bot
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("DISCORD_TOKEN not found in .env file")
