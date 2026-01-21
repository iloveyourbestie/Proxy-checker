import os
import json
import time
import asyncio
import logging
import aiohttp
import tarfile
import requests
from pathlib import Path

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
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

# ================== HARD CONFIG ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 8537424608  # 🔥 RAW OWNER ID

MAXMIND_ACCOUNT_ID = os.getenv("MAXMIND_ACCOUNT_ID")
MAXMIND_LICENSE_KEY = os.getenv("MAXMIND_LICENSE_KEY")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

if not MAXMIND_LICENSE_KEY:
    raise RuntimeError("MAXMIND_LICENSE_KEY not set")

REQUIRED_CHANNELS = ["@legendyt830", "@youXyash"]

DATA_DIR = "data"
RESULTS_DIR = f"{DATA_DIR}/results"
GEO_DB = f"{DATA_DIR}/GeoLite2-City.mmdb"

TIMEOUT = aiohttp.ClientTimeout(total=15)
MAX_CONCURRENCY = 50  # accurate, not fake-fast

# ================== LOGGING ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ================== STORAGE ==================

def ensure_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    defaults = {
        "users.json": {},
        "checks_count.json": {"total": 0},
        "ban.json": [],
        "uptime.json": {},
    }

    for name, default in defaults.items():
        path = f"{DATA_DIR}/{name}"
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            with open(path, "w") as f:
                json.dump(default, f)

def load(name):
    with open(f"{DATA_DIR}/{name}", "r") as f:
        return json.load(f)

def save(name, data):
    with open(f"{DATA_DIR}/{name}", "w") as f:
        json.dump(data, f, indent=2)

# ================== GEO DOWNLOAD ==================

