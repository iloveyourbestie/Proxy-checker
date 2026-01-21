import os
import json
import asyncio
import aiohttp
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Document,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

OWNER_ID = 8537424608
REQUIRED_CHANNELS = ["@legendyt830", "@youXyash"]

DATA_DIR = "data"
RESULT_DIR = os.path.join(DATA_DIR, "results")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
CHECKS_FILE = os.path.join(DATA_DIR, "checks_count.json")
BAN_FILE = os.path.join(DATA_DIR, "ban.json")
# =========================================

# ========== SETUP LOGGING ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# ===================================

# ========== AUTO INIT STORAGE ==========
def init_storage():
    """Initialize all required directories and files"""
    try:
        # Create directories
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(RESULT_DIR, exist_ok=True)
        
        # Initialize JSON files with default data if they don't exist or are corrupted
        files_to_init = [
            (USERS_FILE, {}),
            (CHECKS_FILE, {"total_checks": 0}),
            (BAN_FILE, [])
        ]
        
        for file_path, default_data in files_to_init:
            try:
                if not os.path.exists(file_path):
                    logger.info(f"Creating {file_path}")
                    with open(file_path, 'w') as f:
                        json.dump(default_data, f, indent=2)
                else:
                    # Check if file is valid JSON
                    with open(file_path, 'r') as f:
                        content = f.read()
                        if not content.strip():
                            logger.warning(f"{file_path} is empty, resetting")
                            with open(file_path, 'w') as fw:
                                json.dump(default_data, fw, indent=2)
                        else:
                            json.loads(content)  # Just to validate
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Error reading {file_path}: {e}. Resetting...")
                with open(file_path, 'w') as f:
                    json.dump(default_data, f, indent=2)
        
        # Load data
        with open(USERS_FILE, 'r') as f:
            users = json.load(f)
        
        with open(CHECKS_FILE, 'r') as f:
            checks_count = json.load(f)
        
        with open(BAN_FILE, 'r') as f:
            banned_users = set(json.load(f))
        
        return users, checks_count, banned_users
        
    except Exception as e:
        logger.error(f"Failed to initialize storage: {e}")
        # Return defaults
        return {}, {"total_checks": 0}, set()

# Initialize storage
users, checks_count, banned_users = init_storage()
# ======================================

# =============== FORCE JOIN =================
async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False

    uid = user.id

    if uid == OWNER_ID:
        return True

    if uid in banned_users:
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return False

    for ch in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(ch, uid)
            if member.status in ("left", "kicked"):
                raise Exception
        except Exception:
            await update.message.reply_text(
                "❌ You must join both channels to use this bot.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join @legendyt830", url="https://t.me/legendyt830")],
                    [InlineKeyboardButton("Join @youXyash", url="https://t.me/youXyash")],
                ])
            )
            return False

    users[str(uid)] = True
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

    return True
# ===========================================

# ============ ASYNC PROXY CHECK ============
async def check_proxy(session, proxy, proxy_type="http"):
    """Check if a proxy is working"""
    try:
        # Format proxy based on type
        if proxy_type == "http":
            proxy_url = f"http://{proxy}"
        else:  # socks5
            proxy_url = f"socks5://{proxy}"
        
        async with session.get(
            "http://httpbin.org/ip",
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=5),
            ssl=False
        ) as r:
            if r.status == 200:
                return proxy
    except Exception as e:
        return None
# ==========================================

# ================= COMMANDS =================
async def start(update, context):
    if not await check_access(update, context):
        return
    await update.message.reply_text("👋 Use /check to verify proxies.")

