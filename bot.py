import os
import json
import asyncio
import aiohttp
from pathlib import Path
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # REQUIRED
OWNER_ID = 8537424608

FORCE_JOIN_CHANNELS = [
    "legendyt830",
    "youXyash",
]

DATA_DIR = Path("data")
RESULTS_DIR = DATA_DIR / "results"
USERS_FILE = DATA_DIR / "users.json"
CHECKS_FILE = DATA_DIR / "checks_count.json"
BANS_FILE = DATA_DIR / "banned_users.json"

SEM = asyncio.Semaphore(100)
# ========================================


# ============ STORAGE INIT ===============
def ensure_json(path, default):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default))
        return default

    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        path.write_text(json.dumps(default))
        return default


users = ensure_json(USERS_FILE, {})
checks_count = ensure_json(CHECKS_FILE, {"total": 0})
banned_users = ensure_json(BANS_FILE, [])
# ========================================


# ============ FORCE JOIN =================
async def check_force_join(context, user_id):
    for ch in FORCE_JOIN_CHANNELS:
        try:
            member = await context.bot.get_chat_member(f"@{ch}", user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except:
            return False
    return True
# ========================================


# ============ ASYNC PROXY CHECK ==========
async def check_proxy(session, proxy, proxy_type):
    url = "http://httpbin.org/ip"
    proxy_url = f"{proxy_type}://{proxy}"

    try:
        async with SEM:
            async with session.get(
                url,
                proxy=proxy_url,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status == 200:
                    return proxy, True
    except:
        pass
    return proxy, False


async def run_check(proxies, proxy_type, progress_cb):
    good, bad = [], []

    async with aiohttp.ClientSession() as session:
        tasks = [
            check_proxy(session, p.strip(), proxy_type)
            for p in proxies if p.strip()
        ]

        total = len(tasks)
        done = 0

        for coro in asyncio.as_completed(tasks):
            proxy, ok = await coro
            done += 1

            if ok:
                good.append(proxy)
            else:
                bad.append(proxy)

            if done % 10 == 0 or done == total:
                await progress_cb(done, total)

    return good, bad
# ========================================


# ============ COMMANDS ===================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    if uid in banned_users:
        return

    users[uid] = True
    USERS_FILE.write_text(json.dumps(users))

    await update.message.reply_text(
        "👋 Welcome!\n\nUse /check to start proxy checking."
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Stats\n\n"
        f"👤 Users: {len(users)}\n"
        f"🔎 Checks: {checks_count['total']}\n"
        f"🚫 Banned: {len(banned_users)}"
    )


async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        return

    uid = context.args[0]
    if uid not in banned_users:
        banned_users.append(uid)
        BANS_FILE.write_text(json.dumps(banned_users))

    await update.message.reply_text("🚫 User banned")


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        return

    uid = context.args[0]
    if uid in banned_users:
        banned_users.remove(uid)
        BANS_FILE.write_text(json.dumps(banned_users))

    await update.message.reply_text("✅ User unbanned")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    user_dir = RESULTS_DIR / uid

    if not user_dir.exists():
        await update.message.reply_text("📭 No history yet")
        return

    files = list(user_dir.glob("*.txt"))
    if not files:
        await update.message.reply_text("📭 No history yet")
        return

    msg = "📜 Your history:\n\n"
    for f in files:
        msg += f"• {f.name}\n"

    await update.message.reply_text(msg)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    kb = [
        [InlineKeyboardButton("👤 Users", callback_data="a_users")],
        [InlineKeyboardButton("📊 Checks", callback_data="a_checks")],
        [InlineKeyboardButton("🚫 Banned", callback_data="a_banned")],
    ]

    await update.message.reply_text(
        "🛠 Admin Panel",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "a_users":
        await q.message.reply_text(f"👤 Users: {len(users)}")
    elif q.data == "a_checks":
        await q.message.reply_text(f"📊 Checks: {checks_count['total']}")
    elif q.data == "a_banned":
        await q.message.reply_text(f"🚫 Banned: {len(banned_users)}")
# ========================================


# ============ CHECK FLOW =================
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if str(uid) in banned_users:
        return

    if not await check_force_join(context, uid):
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I Joined", callback_data="recheck")]
        ])
        await update.message.reply_text(
            "❌ Join required channels first.",
            reply_markup=btn
        )
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("HTTP", callback_data="http")],
        [InlineKeyboardButton("HTTPS", callback_data="https")],
        [InlineKeyboardButton("SOCKS5", callback_data="socks5")],
    ])

    await update.message.reply_text("Select proxy type:", reply_markup=kb)


async def proxy_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["ptype"] = q.data
    await q.message.reply_text("📄 Upload .txt file")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    ptype = context.user_data.get("ptype")
    if not ptype:
        return

    file = await update.message.document.get_file()
    content = (await file.download_as_bytearray()).decode().splitlines()

    user_dir = RESULTS_DIR / uid
    user_dir.mkdir(parents=True, exist_ok=True)

    status = await update.message.reply_text("⏳ Checking...")

    async def prog(d, t):
        percent = int((d / t) * 100)
        await status.edit_text(f"⏳ Progress: {percent}%")

    good, bad = await run_check(content, ptype, prog)

    out = user_dir / f"{ptype}_checked.txt"
    out.write_text("\n".join(good))

    checks_count["total"] += len(content)
    CHECKS_FILE.write_text(json.dumps(checks_count))

    await status.edit_text(
        f"✅ Done\n\n"
        f"✔ Working: {len(good)}\n"
        f"❌ Dead: {len(bad)}"
    )

    await update.message.reply_document(out.open("rb"))
# ========================================


# ============ MAIN =======================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("check", check))

    app.add_handler(CallbackQueryHandler(proxy_type, pattern="^(http|https|socks5)$"))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^a_"))
    app.add_handler(CallbackQueryHandler(lambda u, c: check(u, c), pattern="^recheck$"))

    app.add_handler(
        MessageHandler(
            filters.Document.FileExtension("txt"),
            handle_file,
        )
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()