import os
import sys
import logging
from dotenv import load_dotenv

# Load env variables from .env file
load_dotenv()

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AutoopsyConfig")

# Core Environment Variables Checklist (Always required)
REQUIRED_CORE_ENV_VARS = [
    "TELEGRAM_BOT_TOKEN",
    "GITHUB_PAT",
    "LLM_API_KEY"
]

TEMPLATE_ENV_CONTENT = """# Autoopsy Environment Configurations

# 1. Telegram Configurations
TELEGRAM_BOT_TOKEN=
# Optional: Public Webhook URL (if omitted, bot uses Long Polling mode for local testing)
# WEBHOOK_URL=https://your-domain.render.com/webhook
# Optional: Target Chat ID for scheduled reports. Will be auto-saved if not set.
TELEGRAM_CHAT_ID=
# Optional: Comma-separated list of allowed Telegram user IDs (e.g. 12345678,98765432).
# If set, only these users can message/run commands on the bot.
ALLOWED_TELEGRAM_USER_IDS=

# 2. Shared GitHub Configurations
GITHUB_PAT=

# 3. Backend Target (Render + GitHub Backend Repo)
# To disable backend monitoring, leave TARGET_RENDER_SERVICE_ID empty.
RENDER_API_KEY=
TARGET_RENDER_SERVICE_ID=
# Optional: Render Owner/Workspace ID (will be fetched automatically if omitted)
RENDER_OWNER_ID=
BACKEND_GITHUB_REPO=owner/backend-repo
BACKEND_GITHUB_BRANCH=main

# 4. Frontend Target (Cloudflare Pages + GitHub Frontend Repo)
# To disable frontend monitoring, leave CLOUDFLARE_PROJECT_NAME empty.
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_PROJECT_NAME=
FRONTEND_GITHUB_REPO=owner/frontend-repo
FRONTEND_GITHUB_BRANCH=main

# 5. LLM Provider Configurations (supports "openai" compatible or "gemini")
LLM_PROVIDER=openai
LLM_API_KEY=
# Leave blank if using default OpenAI. Populate if using DeepInfra, Fireworks, etc.
# Examples: 
# DeepInfra: https://api.deepinfra.com/v1
# Fireworks: https://api.fireworks.ai/inference/v1
LLM_BASE_URL=https://api.deepinfra.com/v1

# Models configurations
# Diagnostic: Meta-Llama-3.1-8B-Instruct or gpt-4o-mini
LLM_MODEL_DIAGNOSTIC=meta-llama/Meta-Llama-3.1-8B-Instruct
# Coder: Meta-Llama-3.1-70B-Instruct or gpt-4o
LLM_MODEL_CODER=meta-llama/Meta-Llama-3.1-70B-Instruct

# 6. Service Configurations
PORT=8000
HOST=0.0.0.0
DAILY_REPORT_TIME=09:00

# 7. Coding Engine ("native" or "aider")
CODING_ENGINE=aider

# 8. Enable Mock/Simulation fallbacks (set to true for offline testing, default is false)
ENABLE_MOCK_FALLBACK=false
"""

def print_setup_guide_and_exit(validation_errors):
    """
    Prints a detailed, step-by-step terminal guide instructing the user
    how to obtain required API credentials, creates a template .env file,
    and terminates execution.
    """
    separator = "=" * 80
    print(separator)
    print("                    AUTOOPSY CREDENTIALS SETUP GUIDE (FIRST RUN)")
    print(separator)
    print(f"CRITICAL CONFIGURATION ERROR(S) DETECTED:")
    for error in validation_errors:
        print(f"  - {error}")
    print()
    print("Please follow these step-by-step instructions to configure your targets:")
    print()
    print("1. TELEGRAM BOT TOKEN")
    print("   a. Open Telegram and search for the '@BotFather' bot.")
    print("   b. Send the command '/newbot' and follow the prompts to name your bot.")
    print("   c. Copy the HTTP API token provided (e.g., '123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ').")
    print()
    print("2. GITHUB PERSONAL ACCESS TOKEN (PAT)")
    print("   a. Sign in to GitHub and click your profile picture > Settings.")
    print("   b. Scroll to the bottom and click Developer Settings > Personal Access Tokens > Tokens (classic).")
    print("   c. Click 'Generate new token' (classic).")
    print("   d. Set a note, select expiration, and check the 'repo' scope checkbox.")
    print("   e. Copy the token (starts with 'ghp_') and set GITHUB_PAT. It will be used for both repos.")
    print()
    print("3. BACKEND TARGET (RENDER + GITHUB REPO)")
    print("   a. RENDER_API_KEY: Account Settings > API Keys > click 'Create API Key' in Render.")
    print("   b. RENDER_SERVICE_ID: Check the URL of your Web Service in Render Dashboard.")
    print("   c. BACKEND_GITHUB_REPO: The path of your backend repository (e.g. 'username/backend-repo').")
    print()
    print("4. FRONTEND TARGET (CLOUDFLARE PAGES + GITHUB REPO)")
    print("   a. CLOUDFLARE_API_TOKEN: Profile > API Tokens > Create Token. Use 'Edit Cloudflare Pages' template.")
    print("   b. CLOUDFLARE_ACCOUNT_ID & PROJECT_NAME: Available in Cloudflare Pages overview page.")
    print("   c. FRONTEND_GITHUB_REPO: The path of your frontend repository (e.g. 'username/frontend-repo').")
    print()
    print("5. LLM API KEY (OpenAI / DeepInfra / Fireworks / Gemini)")
    print("   a. Obtain API key from DeepInfra, Fireworks, OpenAI, or Google AI Studio (Gemini).")
    print("   b. Set LLM_PROVIDER to 'openai' or 'gemini' and configure the base URL and model identifiers.")
    print()
    print(separator)
    
    # Auto-generate a template .env file if .env is missing or empty
    env_file = ".env"
    if not os.path.exists(env_file) or os.path.getsize(env_file) == 0:
        with open(env_file, "w") as f:
            f.write(TEMPLATE_ENV_CONTENT)
        print(f"SUCCESS: A template file has been created at: '{os.path.abspath(env_file)}'")
        print("Please edit this file, input your credentials, and restart the application.")
    else:
        print(f"Please update the existing '{os.path.abspath(env_file)}' file with the correct settings.")
    print(separator)
    sys.exit(1)

