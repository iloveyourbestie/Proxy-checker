import os
import json
import time
import asyncio
import aiohttp
from pathlib import Path
from aiohttp_socks import ProxyConnector
import geoip2.database

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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
OWNER_ID = 8537424608

FORCE_JOIN_CHANNELS = ["@legendyt830", "@youXyash"]

DATA_DIR = Path("data")
RESULTS_DIR = DATA_DIR / "results"
USERS_FILE = DATA_DIR / "users.json"
CHECKS_FILE = DATA_DIR / "checks_count.json"
BANS_FILE = DATA_DIR / "ban.json"
STATS_FILE = DATA_DIR / "proxy_stats.json"

GEO_DB = "GeoLite2-Country.mmdb"

TEST_URL = "https://api.ipify.org?format=json"
TIMEOUT = aiohttp.ClientTimeout(total=8)
SEM = asyncio.Semaphore(30)
# =========================================


# ================= STORAGE =================
def ensure_file(path, default):
    if not path.exists() or path.stat().st_size == 0:
        path.write_text(json.dumps(default))

def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except:
        path.write_text(json.dumps(default))
        return default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))

DATA_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

ensure_file(USERS_FILE, {})
ensure_file(CHECKS_FILE, {"total": 0})
ensure_file(BANS_FILE, [])
ensure_file(STATS_FILE, {})

users = load_json(USERS_FILE, {})
checks_count = load_json(CHECKS_FILE, {"total": 0})
banned_users = set(load_json(BANS_FILE, []))
proxy_stats = load_json(STATS_FILE, {})
# =========================================


# ================= GEO =================
geo_reader = geoip2.database.Reader(GEO_DB)

def get_country(ip):
    try:
        r = geo_reader.country(ip)
        return r.country.iso_code, r.country.name
    except:
        return "??", "Unknown"
# =========================================


# ================= FORCE JOIN =================
async def check_force_join(bot, user_id):
    for ch in FORCE_JOIN_CHANNELS:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status not in ("member", "administrator", "creator"):
                return False
        except:
            return False
    return True
# =============================================


# ================= PROXY PARSER =================
def parse_proxy(line, ptype):
    line = line.strip()
    if not line:
        return None

    if line.startswith(("http://", "https://", "socks4://", "socks5://")):
        return ptype, line

    parts = line.split(":")

    if len(parts) == 4:
        ip, port, user, pwd = parts
        return ptype, f"{ptype}://{user}:{pwd}@{ip}:{port}"

    if "@" in line:
        return ptype, f"{ptype}://{line}"

    if len(parts) == 2:
        return ptype, f"{ptype}://{line}"

    return None
# ===============================================


# ================= SCORE =================
def speed_score(ms):
    if ms < 300:
        return 100
    if ms < 600:
        return 80
    if ms < 1000:
        return 50
    return 20

def smart_score(ms, success, total):
    uptime = (success / total) * 100 if total else 0
    return int(speed_score(ms) * 0.6 + uptime * 0.4)
# ===============================================


# ================= PROXY CHECK =================
async def check_proxy(proxy_type, proxy_url):
    start = time.time()
    try:
        async with SEM:
            if proxy_type in ("http", "https"):
                async with aiohttp.ClientSession(timeout=TIMEOUT) as s:
                    async with s.get(TEST_URL, proxy=proxy_url, ssl=False) as r:
                        if r.status == 200:
                            ip = (await r.json())["ip"]
                            return True, ip, int((time.time() - start) * 1000)

            else:
                conn = ProxyConnector.from_url(proxy_url)
                async with aiohttp.ClientSession(connector=conn, timeout=TIMEOUT) as s:
                    async with s.get(TEST_URL, ssl=False) as r:
                        if r.status == 200:
                            ip = (await r.json())["ip"]
                            return True, ip, int((time.time() - start) * 1000)

    except:
        pass

    return False, None, None
# ===============================================


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not await check_force_join(context.bot, uid):
        kb = [
            [InlineKeyboardButton("📢 Join @legendyt830", url="https://t.me/legendyt830")],
            [InlineKeyboardButton("📢 Join @youXyash", url="https://t.me/youXyash")],
            [InlineKeyboardButton("✅ I Joined", callback_data="recheck")],
        ]
        await update.message.reply_text(
            "🔒 **Join both channels to continue**",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown",
        )
        return

    kb = [
        [InlineKeyboardButton("🌐 HTTP", callback_data="ptype_http")],
        [InlineKeyboardButton("🔐 HTTPS", callback_data="ptype_https")],
        [InlineKeyboardButton("🧦 SOCKS4", callback_data="ptype_socks4")],
        [InlineKeyboardButton("🧦 SOCKS5", callback_data="ptype_socks5")],
    ]
    await update.message.reply_text(
        "🧠 **Select Proxy Type**",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown",
    )

async def recheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if await check_force_join(context.bot, update.effective_user.id):
        await update.callback_query.message.edit_text("✅ Access granted\n\nSend /start")

async def select_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["ptype"] = q.data.replace("ptype_", "")
    await q.message.edit_text(
        "📤 Upload proxy `.txt`\n\n"
        "`ip:port`\n"
        "`user:pass@ip:port`\n"
        "`ip:port:user:pass`",
        parse_mode="Markdown",
    )
# ===============================================


# ================= FILE HANDLER =================
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    ptype = context.user_data.get("ptype")

    if not ptype:
        await update.message.reply_text("❗ Select proxy type first using /start")
        return

    doc = update.message.document
    file = await doc.get_file()
    raw = (await file.download_as_bytearray()).decode(errors="ignore")

    parsed = [parse_proxy(l, ptype) for l in raw.splitlines()]
    proxies = [p for p in parsed if p]

    user_dir = RESULTS_DIR / uid
    user_dir.mkdir(exist_ok=True)

    live_data = []

    msg = await update.message.reply_text("⏳ Checking... 0%")

    for i, (ptype, purl) in enumerate(proxies, 1):
        ok, ip, ms = await check_proxy(ptype, purl)

        stats = proxy_stats.setdefault(purl, {"ok": 0, "total": 0})
        stats["total"] += 1

        if ok:
            stats["ok"] += 1
            cc, cn = get_country(ip)
            score = smart_score(ms, stats["ok"], stats["total"])
            live_data.append((score, ms, cc, cn, purl))

        await msg.edit_text(f"⏳ {int(i/len(proxies)*100)}%")

    save_json(STATS_FILE, proxy_stats)

    ranked = sorted(live_data, reverse=True)

    out = []
    for score, ms, cc, cn, p in ranked:
        out.append(f"{p} | {ms}ms | {cc} {cn} | Score {score}")

    (user_dir / "ranked.txt").write_text("\n".join(out))

    await msg.edit_text(
        f"✅ Done\n🟢 Live: {len(out)}\n🔴 Dead: {len(proxies)-len(out)}"
    )

    if out:
        await update.message.reply_document(
            document=(user_dir / "ranked.txt").open("rb"),
            caption="🏆 Ranked Proxies",
        )
# ===============================================


# ================= MAIN =================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(recheck, pattern="recheck"))
    app.add_handler(CallbackQueryHandler(select_type, pattern="ptype_"))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_file))

    print("✅ Bot running")
    app.run_polling()

if __name__ == "__main__":
    main()