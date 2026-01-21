import os
import json
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Railway env var
OWNER_ID = 8537424608

FORCE_JOIN_CHANNELS = [
    "legendyt830",
    "youXyash",
]

DATA_DIR = "data"
RESULTS_DIR = os.path.join(DATA_DIR, "results")

USERS_FILE = os.path.join(DATA_DIR, "users.json")
CHECKS_FILE = os.path.join(DATA_DIR, "checks_count.json")
BAN_FILE = os.path.join(DATA_DIR, "ban.json")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ============== STORAGE ===================
def safe_load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f)
        return default

    try:
        with open(path, "r") as f:
            data = json.load(f)
            if data is None:
                raise ValueError
            return data
    except (json.JSONDecodeError, ValueError):
        with open(path, "w") as f:
            json.dump(default, f)
        return default


def init_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    users = safe_load_json(USERS_FILE, {})
    checks = safe_load_json(CHECKS_FILE, {"total": 0})
    banned = safe_load_json(BAN_FILE, [])

    return users, checks, banned


users, checks_count, banned_users = init_storage()

# ============== FORCE JOIN =================
async def is_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    for channel in FORCE_JOIN_CHANNELS:
        try:
            member = await context.bot.get_chat_member(f"@{channel}", user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except Exception:
            return False
    return True


async def force_join_message(update: Update):
    buttons = [
        [InlineKeyboardButton("Join Channel", url=f"https://t.me/{c}")]
        for c in FORCE_JOIN_CHANNELS
    ]
    buttons.append(
        [InlineKeyboardButton("✅ Recheck", callback_data="recheck_join")]
    )

    await update.message.reply_text(
        "🚫 Join required channels to use this bot.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def recheck_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if await is_member(update, context):
        await query.message.reply_text("✅ Access granted. Use /check")
    else:
        await query.message.reply_text("❌ Still not joined all channels.")

# ============== COMMANDS ===================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    if uid in banned_users:
        return

    if not await is_member(update, context):
        await force_join_message(update)
        return

    users.setdefault(uid, {})
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "Use /check to upload proxy file\n"
        "Use /stats to see usage"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    await update.message.reply_text(
        f"👤 Users: {len(users)}\n"
        f"📊 Total checks: {checks_count['total']}"
    )


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    if not context.args:
        return

    uid = context.args[0]
    banned_users.append(uid)
    with open(BAN_FILE, "w") as f:
        json.dump(banned_users, f)

    await update.message.reply_text(f"🚫 Banned {uid}")


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    uid = context.args[0]
    if uid in banned_users:
        banned_users.remove(uid)

    with open(BAN_FILE, "w") as f:
        json.dump(banned_users, f)

    await update.message.reply_text(f"✅ Unbanned {uid}")


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_member(update, context):
        await force_join_message(update)
        return

    keyboard = [
        [InlineKeyboardButton("HTTP", callback_data="http")],
        [InlineKeyboardButton("HTTPS", callback_data="https")],
        [InlineKeyboardButton("SOCKS5", callback_data="socks5")],
    ]

    await update.message.reply_text(
        "Select proxy type:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def proxy_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["proxy_type"] = query.data
    await query.message.reply_text("📂 Upload .txt proxy file")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    proxy_type = context.user_data.get("proxy_type")

    if not proxy_type:
        await update.message.reply_text("❌ Select proxy type first.")
        return

    file = await update.message.document.get_file()
    content = (await file.download_as_bytearray()).decode()

    user_dir = os.path.join(RESULTS_DIR, uid)
    os.makedirs(user_dir, exist_ok=True)

    out_file = os.path.join(user_dir, f"{proxy_type}_checked.txt")
    with open(out_file, "w") as f:
        f.write(content)

    checks_count["total"] += 1
    with open(CHECKS_FILE, "w") as f:
        json.dump(checks_count, f)

    await update.message.reply_text(
        f"✅ Saved `{proxy_type}` results",
        parse_mode="Markdown",
    )

# ============== MAIN =======================
async def main():
    log.info("🤖 Bot starting")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("check", check))

    app.add_handler(CallbackQueryHandler(recheck_join, pattern="^recheck_join$"))
    app.add_handler(CallbackQueryHandler(proxy_type_selected))
    app.add_handler(
        MessageHandler(filters.Document.FileExtension("txt"), handle_file)
    )

    await app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    asyncio.run(main())