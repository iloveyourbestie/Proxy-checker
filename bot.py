import os
import json
import time
import asyncio
import aiohttp
import logging
from datetime import datetime
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
    raise RuntimeError("BOT_TOKEN not set")

OWNER_ID = 8537424608
FORCE_JOIN_CHANNELS = ["legendyt830", "youXyash"]

DATA_DIR = "data"
RESULT_DIR = f"{DATA_DIR}/results"
USERS_FILE = f"{DATA_DIR}/users.json"
CHECKS_FILE = f"{DATA_DIR}/checks_count.json"
BAN_FILE = f"{DATA_DIR}/ban.json"
# =========================================

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("PROXY")

# ========== STORAGE INIT ==========
def safe_json(path, default):
    try:
        if not os.path.exists(path) or os.stat(path).st_size == 0:
            raise ValueError
        with open(path, "r") as f:
            return json.load(f)
    except:
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default

def init_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RESULT_DIR, exist_ok=True)

    users = safe_json(USERS_FILE, {})
    checks = safe_json(CHECKS_FILE, {"total": 0})
    bans = set(safe_json(BAN_FILE, []))
    return users, checks, bans

users, checks_count, banned_users = init_storage()

# ========== FORCE JOIN ==========
async def check_access(update, context):
    uid = update.effective_user.id

    if uid == OWNER_ID:
        return True

    if uid in banned_users:
        await update.message.reply_text("🚫 You are banned.")
        return False

    for ch in FORCE_JOIN_CHANNELS:
        try:
            m = await context.bot.get_chat_member(f"@{ch}", uid)
            if m.status in ("left", "kicked"):
                raise Exception
        except:
            await update.message.reply_text(
                "🔒 **Join required channels**",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 @legendyt830", url="https://t.me/legendyt830")],
                    [InlineKeyboardButton("📢 @youXyash", url="https://t.me/youXyash")],
                    [InlineKeyboardButton("✅ I Joined", callback_data="recheck")]
                ])
            )
            return False

    users[str(uid)] = True
    json.dump(users, open(USERS_FILE, "w"), indent=2)
    return True

# ========== PROXY CHECK ==========
async def check_proxy(session, proxy, ptype):
    url = "http://httpbin.org/ip"
    proxy_url = f"{ptype}://{proxy}"
    start = time.time()

    try:
        async with session.get(
            url,
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=8),
            ssl=False
        ) as r:
            if r.status == 200:
                latency = int((time.time() - start) * 1000)
                country = r.headers.get("X-Forwarded-For", "Unknown")
                return proxy, latency, country
    except:
        return None

# ========== COMMANDS ==========
async def start(update, context):
    await update.message.reply_text(
        "👋 **PROXY CHECKER**\n\n"
        "⚡ Async • Live CPM • Country • Latency\n\n"
        "📌 /check — Start checking\n"
        "📂 /history — Your results",
        parse_mode="Markdown"
    )

async def check(update, context):
    if not await check_access(update, context):
        return
    await update.message.reply_text(
        "🧪 **Select proxy type**",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 HTTP", callback_data="http")],
            [InlineKeyboardButton("🔐 HTTPS", callback_data="https")],
            [InlineKeyboardButton("🧦 SOCKS5", callback_data="socks5")],
        ])
    )

async def history(update, context):
    uid = str(update.effective_user.id)
    hist = f"{RESULT_DIR}/{uid}/history.json"
    if not os.path.exists(hist):
        await update.message.reply_text("📭 No history yet.")
        return
    await update.message.reply_document(open(hist, "rb"))

# ========== CALLBACK ==========
async def proxy_type_selected(update, context):
    await update.callback_query.answer()
    context.user_data["ptype"] = update.callback_query.data
    await update.callback_query.edit_message_text("📤 Upload `.txt` proxy file")

# ========== FILE HANDLER ==========
async def handle_file(update, context):
    if not await check_access(update, context):
        return

    uid = str(update.effective_user.id)
    ptype = context.user_data.get("ptype")
    if not ptype:
        return await update.message.reply_text("Use /check first")

    os.makedirs(f"{RESULT_DIR}/{uid}", exist_ok=True)

    doc: Document = update.message.document
    file = await doc.get_file()
    proxies = (await file.download_as_bytearray()).decode().splitlines()
    proxies = [p.strip() for p in proxies if p.strip()]

    msg = await update.message.reply_text("⏳ Starting check...")

    good = []
    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        sem = asyncio.Semaphore(50)

        async def run(p):
            async with sem:
                return await check_proxy(session, p, ptype)

        tasks = [run(p) for p in proxies]

        done = 0
        for coro in asyncio.as_completed(tasks):
            res = await coro
            done += 1

            if res:
                good.append(res)

            elapsed = time.time() - start_time
            cpm = int(done / elapsed * 60) if elapsed > 0 else 0
            percent = int(done / len(proxies) * 100)

            if done % 10 == 0:
                await msg.edit_text(
                    f"⚡ **Live Checking**\n\n"
                    f"📊 Progress: `{percent}%`\n"
                    f"🚀 CPM: `{cpm}`\n"
                    f"✅ Good: `{len(good)}`",
                    parse_mode="Markdown"
                )

    out = f"{RESULT_DIR}/{uid}/{ptype}_checked.txt"
    with open(out, "w") as f:
        for p, ms, c in good:
            f.write(f"{p} | {ms}ms | {c}\n")

    hist = f"{RESULT_DIR}/{uid}/history.json"
    history = safe_json(hist, [])
    history.append({
        "type": ptype,
        "total": len(proxies),
        "good": len(good),
        "time": datetime.utcnow().isoformat()
    })
    json.dump(history, open(hist, "w"), indent=2)

    checks_count["total"] += 1
    json.dump(checks_count, open(CHECKS_FILE, "w"), indent=2)

    await msg.edit_text(
        f"✅ **Completed**\n\n"
        f"🟢 Working: `{len(good)}`\n"
        f"🔴 Dead: `{len(proxies)-len(good)}`",
        parse_mode="Markdown"
    )
    await update.message.reply_document(open(out, "rb"))

# ========== MAIN ==========
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CallbackQueryHandler(proxy_type_selected))
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_file))

    app.run_polling()

if __name__ == "__main__":
    main()