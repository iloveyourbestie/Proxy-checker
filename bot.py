import os
import json
import time
import asyncio
import aiohttp
from pathlib import Path
from aiohttp_socks import ProxyConnector
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

FORCE_JOIN_CHANNELS = [
    "@legendyt830",
    "@youXyash",
]

DATA_DIR = Path("data")
RESULTS_DIR = DATA_DIR / "results"
USERS_FILE = DATA_DIR / "users.json"
CHECKS_FILE = DATA_DIR / "checks_count.json"
BANS_FILE = DATA_DIR / "ban.json"

TIMEOUT = aiohttp.ClientTimeout(total=8)
SEM = asyncio.Semaphore(30)
TEST_URL = "https://api.ipify.org?format=json"
# =========================================


# ================= STORAGE =================
def ensure_storage():
    DATA_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)

    for file, default in [
        (USERS_FILE, {}),
        (CHECKS_FILE, {"total": 0}),
        (BANS_FILE, []),
    ]:
        if not file.exists() or file.stat().st_size == 0:
            file.write_text(json.dumps(default))

def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except:
        path.write_text(json.dumps(default))
        return default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))

ensure_storage()

users = load_json(USERS_FILE, {})
checks_count = load_json(CHECKS_FILE, {"total": 0})
banned_users = set(load_json(BANS_FILE, []))
# =========================================


# ================= FORCE JOIN =================
async def is_member(bot, user_id):
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
def parse_proxy(line: str):
    line = line.strip()
    if not line:
        return None

    # Detect auth
    auth = "@" in line

    # Detect scheme
    if line.startswith("http://"):
        return "http", line
    if line.startswith("https://"):
        return "https", line
    if line.startswith("socks4://"):
        return "socks4", line
    if line.startswith("socks5://"):
        return "socks5", line

    # Guess based on port / auth
    if auth:
        return "http", "http://" + line

    return "http", "http://" + line
# ===============================================


# ================= PROXY CHECK =================
async def check_proxy(proxy_type, proxy_url):
    start = time.time()

    try:
        async with SEM:
            if proxy_type in ("http", "https"):
                async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                    async with session.get(
                        TEST_URL,
                        proxy=proxy_url,
                        ssl=False,
                    ) as r:
                        if r.status == 200:
                            latency = int((time.time() - start) * 1000)
                            return True, latency

            else:  # SOCKS4 / SOCKS5
                connector = ProxyConnector.from_url(proxy_url)
                async with aiohttp.ClientSession(
                    connector=connector,
                    timeout=TIMEOUT
                ) as session:
                    async with session.get(TEST_URL, ssl=False) as r:
                        if r.status == 200:
                            latency = int((time.time() - start) * 1000)
                            return True, latency

    except:
        pass

    return False, None
# ===============================================


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if uid in banned_users:
        return

    users[uid] = users.get(uid, 0) + 1
    save_json(USERS_FILE, users)

    await update.message.reply_text(
        "👋 **Proxy Checker Bot**\n\n"
        "⚡ HTTP / HTTPS / SOCKS4 / SOCKS5\n"
        "🔐 Private proxy supported\n\n"
        "📌 Commands:\n"
        "/check – Start checking\n"
        "/history – Your results",
        parse_mode="Markdown",
    )

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if str(uid) in banned_users:
        return

    if not await is_member(context.bot, uid):
        buttons = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{c[1:]}")]
            for c in FORCE_JOIN_CHANNELS
        ]
        buttons.append([InlineKeyboardButton("✅ I Joined", callback_data="recheck")])

        await update.message.reply_text(
            "🔒 **Join required channels first**",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        "📤 **Upload proxy .txt file**\n\n"
        "Supported formats:\n"
        "`ip:port`\n"
        "`user:pass@ip:port`\n"
        "`socks5://ip:port`",
        parse_mode="Markdown",
    )

async def recheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    if await is_member(context.bot, update.effective_user.id):
        await update.callback_query.message.edit_text(
            "✅ Access granted\n\nSend /check again"
        )
# ===============================================


# ================= FILE HANDLER =================
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    doc = update.message.document
    file = await doc.get_file()
    raw = (await file.download_as_bytearray()).decode(errors="ignore")

    parsed = [parse_proxy(l) for l in raw.splitlines()]
    proxies = [p for p in parsed if p]

    total = len(proxies)
    if total == 0:
        return

    user_dir = RESULTS_DIR / str(uid)
    user_dir.mkdir(exist_ok=True)

    live, dead = [], []

    msg = await update.message.reply_text("⏳ Checking... 0%")
    start_time = time.time()

    for i, (ptype, purl) in enumerate(proxies, 1):
        ok, latency = await check_proxy(ptype, purl)
        if ok:
            live.append(f"{purl} | {latency}ms")
        else:
            dead.append(purl)

        if i % 5 == 0 or i == total:
            percent = int(i / total * 100)
            await msg.edit_text(f"⏳ Checking... {percent}%")

        await asyncio.sleep(0.05)

    (user_dir / "live.txt").write_text("\n".join(live))
    (user_dir / "dead.txt").write_text("\n".join(dead))

    checks_count["total"] += total
    save_json(CHECKS_FILE, checks_count)

    elapsed = max(1, time.time() - start_time)
    cpm = int((total / elapsed) * 60)

    await msg.edit_text(
        f"✅ **Check Completed**\n\n"
        f"🟢 Live: {len(live)}\n"
        f"🔴 Dead: {len(dead)}\n"
        f"⚡ CPM: {cpm}",
        parse_mode="Markdown",
    )

    if live:
        await update.message.reply_document(
            document=(user_dir / "live.txt").open("rb"),
            caption="🟢 Live Proxies",
        )
# ===============================================


# ================= MAIN =================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CallbackQueryHandler(recheck, pattern="recheck"))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), handle_file))

    print("✅ Bot running")
    app.run_polling()

if __name__ == "__main__":
    main()