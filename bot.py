import os
import json
import time
import asyncio
import aiohttp
import aiofiles
import logging
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import geoip2.database

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 8537424608
REQUIRED_CHANNELS = ["@legendyt830", "@youXyash"]

DATA_DIR = Path("data")
HISTORY_DIR = DATA_DIR / "history"
USERS_FILE = DATA_DIR / "users.json"
BANS_FILE = DATA_DIR / "bans.json"
GEO_DB = "GeoLite2-Country.mmdb"
# =========================================

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("proxybot")

# ============ STORAGE INIT ============
def safe_json_load(path, default):
    try:
        if not path.exists() or path.stat().st_size == 0:
            return default
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def safe_json_save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

DATA_DIR.mkdir(exist_ok=True)
HISTORY_DIR.mkdir(exist_ok=True)

users = safe_json_load(USERS_FILE, {})
banned = set(safe_json_load(BANS_FILE, []))

# ============ GEO ============
geo_reader = geoip2.database.Reader(GEO_DB)

def get_country(ip):
    try:
        return geo_reader.country(ip).country.iso_code or "??"
    except:
        return "??"

# ============ FORCE JOIN ============
async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid == OWNER_ID:
        return True

    if uid in banned:
        await update.message.reply_text("🚫 You are banned.")
        return False

    for ch in REQUIRED_CHANNELS:
        try:
            m = await context.bot.get_chat_member(ch, uid)
            if m.status in ("left", "kicked"):
                raise Exception
        except:
            await update.message.reply_text(
                "❌ Join required channels first:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join Channel 1", url="https://t.me/legendyt830")],
                    [InlineKeyboardButton("Join Channel 2", url="https://t.me/youXyash")],
                    [InlineKeyboardButton("✅ I Joined", callback_data="recheck")]
                ])
            )
            return False

    users[str(uid)] = int(time.time())
    safe_json_save(USERS_FILE, users)
    return True

async def recheck_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    fake = Update(update.update_id, message=update.callback_query.message)
    if await check_access(fake, context):
        await update.callback_query.message.reply_text("✅ Access granted.")

# ============ PROXY UTILS ============
def parse_proxy(line):
    p = line.strip().split(":")
    if len(p) == 2:
        return p[0], p[1], None, None
    if len(p) == 4:
        return p[0], p[1], p[2], p[3]
    return None

def build_proxy(proto, ip, port, u=None, pw=None):
    if u and pw:
        return f"{proto}://{u}:{pw}@{ip}:{port}"
    return f"{proto}://{ip}:{port}"

AUTO_PROTOCOLS = ["https", "http", "socks5", "socks4"]

async def check_proxy(session, proto, proxy_line):
    parsed = parse_proxy(proxy_line)
    if not parsed:
        return None

    ip, port, u, pw = parsed
    proxy_url = build_proxy(proto, ip, port, u, pw)

    start = time.perf_counter()
    try:
        async with session.get(
            "http://httpbin.org/ip",
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=8),
            ssl=False
        ) as r:
            if r.status == 200:
                latency = int((time.perf_counter() - start) * 1000)
                return {
                    "proxy": proxy_line,
                    "type": proto,
                    "latency": latency,
                    "country": get_country(ip),
                }
    except:
        return None

async def auto_check(session, line):
    for proto in AUTO_PROTOCOLS:
        res = await check_proxy(session, proto, line)
        if res:
            return res
    return None

# ============ COMMANDS ============
async def start(update, context):
    if not await check_access(update, context):
        return
    await update.message.reply_text(
        "👋 **Proxy Checker Bot**\n\nUse /check to begin.",
        parse_mode="Markdown"
    )

async def check(update, context):
    if not await check_access(update, context):
        return
    await update.message.reply_text(
        "🧠 Select proxy type:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 HTTP", callback_data="http")],
            [InlineKeyboardButton("🔐 HTTPS", callback_data="https")],
            [InlineKeyboardButton("🧦 SOCKS5", callback_data="socks5")],
            [InlineKeyboardButton("🧦 SOCKS4", callback_data="socks4")],
            [InlineKeyboardButton("🤖 Automatic Select", callback_data="auto")],
        ])
    )

async def type_cb(update, context):
    await update.callback_query.answer()
    context.user_data["ptype"] = update.callback_query.data
    await update.callback_query.message.reply_text("📤 Upload proxy .txt file")

# ============ FILE HANDLER ============
async def file_handler(update, context):
    if not await check_access(update, context):
        return

    if "ptype" not in context.user_data:
        await update.message.reply_text("Use /check first.")
        return

    uid = str(update.effective_user.id)
    ptype = context.user_data["ptype"]

    file = await update.message.document.get_file()
    content = (await file.download_as_bytearray()).decode().splitlines()
    proxies = [x.strip() for x in content if x.strip()]

    msg = await update.message.reply_text("⏳ Checking proxies...")

    results = []
    async with aiohttp.ClientSession() as session:
        sem = asyncio.Semaphore(50)

        async def run(p):
            async with sem:
                if ptype == "auto":
                    return await auto_check(session, p)
                return await check_proxy(session, ptype, p)

        tasks = [run(p) for p in proxies]
        done = 0

        for coro in asyncio.as_completed(tasks):
            r = await coro
            done += 1
            if r:
                results.append(r)
            if done % 10 == 0:
                await msg.edit_text(f"⏳ Progress: {done}/{len(proxies)}")

    results.sort(key=lambda x: x["latency"])

    out_dir = HISTORY_DIR / uid
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{ptype}_{int(time.time())}.txt"

    async with aiofiles.open(out_file, "w") as f:
        for r in results:
            score = max(1, 1000 - r["latency"])
            await f.write(
                f"{r['proxy']} | {r['type']} | {r['country']} | {r['latency']}ms | score:{score}\n"
            )

    await msg.edit_text(
        f"✅ Done\n\n"
        f"✔ Live: {len(results)}\n"
        f"❌ Dead: {len(proxies)-len(results)}"
    )

    if results:
        await update.message.reply_document(open(out_file, "rb"))

# ============ MAIN ============
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CallbackQueryHandler(recheck_cb, pattern="recheck"))
    app.add_handler(CallbackQueryHandler(type_cb))
    app.add_handler(MessageHandler(filters.Document.TEXT, file_handler))

    log.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()