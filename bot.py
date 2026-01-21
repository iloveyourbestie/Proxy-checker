import os
import json
import time
import asyncio
import logging
import aiohttp
import requests
import tarfile

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
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

# ================== GEO DB AUTO DOWNLOAD ==================

def ensure_geolite_db():
    if os.path.exists(GEO_DB):
        return

    logging.info("⬇️ Downloading GeoLite2 City database")

    url = "https://download.maxmind.com/app/geoip_download"
    params = {
        "edition_id": "GeoLite2-City",
        "license_key": MAXMIND_LICENSE_KEY,
        "suffix": "tar.gz",
    }

    r = requests.get(
        url,
        params=params,
        auth=(MAXMIND_ACCOUNT_ID, MAXMIND_LICENSE_KEY),
        timeout=30,
    )
    r.raise_for_status()

    tar_path = f"{DATA_DIR}/geo.tar.gz"
    with open(tar_path, "wb") as f:
        f.write(r.content)

    with tarfile.open(tar_path, "r:gz") as tar:
        for m in tar.getmembers():
            if m.name.endswith("GeoLite2-City.mmdb"):
                m.name = os.path.basename(m.name)
                tar.extract(m, DATA_DIR)

    os.remove(tar_path)
    logging.info("✅ GeoLite2 City ready")

# ================== GEO LOOKUP ==================

geo_reader = None

def geo_lookup(ip):
    try:
        r = geo_reader.city(ip)
        return (
            r.country.name or "Unknown",
            r.city.name or "Unknown",
            r.traits.isp or "Unknown",
        )
    except:
        return ("Unknown", "Unknown", "Unknown")

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

def smart_score(latency, uptime):
    return round((100 - min(latency / 10, 80)) + uptime * 10, 2)

# ================== AUTO DETECT ==================

def auto_detect(proxy):
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
                ssl=False,
            ) as r:
                if r.status != 200:
                    return None

        latency = int((time.time() - start) * 1000)
        country, city, isp = geo_lookup(ip)

        return {
            "proxy": proxy,
            "latency": latency,
            "country": country,
            "city": city,
            "isp": isp,
        }
    except:
        return None

# ================== HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_joined(context.bot, update.effective_user.id):
        kb = [[InlineKeyboardButton("✅ I Joined", callback_data="recheck")]]
        return await update.message.reply_text(
            "❌ Join required channels first",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    users = load("users.json")
    users[str(update.effective_user.id)] = int(time.time())
    save("users.json", users)

    await update.message.reply_text(
        "🚀 *PROXY CHECKER*\n\n"
        "• Real proxy validation\n"
        "• Country / City / ISP\n"
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
        return await update.message.reply_text("❌ Select proxy type first")

    file = await update.message.document.get_file()
    proxies = (await file.download_as_bytearray()).decode().splitlines()

    if ptype == "auto":
        ptype = auto_detect(proxies[0])

    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    results = []
    checked = 0
    start_time = time.time()

    msg = await update.message.reply_text("⏳ Starting checks...")

    async def runner(p):
        nonlocal checked
        async with sem:
            r = await check_proxy(p, ptype)
            checked += 1

            if r:
                results.append(r)

            if checked % 10 == 0 or checked == len(proxies):
                elapsed = max(time.time() - start_time, 1)
                cpm = int((checked / elapsed) * 60)
                eta = int(((len(proxies) - checked) / checked) * elapsed)

                try:
                    await msg.edit_text(
                        f"📊 {checked}/{len(proxies)}\n"
                        f"⚡ CPM: {cpm}\n"
                        f"⏱ ETA: {eta}s"
                    )
                except:
                    pass

    await asyncio.gather(*[runner(p) for p in proxies])

    uptime = load("uptime.json")
    for r in results:
        uptime[r["proxy"]] = uptime.get(r["proxy"], 0) + 1
    save("uptime.json", uptime)

    for r in results:
        r["score"] = smart_score(r["latency"], uptime[r["proxy"]])

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

    await msg.edit_text(
        f"✅ DONE\n🟢 Live: {len(results)}\n🔴 Dead: {len(proxies)-len(results)}"
    )

    await update.message.reply_document(document=open(out, "rb"))

# ================== ADMIN ==================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    users = load("users.json")
    checks = load("checks_count.json")
    await update.message.reply_text(
        f"👑 ADMIN\n\nUsers: {len(users)}\nChecks: {checks['total']}"
    )

# ================== MAIN ==================

async def main():
    ensure_storage()
    ensure_geolite_db()

    global geo_reader
    geo_reader = geoip2.database.Reader(GEO_DB)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("stats", stats))

    app.add_handler(CallbackQueryHandler(recheck, pattern="recheck"))
    app.add_handler(CallbackQueryHandler(proxy_type))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_file))

    logging.info("✅ BOT READY")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())