async def stats(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    
    # Reload data
    global users, checks_count, banned_users
    users, checks_count, banned_users = init_storage()
    
    await update.message.reply_text(
        f"📊 Bot Stats\n\n"
        f"👤 Users: {len(users)}\n"
        f"📂 Total checks: {checks_count.get('total_checks', 0)}\n"
        f"🚫 Banned users: {len(banned_users)}"
    )

async def ban(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        uid = int(context.args[0])
        banned_users.add(uid)
        with open(BAN_FILE, "w") as f:
            json.dump(list(banned_users), f, indent=2)
        await update.message.reply_text(f"✅ User {uid} banned")
    except:
        await update.message.reply_text("Usage: /ban <user_id>")

async def unban(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        uid = int(context.args[0])
        if uid in banned_users:
            banned_users.remove(uid)
            with open(BAN_FILE, "w") as f:
                json.dump(list(banned_users), f, indent=2)
            await update.message.reply_text(f"✅ User {uid} unbanned")
        else:
            await update.message.reply_text(f"❌ User {uid} is not banned")
    except:
        await update.message.reply_text("Usage: /unban <user_id>")

async def check(update, context):
    if not await check_access(update, context):
        return
    await update.message.reply_text(
        "Select proxy type:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("HTTP", callback_data="http")],
            [InlineKeyboardButton("SOCKS5", callback_data="socks5")],
        ])
    )
# ===========================================

# ============ CALLBACK ======================
async def proxy_type_selected(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["proxy_type"] = query.data
    await query.edit_message_text("📤 Upload proxy file (.txt)")
# ===========================================

# ============ FILE HANDLER ==================
async def handle_file(update, context):
    if not await check_access(update, context):
        return

    if "proxy_type" not in context.user_data:
        await update.message.reply_text("❗ Use /check first.")
        return

    uid = str(update.effective_user.id)
    proxy_type = context.user_data["proxy_type"]

    user_dir = os.path.join(RESULT_DIR, uid)
    os.makedirs(user_dir, exist_ok=True)

    doc: Document = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("❗ Please upload a .txt file.")
        return

    # Check file size (max 1MB)
    if doc.file_size > 1024 * 1024:
        await update.message.reply_text("❗ File too large. Max size is 1MB.")
        return

    try:
        file = await doc.get_file()
        data = await file.download_as_bytearray()
        
        proxies = data.decode().splitlines()
        proxies = [p.strip() for p in proxies if p.strip()]
        
        if not proxies:
            await update.message.reply_text("❗ No proxies found in the file.")
            return
            
        if len(proxies) > 1000:
            await update.message.reply_text("❗ Too many proxies. Max 1000 per file.")
            return
            
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        await update.message.reply_text("❗ Error reading file. Make sure it's a valid text file.")
        return

    msg = await update.message.reply_text(f"🔍 Checking {len(proxies)} proxies...")

    good = []
    
    # Check proxies with concurrency limit
    async with aiohttp.ClientSession() as session:
        semaphore = asyncio.Semaphore(50)  # Limit concurrent connections
        
        async def check_with_semaphore(proxy):
            async with semaphore:
                return await check_proxy(session, proxy, proxy_type)
        
        tasks = [check_with_semaphore(p) for p in proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for proxy, result in zip(proxies, results):
            if result and not isinstance(result, Exception):
                good.append(proxy)

    # Save results
    timestamp = int(asyncio.get_event_loop().time())
    out_path = os.path.join(user_dir, f"{proxy_type}_checked_{timestamp}.txt")
    
    try:
        with open(out_path, "w") as f:
            f.write("\n".join(good))
        
        # Update checks count
        checks_count["total_checks"] = checks_count.get("total_checks", 0) + 1
        with open(CHECKS_FILE, "w") as f:
            json.dump(checks_count, f, indent=2)
        
        result_text = f"✅ Check completed!\n✅ Working: {len(good)}\n❌ Dead: {len(proxies) - len(good)}"
        await msg.edit_text(result_text)
        
        if good:
            await update.message.reply_document(
                document=open(out_path, "rb"),
                caption=f"✅ {len(good)} working {proxy_type.upper()} proxies found."
            )
        else:
            await update.message.reply_text("❌ No working proxies found.")
            
    except Exception as e:
        logger.error(f"Error saving results: {e}")
        await msg.edit_text("❌ Error saving results. Please try again.")
# ===========================================

# ================= MAIN =====================
async def main():
    try:
        logger.info("🤖 Bot is starting...")
        logger.info(f"📁 Data directory: {DATA_DIR}")
        logger.info(f"👤 Registered users: {len(users)}")
        logger.info(f"📊 Total checks: {checks_count.get('total_checks', 0)}")
        logger.info(f"🚫 Banned users: {len(banned_users)}")
        
        app = Application.builder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("stats", stats))
        app.add_handler(CommandHandler("ban", ban))
        app.add_handler(CommandHandler("unban", unban))
        app.add_handler(CommandHandler("check", check))
        app.add_handler(CallbackQueryHandler(proxy_type_selected))
        app.add_handler(MessageHandler(filters.Document.TEXT & filters.Document.FileExtension("txt"), handle_file))

        logger.info("✅ Bot is ready!")
        await app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
# ===========================================

if __name__ == "__main__":
    # Initialize storage on startup
    users, checks_count, banned_users = init_storage()
    asyncio.run(main())
