# Solo Q Bot Discord

A Discord bot that sends messages to a specific channel.

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create a `.env` file** with your Discord bot token and target channel ID:
   ```
   DISCORD_TOKEN=your_bot_token
   CHANNEL_ID=your_channel_id
   ```

3. **Run the bot:**
   ```bash
   python bot.py
   ```

## Railway deployment

Railway will build and run your project; use the included `Procfile` (or set the start command to `python main.py`).

If you see an `audioop` error at runtime, the host image may lack Python's audio extension used by voice/audio parts of some Discord libraries — ask Railway to use a Debian-based Python runtime or contact me and I can provide a small alternative build script.

## Features

- Connects to Discord and announces when ready
- Sends messages to a specific channel on startup
- `!send <message>` command to send messages to the target channel

## Getting Your Bot Token

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" and click "Add Bot"
4. Copy the token and add it to `.env`

## Getting Your Channel ID

1. Enable Developer Mode in Discord (User Settings > Advanced > Developer Mode)
2. Right-click on a channel and select "Copy Channel ID"
3. Add it to `.env`
