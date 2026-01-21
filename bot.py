import os
import json
import asyncio
import aiohttp
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

# ========== AUTO INIT STORAGE ==========
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

def ensure_file(path, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f)

ensure_file(USERS_FILE, {})
ensure_file(CHECKS_FILE, {"total_checks": 0})
ensure_file(BAN_FILE, [])
# ======================================

# ========== LOAD DATA ==========
with open(USERS_FILE) as f:
    users = json.load(f)

with open(CHECKS_FILE) as f:
    checks_count = json.load(f)

with open(BAN_FILE) as f:
    banned_users = set(json.load(f))
# ==============================

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
async def check_proxy(session, proxy):
    try:
        async with session.get(
            "http://httpbin.org/ip",
            proxy=f"http://{proxy}",
            timeout=aiohttp.ClientTimeout(total=8),
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
        f"📊 Bot Stats\n\n"
        f"👤 Users: {len(users)}\n"
        f"📂 Total checks: {checks_count['total_checks']}"
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
    await query.message.reply_text("📤 Upload proxy file (.txt)")
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
    file = await doc.get_file()
    data = await file.download_as_bytearray()
    proxies = data.decode().splitlines()

    good = []
    async with aiohttp.ClientSession() as session:
        for p in proxies:
            res = await check_proxy(session, p)
            if res:
                good.append(res)

    out_path = os.path.join(user_dir, f"{proxy_type}_checked.txt")
    with open(out_path, "w") as f:
        f.write("\n".join(good))

    checks_count["total_checks"] += 1
    with open(CHECKS_FILE, "w") as f:
        json.dump(checks_count, f, indent=2)

    await update.message.reply_document(
        document=open(out_path, "rb"),
        caption=f"✅ Done. Working: {len(good)}"
    )
# ===========================================

# ================= MAIN =====================
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CallbackQueryHandler(proxy_type_selected))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