def ensure_geolite():
    if os.path.exists(GEO_DB):
        return

    logging.info("⬇️ Downloading GeoLite2 City DB")

    url = (
        "https://download.maxmind.com/app/geoip_download"
        f"?edition_id=GeoLite2-City&license_key={MAXMIND_LICENSE_KEY}&suffix=tar.gz"
    )

    tar_path = f"{DATA_DIR}/geo.tar.gz"

    r = requests.get(url, stream=True)
    with open(tar_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

    with tarfile.open(tar_path, "r:gz") as tar:
        for m in tar.getmembers():
            if m.name.endswith(".mmdb"):
                m.name = os.path.basename(m.name)
                tar.extract(m, DATA_DIR)

    os.remove(tar_path)
    logging.info("✅ GeoLite2 ready")

# ================== GEO LOOKUP ==================

geo_reader = None

def geo_lookup(ip):
    try:
        r = geo_reader.city(ip)
        return {
            "country": r.country.name or "Unknown",
            "city": r.city.name or "Unknown",
            "isp": r.traits.isp or "Unknown",
        }
    except:
        return {"country": "Unknown", "city": "Unknown", "isp": "Unknown"}

# ================== FORCE JOIN ==================

async def is_joined(bot, uid):
    for ch in REQUIRED_CHANNELS:
        try:
            m = await bot.get_chat_member(ch, uid)
            if m.status not in ("member", "administrator", "creator"):
                return False
        except:
            return False
    return True

# ================== SMART SCORE ==================

def smart_score(latency_ms, uptime):
    return round((100 - min(latency_ms / 15, 80)) + (uptime * 15), 2)

# ================== AUTO DETECT ==================

def auto_detect(proxy):
    if proxy.count(":") == 3:
        return "http"
    return "http"

# ================== PROXY CHECK ==================

async def check_proxy(proxy, ptype):
    start = time.time()
    parts = proxy.split(":")
    ip = parts[0]

    proxy_url = f"{ptype}://{proxy}"

    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(
                "http://httpbin.org/ip",
                proxy=proxy_url,
                ssl=False
            ) as r:
                if r.status != 200:
                    return None

        latency = int((time.time() - start) * 1000)
        geo = geo_lookup(ip)

        return {
            "proxy": proxy,
            "latency": latency,
            "country": geo["country"],
            "city": geo["city"],
            "isp": geo["isp"],
        }
    except:
        return None

# ================== HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_joined(context.bot, update.effective_user.id):
        kb = [[InlineKeyboardButton("✅ I Joined", callback_data="recheck")]]
        return await update.message.reply_text(
            "❌ Join required channels first.",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    bans = load("ban.json")
    if str(update.effective_user.id) in bans:
        return await update.message.reply_text("🚫 You are banned.")

    users = load("users.json")
    users[str(update.effective_user.id)] = int(time.time())
    save("users.json", users)

    await update.message.reply_text(
        "🚀 *PROXY CHECKER*\n\n"
        "• Accurate validation\n"
        "• City / ISP / Country\n"
        "• CPM + ETA\n"
        "• Smart Score ranking\n\n"
        "Use /check",
        parse_mode="Markdown",
    )

async def recheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if await is_joined(context.bot, q.from_user.id):
        await q.message.edit_text("✅ Access granted. Use /check")

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🌐 HTTP", callback_data="http")],
        [InlineKeyboardButton("🔒 HTTPS", callback_data="https")],
        [InlineKeyboardButton("🧦 SOCKS4", callback_data="socks4")],
        [InlineKeyboardButton("🧦 SOCKS5", callback_data="socks5")],
        [InlineKeyboardButton("⚡ AUTO", callback_data="auto")],
    ]
    await update.message.reply_text(
        "🧠 *Select proxy type*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )

async def proxy_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["ptype"] = q.data
    await q.message.edit_text("📤 Upload proxy `.txt` file")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ptype = context.user_data.get("ptype")

    if not ptype:
        return await update.message.reply_text("❌ Select proxy type first.")

    file = await update.message.document.get_file()
    proxies = (await file.download_as_bytearray()).decode().splitlines()

    if ptype == "auto":
        ptype = auto_detect(proxies[0])

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    results = []
    checked = 0
    start_time = time.time()

    progress = await update.message.reply_text("⏳ Checking proxies...")

    async def runner(p):
        nonlocal checked
        async with sem:
            r = await check_proxy(p, ptype)
            checked += 1
            if r:
                results.append(r)

            if checked % 10 == 0 or checked == len(proxies):
                elapsed = time.time() - start_time
                cpm = int((checked / max(elapsed, 1)) * 60)
                eta = int(((len(proxies) - checked) / max(checked, 1)) * elapsed)
                await progress.edit_text(
                    f"📊 {checked}/{len(proxies)}\n⚡ CPM: {cpm}\n⏱ ETA: {eta}s"
                )

    await asyncio.gather(*[runner(p) for p in proxies])

    uptime = load("uptime.json")
    for r in results:
        uptime[r["proxy"]] = uptime.get(r["proxy"], 0) + 1
    save("uptime.json", uptime)

    for r in results:
        r["score"] = smart_score(r["latency"], uptime.get(r["proxy"], 1))

    results.sort(key=lambda x: x["score"], reverse=True)

    user_dir = f"{RESULTS_DIR}/{uid}"
    os.makedirs(user_dir, exist_ok=True)
    out = f"{user_dir}/{ptype}_live.txt"

    with open(out, "w") as f:
        for r in results:
            f.write(
                f'{r["proxy"]} | {r["latency"]}ms | '
                f'{r["country"]}/{r["city"]} | '
                f'{r["isp"]} | SCORE:{r["score"]}\n'
            )

    checks = load("checks_count.json")
    checks["total"] += len(proxies)
    save("checks_count.json", checks)

    await progress.edit_text(
        f"✅ DONE\n🟢 Live: {len(results)}\n🔴 Dead: {len(proxies)-len(results)}"
    )
    await update.message.reply_document(document=open(out, "rb"))

# ================== ADMIN ==================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(
        f"👑 ADMIN\n\n"
        f"👤 Users: {len(load('users.json'))}\n"
        f"📊 Checks: {load('checks_count.json')['total']}"
    )

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    uid = context.args[0]
    bans = load("ban.json")
    if uid not in bans:
        bans.append(uid)
    save("ban.json", bans)
    await update.message.reply_text("🚫 Banned")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    uid = context.args[0]
    bans = load("ban.json")
    if uid in bans:
        bans.remove(uid)
    save("ban.json", bans)
    await update.message.reply_text("✅ Unbanned")

# ================== MAIN ==================

async def main():
    ensure_storage()
    ensure_geolite()

    global geo_reader
    geo_reader = geoip2.database.Reader(GEO_DB)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))

    app.add_handler(CallbackQueryHandler(recheck, pattern="recheck"))
    app.add_handler(CallbackQueryHandler(proxy_type))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_file))

    logging.info("✅ BOT STARTED")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(main())