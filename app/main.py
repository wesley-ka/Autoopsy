import uvicorn
from fastapi import FastAPI, Request, Response, status
from contextlib import asynccontextmanager
import threading
import logging
from apscheduler.schedulers.background import BackgroundScheduler
import telebot

from app import config
from app.bot import bot, send_daily_report

logger = logging.getLogger("Main")

# Setup APScheduler
scheduler = BackgroundScheduler()

def setup_scheduler():
    """
    Parses DAILY_REPORT_TIME (HH:MM) and configures the cron task.
    """
    time_str = config.DAILY_REPORT_TIME
    try:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1])
    except Exception as e:
        logger.error(f"Error parsing DAILY_REPORT_TIME '{time_str}': {e}. Defaulting to 09:00.")
        hour, minute = 9, 0

    scheduler.add_job(
        send_daily_report,
        'cron',
        hour=hour,
        minute=minute,
        id="daily_metrics_report",
        replace_existing=True
    )
    scheduler.start()
    logger.info(f"Background scheduler started. Daily report configured for {hour:02d}:{minute:02d}.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP HANDLER ---
    logger.info("Starting Ops-Agent service...")
    
    # 1. Setup daily metrics report scheduler
    setup_scheduler()
    
    # 2. Register Telegram Bot commands menu dynamically
    logger.info("Registering Bot commands menu with Telegram...")
    try:
        bot.set_my_commands([
            telebot.types.BotCommand("status", "Check Render backend & Cloudflare frontend status"),
            telebot.types.BotCommand("debug", "Fetch live logs and run LLM SRE diagnostics"),
            telebot.types.BotCommand("fix", "Run self-correcting fix sandbox and create a PR"),
            telebot.types.BotCommand("logs", "Fetch recent raw backend container logs"),
            telebot.types.BotCommand("frontend", "Fetch frontend build stages & reachability"),
            telebot.types.BotCommand("clear", "Reset conversational history context"),
            telebot.types.BotCommand("help", "Get commands help and setup guide")
        ])
        logger.info("Bot commands registered successfully.")
    except Exception as e:
        logger.error(f"Failed to register Bot commands: {e}")
        
    # 3. Setup Telegram Bot communication mode
    if config.WEBHOOK_URL:
        # Webhook Mode
        webhook_path = "/webhook"
        full_webhook_url = f"{config.WEBHOOK_URL.rstrip('/')}{webhook_path}"
        logger.info(f"Configuring Telegram Webhook. Registering URL: {full_webhook_url}")
        try:
            bot.remove_webhook()
            # Set webhook. We can add a secret token for security if desired
            bot.set_webhook(url=full_webhook_url)
            logger.info("Telegram Webhook set successfully.")
        except Exception as e:
            logger.critical(f"Failed to set Telegram Webhook: {e}")
    else:
        # Long Polling Mode (for local development)
        logger.info("WEBHOOK_URL is not set. Launching Telegram Bot in Long Polling mode...")
        polling_thread = threading.Thread(
            target=lambda: bot.infinity_polling(skip_pending=True),
            daemon=True,
            name="TelegramBotPolling"
        )
        polling_thread.start()
        logger.info("Long Polling background thread started.")
        
    yield
    
    # --- SHUTDOWN HANDLER ---
    logger.info("Stopping Ops-Agent service...")
    
    # 1. Stop scheduler
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Background scheduler shut down.")
        
    # 2. Cleanup webhook if registered
    if config.WEBHOOK_URL:
        try:
            bot.remove_webhook()
            logger.info("Telegram Webhook removed.")
        except Exception as e:
            logger.error(f"Error removing Telegram Webhook: {e}")

# Initialize FastAPI App
app = FastAPI(
    title="Ops-Agent",
    description="SRE DevSecOps Agent Webhook and Health Endpoint",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/", status_code=status.HTTP_200_OK)
def read_root():
    return {
        "status": "online",
        "service": "Ops-Agent SRE Bot",
        "webhook_configured": bool(config.WEBHOOK_URL)
    }

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """
    Standard health check endpoint for monitoring/deployment tools like Render.
    """
    return {
        "status": "healthy",
        "scheduler_running": scheduler.running
    }

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """
    Webhook receiver endpoint for Telegram updates.
    """
    if not config.WEBHOOK_URL:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
        
    try:
        json_data = await request.json()
        update = telebot.types.Update.de_json(json_data)
        if update:
            bot.process_new_updates([update])
        return Response(status_code=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error processing update in webhook: {e}")
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

if __name__ == "__main__":
    logger.info(f"Launching Uvicorn server on {config.HOST}:{config.PORT}...")
    uvicorn.run(
        "app.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False  # Disabled reload in production context
    )