# Resolve TARGET_RENDER_SERVICE_ID securely, avoiding conflicts with Render's auto-injected environment variable
RENDER_SERVICE_ID = os.getenv("TARGET_RENDER_SERVICE_ID")

# Validate config keys on start
validation_errors = []
for key in REQUIRED_CORE_ENV_VARS:
    if not os.getenv(key):
        validation_errors.append(f"Missing required core variable: {key}")

has_backend = bool(RENDER_SERVICE_ID)
has_frontend = bool(os.getenv("CLOUDFLARE_PROJECT_NAME"))

if not has_backend and not has_frontend:
    validation_errors.append("At least one target (TARGET_RENDER_SERVICE_ID for Backend, or CLOUDFLARE_PROJECT_NAME for Frontend) must be configured.")

if has_backend:
    if not os.getenv("RENDER_API_KEY"):
        validation_errors.append("RENDER_API_KEY (required because TARGET_RENDER_SERVICE_ID is set)")
    if not os.getenv("BACKEND_GITHUB_REPO"):
        validation_errors.append("BACKEND_GITHUB_REPO (required because TARGET_RENDER_SERVICE_ID is set)")

if has_frontend:
    if not os.getenv("CLOUDFLARE_API_TOKEN"):
        validation_errors.append("CLOUDFLARE_API_TOKEN (required because CLOUDFLARE_PROJECT_NAME is set)")
    if not os.getenv("CLOUDFLARE_ACCOUNT_ID"):
        validation_errors.append("CLOUDFLARE_ACCOUNT_ID (required because CLOUDFLARE_PROJECT_NAME is set)")
    if not os.getenv("FRONTEND_GITHUB_REPO"):
        validation_errors.append("FRONTEND_GITHUB_REPO (required because CLOUDFLARE_PROJECT_NAME is set)")

if validation_errors:
    print_setup_guide_and_exit(validation_errors)

# Load configuration into module constants
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GITHUB_PAT = os.getenv("GITHUB_PAT")

# Backend target configs
RENDER_API_KEY = os.getenv("RENDER_API_KEY")
# RENDER_SERVICE_ID is already defined above
RENDER_OWNER_ID = os.getenv("RENDER_OWNER_ID")
BACKEND_GITHUB_REPO = os.getenv("BACKEND_GITHUB_REPO")
BACKEND_GITHUB_BRANCH = os.getenv("BACKEND_GITHUB_BRANCH", "main")

# Frontend target configs
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_PROJECT_NAME = os.getenv("CLOUDFLARE_PROJECT_NAME")
FRONTEND_GITHUB_REPO = os.getenv("FRONTEND_GITHUB_REPO")
FRONTEND_GITHUB_BRANCH = os.getenv("FRONTEND_GITHUB_BRANCH", "main")

# LLM config
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_MODEL_DIAGNOSTIC = os.getenv("LLM_MODEL_DIAGNOSTIC", "meta-llama/Meta-Llama-3.1-8B-Instruct")
LLM_MODEL_CODER = os.getenv("LLM_MODEL_CODER", "meta-llama/Meta-Llama-3.1-70B-Instruct")
CODING_ENGINE = os.getenv("CODING_ENGINE", "aider").lower()
ENABLE_MOCK_FALLBACK = os.getenv("ENABLE_MOCK_FALLBACK", "false").lower() in ("true", "1", "yes")

# Authorization Config
ALLOWED_TELEGRAM_USER_IDS = os.getenv("ALLOWED_TELEGRAM_USER_IDS", "")
ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_TELEGRAM_USER_IDS.split(",") if uid.strip()]

# Web Server & Scheduler Config
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
DAILY_REPORT_TIME = os.getenv("DAILY_REPORT_TIME", "09:00")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHAT_ID_FILE = "chat_id.txt"

def get_target_chat_id() -> str:
    """
    Retrieves the saved chat ID if it exists and was cached, otherwise returns TELEGRAM_CHAT_ID from config.
    """
    if os.path.exists(CHAT_ID_FILE):
        try:
            with open(CHAT_ID_FILE, "r") as f:
                chat_id = f.read().strip()
                if chat_id:
                    return chat_id
        except Exception as e:
            logger.error(f"Error reading chat_id cache file: {e}")
    return TELEGRAM_CHAT_ID

def save_target_chat_id(chat_id: str):
    """
    Caches the chat ID in a local file so the daily reports scheduler can target it.
    """
    try:
        os.makedirs(os.path.dirname(CHAT_ID_FILE) if os.path.dirname(CHAT_ID_FILE) else ".", exist_ok=True)
        with open(CHAT_ID_FILE, "w") as f:
            f.write(str(chat_id))
        logger.info(f"Target chat ID saved: {chat_id}")
    except Exception as e:
        logger.error(f"Error saving chat_id cache file: {e}")
