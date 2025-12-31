"""
Railway / host entrypoint.

Run with: `python main.py` (Railway start command)

This file loads `.env` locally (ignored by git) and imports `bot` which starts the
Discord client. Keep secrets in environment variables on the host (Railway secrets).
"""
from dotenv import load_dotenv


def main():
    # Load local .env for development only
    load_dotenv()

    # Importing `bot` will execute the module-level startup (bot.run)
    import bot  # noqa: F401


if __name__ == "__main__":
    main()
