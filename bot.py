whatimport os
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

# ========== LOGGING ==========
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
# ============================

# ========== STORAGE INIT ==========
def init_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RESULT_DIR, exist_ok=True)

    def ensure(path, default):
        if not os.path.exists(path):
            with open(path, "w") as f:
                json.dump(default, f, indent=2)

    ensure(USERS_FILE, {})
    ensure(CHECKS_FILE, {"total_checks": 0})
    ensure(BAN_FILE, [])

    with open(USERS_FILE) as f:
        users = json.load(f)

    with open(CHECKS_FILE) as f:
        checks = json.load(f)

    with open(BAN_FILE) as f:
        banned = set(json.load(f))

    return users, checks, banned


users, checks_count, banned_users = init_storage()
# ==========================================

# =============== FORCE JOIN =================
async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False

    uid = user.id

    if uid == OWNER_ID:
        return True

    if uid in banned_users:
        await update.message.reply_text("🚫 You are banned.")
        return False

    for ch in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(ch, uid)
            if member.status in ("left", "kicked"):
                raise Exception
        except Exception:
            await update.message.reply_text(
                "❌ Join both channels to use the bot.",
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
async def check_proxy(session, proxy, proxy_type):
    try:
        if proxy_type == "socks5":
            proxy_url = f"socks5://{proxy}"
        else:
            proxy_url = f"http://{proxy}"

        async with session.get(
            "http://httpbin.org/ip",
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=6),
            ssl=False,
        ) as r:
            if r.status == 200:
                return proxy
    except:
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
    await update.message.reply_text(
        f"📊 Stats\n\n"
        f"👤 Users: {len(users)}\n"
        f"📂 Total checks: {checks_count.get('total_checks', 0)}\n"
        f"🚫 Banned: {len(banned_users)}"
    )

async def ban(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        uid = int(context.args[0])
        banned_users.add(uid)
        with open(BAN_FILE, "w") as f:
            json.dump(list(banned_users), f, indent=2)
        await update.message.reply_text(f"✅ Banned {uid}")
    except:
        await update.message.reply_text("Usage: /ban <user_id>")

async def unban(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        uid = int(context.args[0])
        banned_users.discard(uid)
        with open(BAN_FILE, "w") as f:
            json.dump(list(banned_users), f, indent=2)
        await update.message.reply_text(f"✅ Unbanned {uid}")
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
    ptype = context.user_data["proxy_type"]

    doc: Document = update.message.document
    file = await doc.get_file()
    text = (await file.download_as_bytearray()).decode().splitlines()
    proxies = [p.strip() for p in text if p.strip()]

    user_dir = os.path.join(RESULT_DIR, uid)
    os.makedirs(user_dir, exist_ok=True)

    msg = await update.message.reply_text(f"🔍 Checking {len(proxies)} proxies...")

    good = []
    async with aiohttp.ClientSession() as session:
        sem = asyncio.Semaphore(40)

        async def run(p):
            async with sem:
                return await check_proxy(session, p, ptype)

        results = await asyncio.gather(*(run(p) for p in proxies))
        good = [r for r in results if r]

    out = os.path.join(user_dir, f"{ptype}_checked.txt")
    with open(out, "w") as f:
        f.write("\n".join(good))

    checks_count["total_checks"] += 1
    with open(CHECKS_FILE, "w") as f:
        json.dump(checks_count, f, indent=2)

    await msg.edit_text(f"✅ Done. Working: {len(good)}")
    if good:
        await update.message.reply_document(open(out, "rb"))
# ===========================================

# ================= MAIN =====================
def main():
    logger.info("🤖 Bot starting...")
    logger.info(f"Users: {len(users)} | Checks: {checks_count['total_checks']}")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CallbackQueryHandler(proxy_type_selected))
    app.add_handler(
        MessageHandler(
            filters.Document.TEXT & filters.Document.FileExtension("txt"),
            handle_file,
        )
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES)
# ===========================================

if __name__ == "__main__":
    main()