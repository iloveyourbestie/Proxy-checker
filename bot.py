import os
import json
import time
import asyncio
import logging
import aiohttp
import requests
import tarfile
import re
from datetime import datetime
from collections import defaultdict

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

# ================== ENHANCED LOGGING ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ================== FIXED STORAGE WITH AUTO CREATION ==================

def ensure_storage():
    """Ensure all storage directories and files exist with proper structure"""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    # Create all JSON files with proper defaults
    json_files = {
        "users.json": {},
        "checks_count.json": {
            "total": 0,
            "today": 0,
            "last_reset": datetime.now().strftime("%Y-%m-%d")
        },
        "ban.json": [],
        "uptime.json": {},
        "user_stats.json": {},
        "proxies_db.json": {}
    }
    
    for filename, default_data in json_files.items():
        filepath = f"{DATA_DIR}/{filename}"
        
        # Create file if it doesn't exist
        if not os.path.exists(filepath):
            logger.info(f"📁 Creating {filename} with default data")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(default_data, f, indent=2, ensure_ascii=False)
        else:
            # If file exists but is empty, recreate it
            if os.path.getsize(filepath) == 0:
                logger.warning(f"📁 {filename} is empty, recreating")
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(default_data, f, indent=2, ensure_ascii=False)
            else:
                # Fix existing files that might have wrong structure
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # Special fix for checks_count.json
                    if filename == "checks_count.json":
                        if "last_reset" not in data:
                            data["last_reset"] = datetime.now().strftime("%Y-%m-%d")
                            logger.info(f"🔧 Fixed missing 'last_reset' in {filename}")
                        if "today" not in data:
                            data["today"] = 0
                            logger.info(f"🔧 Fixed missing 'today' in {filename}")
                        if "total" not in data:
                            data["total"] = 0
                            logger.info(f"🔧 Fixed missing 'total' in {filename}")
                        
                        # Save fixed data
                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                            
                except json.JSONDecodeError:
                    logger.error(f"❌ {filename} has invalid JSON, recreating")
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(default_data, f, indent=2, ensure_ascii=False)

def load(name):
    """Load JSON file with error handling and auto-fix"""
    try:
        filepath = f"{DATA_DIR}/{name}"
        if not os.path.exists(filepath):
            ensure_storage()  # Recreate if missing
            
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Special handling for checks_count.json
        if name == "checks_count.json":
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Ensure all required keys exist
            if "last_reset" not in data:
                data["last_reset"] = today
            if "today" not in data:
                data["today"] = 0
            if "total" not in data:
                data["total"] = 0
                
            # Reset today's count if it's a new day
            if data["last_reset"] != today:
                data["today"] = 0
                data["last_reset"] = today
                save(name, data)  # Save immediately
                
        return data
        
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Error loading {name}: {e}")
        ensure_storage()  # Recreate files
        return {}

def save(name, data):
    """Save JSON file with error handling"""
    try:
        with open(f"{DATA_DIR}/{name}", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"Error saving {name}: {e}")
        # Try to save with backup
        backup_file = f"{DATA_DIR}/{name}.backup"
        try:
            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except:
            pass

# ================== PROXY PARSER ==================

class ProxyParser:
    @staticmethod
    def parse_proxy(proxy_str):
        """
        Parse various proxy formats:
        1. ip:port
        2. user:pass@ip:port
        3. ip:port:user:pass
        4. ip:port:user:pass:type (some providers)
        """
        proxy_str = proxy_str.strip()
        
        # Clean up any extra spaces or quotes
        proxy_str = proxy_str.replace('"', '').replace("'", '')
        
        # Pattern 1: ip:port:user:pass
        if proxy_str.count(':') == 3:
            parts = proxy_str.split(':')
            if len(parts) == 4:
                ip, port, user, password = parts
                return {
                    'ip': ip,
                    'port': port,
                    'user': user,
                    'password': password,
                    'original': f"{user}:{password}@{ip}:{port}",
                    'format': 'auth'
                }
        
        # Pattern 2: user:pass@ip:port
        elif '@' in proxy_str:
            auth_part, host_part = proxy_str.split('@')
            if ':' in auth_part and ':' in host_part:
                user, password = auth_part.split(':')
                ip, port = host_part.split(':')
                return {
                    'ip': ip,
                    'port': port,
                    'user': user,
                    'password': password,
                    'original': proxy_str,
                    'format': 'auth'
                }
        
        # Pattern 3: ip:port (no auth)
        elif proxy_str.count(':') == 1:
            ip, port = proxy_str.split(':')
            return {
                'ip': ip,
                'port': port,
                'user': None,
                'password': None,
                'original': proxy_str,
                'format': 'no_auth'
            }
        
        # Pattern 4: Try to extract IP:PORT from messy string
        else:
            # Try to find IP:PORT pattern
            ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
            port_pattern = r':(\d{2,5})'
            
            ip_match = re.search(ip_pattern, proxy_str)
            port_match = re.search(port_pattern, proxy_str)
            
            if ip_match and port_match:
                ip = ip_match.group()
                port = port_match.group(1)
                return {
                    'ip': ip,
                    'port': port,
                    'user': None,
                    'password': None,
                    'original': f"{ip}:{port}",
                    'format': 'extracted'
                }
        
        return None

    @staticmethod
    def normalize_proxy(proxy_info):
        """Convert proxy info to standard format"""
        if proxy_info['user'] and proxy_info['password']:
            return f"{proxy_info['user']}:{proxy_info['password']}@{proxy_info['ip']}:{proxy_info['port']}"
        else:
            return f"{proxy_info['ip']}:{proxy_info['port']}"

# ================== GEO DB AUTO DOWNLOAD & UPDATE ==================

def ensure_geolite_db():
    if os.path.exists(GEO_DB):
        # Check if DB is older than 7 days
        db_age = time.time() - os.path.getmtime(GEO_DB)
        if db_age < 604800:  # 7 days in seconds
            return
        
        logger.info("🔄 GeoLite2 City database is old, updating...")
    
    logging.info("⬇️ Downloading GeoLite2 City database")

    url = "https://download.maxmind.com/app/geoip_download"
    params = {
        "edition_id": "GeoLite2-City",
        "license_key": MAXMIND_LICENSE_KEY,
        "suffix": "tar.gz",
    }

    try:
        r = requests.get(
            url,
            params=params,
            auth=(MAXMIND_ACCOUNT_ID, MAXMIND_LICENSE_KEY),
            timeout=60,
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
                    os.rename(f"{DATA_DIR}/{m.name}", GEO_DB)

        os.remove(tar_path)
        logging.info("✅ GeoLite2 City database updated successfully")
        
    except Exception as e:
        logging.error(f"❌ Failed to update GeoLite2 database: {e}")
        if not os.path.exists(GEO_DB):
            raise

# ================== ENHANCED GEO LOOKUP ==================

geo_reader = None

def geo_lookup(ip):
    try:
        r = geo_reader.city(ip)
        country = r.country.name or "Unknown"
        city = r.city.name or "Unknown"
        isp = r.traits.isp or "Unknown"
        asn = r.traits.autonomous_system_number or "Unknown"
        aso = r.traits.autonomous_system_organization or "Unknown"
        
        return {
            "country": country,
            "city": city,
            "isp": isp,
            "asn": asn,
            "aso": aso
        }
    except Exception as e:
        logger.error(f"Geo lookup failed for {ip}: {e}")
        return {
            "country": "Unknown",
            "city": "Unknown",
            "isp": "Unknown",
            "asn": "Unknown",
            "aso": "Unknown"
        }

# ================== FORCE JOIN WITH CACHE ==================

class ChannelChecker:
    def __init__(self):
        self.cache = {}
        self.cache_time = {}
        self.cache_duration = 300  # 5 minutes cache
        
    async def is_joined(self, bot, uid):
        current_time = time.time()
        
        # Check cache
        if uid in self.cache and current_time - self.cache_time.get(uid, 0) < self.cache_duration:
            return self.cache[uid]
            
        for ch in REQUIRED_CHANNELS:
            try:
                m = await bot.get_chat_member(ch, uid)
                if m.status not in ("member", "administrator", "creator"):
                    self.cache[uid] = False
                    self.cache_time[uid] = current_time
                    return False
            except Exception as e:
                logger.error(f"Failed to check membership for {uid} in {ch}: {e}")
                self.cache[uid] = False
                self.cache_time[uid] = current_time
                return False
                
        self.cache[uid] = True
        self.cache_time[uid] = current_time
        return True

channel_checker = ChannelChecker()

# ================== ENHANCED SMART SCORE ==================

def smart_score(latency, uptime, success_rate=100, proxy_type="http"):
    """
    Enhanced scoring algorithm:
    - Base score: 100 - latency penalty
    - Uptime bonus: increases with consistency
    - Success rate bonus
    - Proxy type multiplier
    """
    # Latency penalty (more aggressive for high latency)
    latency_penalty = min(latency / 5, 60)
    
    # Uptime bonus (logarithmic growth)
    uptime_bonus = min(uptime * 8, 30)
    
    # Success rate bonus
    success_bonus = success_rate * 0.2
    
    # Proxy type multiplier
    type_multiplier = {
        "socks5": 1.2,
        "socks4": 1.1,
        "https": 1.15,
        "http": 1.0
    }.get(proxy_type, 1.0)
    
    base_score = (100 - latency_penalty + uptime_bonus + success_bonus)
    return round(base_score * type_multiplier, 2)

# ================== ENHANCED PROXY CHECKER ==================

class ProxyChecker:
    def __init__(self):
        self.test_urls = [
            "http://httpbin.org/ip",
            "http://api.ipify.org?format=json",
            "http://ip-api.com/json/"
        ]
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    
    async def test_proxy(self, proxy_url, proxy_type):
        """Test a proxy with given type and URL"""
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT, headers=self.headers) as session:
                async with session.get(
                    "http://httpbin.org/ip",
                    proxy=proxy_url,
                    ssl=False,
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        if "origin" in data:
                            return True
        except Exception as e:
            logger.debug(f"Proxy test failed: {e}")
        return False
    
    async def check_proxy_with_type(self, proxy_str, proxy_type):
        """Check proxy with specific protocol type"""
        start = time.time()
        
        # Parse proxy
        proxy_info = ProxyParser.parse_proxy(proxy_str)
        if not proxy_info:
            return None
        
        ip = proxy_info['ip']
        
        # Format proxy URL based on type
        if proxy_info['user'] and proxy_info['password']:
            if proxy_type in ["socks4", "socks5"]:
                proxy_url = f"{proxy_type}://{proxy_info['user']}:{proxy_info['password']}@{proxy_info['ip']}:{proxy_info['port']}"
            else:
                proxy_url = f"{proxy_type}://{proxy_info['user']}:{proxy_info['password']}@{proxy_info['ip']}:{proxy_info['port']}"
        else:
            proxy_url = f"{proxy_type}://{proxy_info['ip']}:{proxy_info['port']}"
        
        successful_tests = 0
        total_tests = len(self.test_urls)
        
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT, headers=self.headers) as session:
                for test_url in self.test_urls:
                    try:
                        async with session.get(
                            test_url,
                            proxy=proxy_url,
                            ssl=False,
                        ) as r:
                            if r.status == 200:
                                successful_tests += 1
                    except:
                        continue
                
                if successful_tests > 0:
                    latency = int((time.time() - start) * 1000)
                    geo_info = geo_lookup(ip)
                    
                    # Calculate success rate
                    success_rate = (successful_tests / total_tests) * 100
                    
                    result = {
                        "proxy": ProxyParser.normalize_proxy(proxy_info),
                        "original": proxy_str,
                        "latency": latency,
                        "country": geo_info["country"],
                        "city": geo_info["city"],
                        "isp": geo_info["isp"],
                        "asn": geo_info["asn"],
                        "aso": geo_info["aso"],
                        "success_rate": success_rate,
                        "checks_passed": successful_tests,
                        "total_checks": total_tests,
                        "type": proxy_type,
                        "has_auth": proxy_info['user'] is not None,
                        "timestamp": datetime.now().isoformat()
                    }
                    return result
        except Exception as e:
            logger.debug(f"Proxy {proxy_str} failed with {proxy_type}: {e}")
        
        return None
    
    async def auto_check_proxy(self, proxy_str):
        """
        Automatically detect and check proxy with all protocols
        Returns the best working result
        """
        proxy_types = ["socks5", "socks4", "http", "https"]
        results = []
        
        # Try all protocols in parallel
        tasks = []
        for ptype in proxy_types:
            task = asyncio.create_task(self.check_proxy_with_type(proxy_str, ptype))
            tasks.append(task)
        
        # Wait for first successful result
        for task in asyncio.as_completed(tasks):
            result = await task
            if result:
                return result
        
        return None
    
    async def check_all_types(self, proxy_str):
        """Check proxy with all types and return all working results"""
        proxy_types = ["socks5", "socks4", "http", "https"]
        results = []
        
        tasks = [self.check_proxy_with_type(proxy_str, ptype) for ptype in proxy_types]
        proxy_results = await asyncio.gather(*tasks)
        
        for result in proxy_results:
            if result:
                results.append(result)
        
        # Sort by latency (fastest first)
        results.sort(key=lambda x: x["latency"])
        return results

proxy_checker = ProxyChecker()

# ================== ENHANCED HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or "No username"
    
    if not await channel_checker.is_joined(context.bot, uid):
        kb = [
            [InlineKeyboardButton("📢 Join Channel 1", url="https://t.me/legendyt830")],
            [InlineKeyboardButton("📢 Join Channel 2", url="https://t.me/youXyash")],
            [InlineKeyboardButton("✅ Verify Join", callback_data="recheck")]
        ]
        return await update.message.reply_text(
            "🔒 *ACCESS REQUIRED*\n\n"
            "To use this bot, you must join our channels:\n"
            "• @legendyt830\n"
            "• @youXyash\n\n"
            "Join both channels and click Verify Join.",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )

    # Update user stats
    users = load("users.json")
    users[str(uid)] = {
        "first_seen": int(time.time()),
        "username": username,
        "last_active": int(time.time()),
        "checks_made": users.get(str(uid), {}).get("checks_made", 0)
    }
    save("users.json", users)

    await update.message.reply_text(
        "🚀 *ULTIMATE PROXY CHECKER*\n\n"
        "⚡ *Features:*\n"
        "• Auto-detection for mixed proxy files\n"
        "• Supports all formats: ip:port, user:pass@ip:port, ip:port:user:pass\n"
        "• Tests HTTP, HTTPS, SOCKS4, SOCKS5 automatically\n"
        "• Smart scoring system\n"
        "• Progress tracking with ETA\n\n"
        "📁 *Supported Formats:*\n"
        "• `23.27.208.120:5830`\n"
        "• `user:pass@23.27.208.120:5830`\n"
        "• `23.27.208.120:5830:lxpvdagm:7ywyhfp6fcvs`\n\n"
        "📊 *Commands:*\n"
        "• /check - Start checking proxies\n"
        "• /stats - Your statistics\n"
        "• /help - Show help message",
        parse_mode="Markdown"
    )

async def recheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    
    if await channel_checker.is_joined(context.bot, uid):
        await q.message.edit_text(
            "✅ *Access Granted!*\n\n"
            "You can now use the bot. Send /check to start checking proxies.",
            parse_mode="Markdown"
        )
    else:
        kb = [
            [InlineKeyboardButton("📢 Join Channel 1", url="https://t.me/legendyt830")],
            [InlineKeyboardButton("📢 Join Channel 2", url="https://t.me/youXyash")],
            [InlineKeyboardButton("🔄 Verify Again", callback_data="recheck")]
        ]
        await q.message.edit_text(
            "❌ *Still Not Joined*\n\n"
            "Please join both required channels and try again.",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🤖 AUTO DETECT (RECOMMENDED)", callback_data="auto")],
        [InlineKeyboardButton("🌐 HTTP", callback_data="http")],
        [InlineKeyboardButton("🔒 HTTPS", callback_data="https")],
        [InlineKeyboardButton("🧦 SOCKS4", callback_data="socks4")],
        [InlineKeyboardButton("🧦 SOCKS5", callback_data="socks5")],
        [InlineKeyboardButton("📊 ALL TYPES", callback_data="all")]
    ]
    await update.message.reply_text(
        "🔧 *Select Checking Mode*\n\n"
        "🤖 **Auto Detect (Recommended):**\n"
        "• Perfect for mixed proxy files\n"
        "• Tests all protocols automatically\n"
        "• Supports any proxy format\n\n"
        "📊 **All Types:**\n"
        "• Tests each proxy with all 4 protocols\n"
        "• Returns fastest working protocol\n\n"
        "Or select specific type below:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def proxy_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data["ptype"] = q.data
    
    if q.data == "auto":
        await q.message.edit_text(
            "📤 *Upload Mixed Proxy File*\n\n"
            "🤖 **Auto Mode Activated**\n\n"
            "Send a `.txt` file containing ANY proxy format:\n"
            "• Mixed HTTP/HTTPS/SOCKS4/SOCKS5\n"
            "• With or without authentication\n"
            "• All formats supported!\n\n"
            "📝 **Supported Formats:**\n"
            "```\n"
            "23.27.208.120:5830\n"
            "user:pass@45.67.89.10:3128\n"
            "98.76.54.32:1080:username:password\n"
            "socks5://proxy.example.com:8080\n"
            "```\n\n"
            "The bot will automatically detect and test all protocols.",
            parse_mode="Markdown"
        )
    elif q.data == "all":
        await q.message.edit_text(
            "📤 *Upload Proxy File*\n\n"
            "📊 **All Types Mode**\n\n"
            "Each proxy will be tested with:\n"
            "• HTTP\n• HTTPS\n• SOCKS4\n• SOCKS5\n\n"
            "Returns the fastest working protocol for each proxy.\n\n"
            "📝 **Format:** `ip:port` or `user:pass@ip:port`",
            parse_mode="Markdown"
        )
    else:
        type_name = {
            "http": "HTTP",
            "https": "HTTPS",
            "socks4": "SOCKS4",
            "socks5": "SOCKS5"
        }.get(q.data, q.data.upper())
        
        await q.message.edit_text(
            f"📤 *Upload {type_name} Proxy File*\n\n"
            f"Only {type_name} proxies will be tested.\n"
            f"📝 **Format:** `ip:port` or `user:pass@ip:port`",
            parse_mode="Markdown"
        )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    ptype = context.user_data.get("ptype")
    
    if not ptype:
        return await update.message.reply_text(
            "❌ Please select checking mode first using /check"
        )

    try:
        # Download file
        file = await update.message.document.get_file()
        content = (await file.download_as_bytearray()).decode().splitlines()
        
        # Parse and clean proxies
        raw_proxies = []
        parsed_proxies = []
        
        for line in content:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("//"):
                # Try to parse the proxy
                proxy_info = ProxyParser.parse_proxy(line)
                if proxy_info:
                    raw_proxies.append(line)
                    parsed_proxies.append(proxy_info)
                elif ':' in line:  # Basic validation
                    raw_proxies.append(line)
        
        if not raw_proxies:
            return await update.message.reply_text(
                "❌ No valid proxies found in file.\n"
                "Supported formats:\n"
                "• ip:port\n• user:pass@ip:port\n• ip:port:user:pass"
            )
        
        logger.info(f"User {username} ({uid}) checking {len(raw_proxies)} proxies in {ptype} mode")
        
        # Create progress message
        progress_msg = await update.message.reply_text(
            f"⏳ *Initializing Check*\n\n"
            f"📊 Total: {len(raw_proxies)} proxies\n"
            f"🔧 Mode: {ptype.upper()}\n"
            f"📝 Format: Mixed/Auto\n"
            f"⏱️ Preparing...",
            parse_mode="Markdown"
        )
        
        # Update user stats - FIXED: Use get with defaults
        user_stats = load("user_stats.json")
        if str(uid) not in user_stats:
            user_stats[str(uid)] = {"total_checks": 0, "live_proxies": 0, "files_checked": 0}
        user_stats[str(uid)]["files_checked"] = user_stats[str(uid)].get("files_checked", 0) + 1
        save("user_stats.json", user_stats)
        
        # Check proxies based on mode
        results = []
        checked = 0
        start_time = time.time()
        
        sem = asyncio.Semaphore(MAX_CONCURRENCY)
        
        async def runner(proxy_str):
            nonlocal checked, results
            async with sem:
                try:
                    if ptype == "auto":
                        # Auto mode: try all protocols, return first working one
                        result = await proxy_checker.auto_check_proxy(proxy_str)
                        if result:
                            results.append(result)
                    
                    elif ptype == "all":
                        # All types mode: test all, return fastest
                        type_results = await proxy_checker.check_all_types(proxy_str)
                        if type_results:
                            # Take the fastest (first in sorted list)
                            results.append(type_results[0])
                    
                    else:
                        # Specific type mode
                        result = await proxy_checker.check_proxy_with_type(proxy_str, ptype)
                        if result:
                            results.append(result)
                    
                except Exception as e:
                    logger.error(f"Error checking proxy {proxy_str}: {e}")
                
                checked += 1
                
                # Update progress every 10% or 50 proxies
                if checked % max(len(raw_proxies) // 10, 1) == 0 or checked == len(raw_proxies):
                    elapsed = max(time.time() - start_time, 0.1)
                    cpm = int((checked / elapsed) * 60)
                    eta = int(((len(raw_proxies) - checked) / checked) * elapsed) if checked > 0 else 0
                    
                    progress_percent = int((checked / len(raw_proxies)) * 100)
                    progress_bar = "🟢" * min(progress_percent // 5, 20)
                    progress_bar += "⚪" * (20 - min(progress_percent // 5, 20))
                    
                    try:
                        await progress_msg.edit_text(
                            f"🔍 *Checking Proxies*\n\n"
                            f"📊 Progress: {checked}/{len(raw_proxies)} ({progress_percent}%)\n"
                            f"{progress_bar}\n\n"
                            f"⚡ Speed: {cpm} CPM\n"
                            f"⏱️ ETA: {eta}s\n"
                            f"✅ Live: {len(results)}\n"
                            f"❌ Dead: {checked - len(results)}",
                            parse_mode="Markdown"
                        )
                    except:
                        pass
        
        # Run checks
        await asyncio.gather(*[runner(p) for p in raw_proxies])
        
        # Calculate stats
        total_time = time.time() - start_time
        success_rate = (len(results) / len(raw_proxies) * 100) if raw_proxies else 0
        
        # Update uptime database - FIXED: Use get with defaults
        uptime = load("uptime.json")
        proxies_db = load("proxies_db.json")
        
        for r in results:
            proxy_key = r["proxy"]
            
            # Update uptime with defaults
            if proxy_key not in uptime:
                uptime[proxy_key] = {"success": 1, "total": 1, "first_seen": datetime.now().isoformat()}
            else:
                uptime[proxy_key]["success"] = uptime[proxy_key].get("success", 0) + 1
                uptime[proxy_key]["total"] = uptime[proxy_key].get("total", 0) + 1
            
            # Calculate score
            success_count = uptime[proxy_key].get("success", 0)
            total_count = uptime[proxy_key].get("total", 0)
            success_rate_proxy = (success_count / total_count * 100) if total_count > 0 else 0
            
            r["score"] = smart_score(
                r["latency"], 
                success_count,
                success_rate_proxy,
                r["type"]
            )
            
            # Store in database with defaults
            proxies_db[proxy_key] = {
                "last_seen": datetime.now().isoformat(),
                "country": r.get("country", "Unknown"),
                "isp": r.get("isp", "Unknown"),
                "latency": r.get("latency", 0),
                "score": r.get("score", 0),
                "type": r.get("type", "unknown"),
                "has_auth": r.get("has_auth", False),
                "total_checks": total_count,
                "success_rate": success_rate_proxy
            }
        
        # Sort results by score (highest first)
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        # Save files
        user_dir = f"{RESULTS_DIR}/{uid}"
        os.makedirs(user_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save detailed results
        detailed_out = f"{user_dir}/{ptype}_detailed_{timestamp}.txt"
        with open(detailed_out, "w", encoding="utf-8") as f:
            f.write(f"# Proxy Check Results - {ptype.upper()} Mode\n")
            f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total: {len(raw_proxies)} | Live: {len(results)} | Dead: {len(raw_proxies)-len(results)}\n")
            f.write(f"# Success Rate: {success_rate:.1f}%\n")
            f.write(f"# Time: {total_time:.1f}s\n")
            f.write(f"{'='*80}\n\n")
            
            for i, r in enumerate(results, 1):
                auth_info = " (Auth)" if r.get("has_auth", False) else ""
                f.write(f"{i}. {r.get('proxy', 'Unknown')}{auth_info}\n")
                f.write(f"   ⏱ Latency: {r.get('latency', 0)}ms\n")
                f.write(f"   🌍 Location: {r.get('country', 'Unknown')} / {r.get('city', 'Unknown')}\n")
                f.write(f"   🏢 ISP: {r.get('isp', 'Unknown')}\n")
                f.write(f"   📡 Type: {r.get('type', 'unknown').upper()}\n")
                f.write(f"   ✅ Checks: {r.get('checks_passed', 0)}/{r.get('total_checks', 0)}\n")
                f.write(f"   ⭐ Score: {r.get('score', 0)}\n")
                f.write(f"{'-'*40}\n")
        
        # Save only live proxies (formatted nicely)
        live_out = f"{user_dir}/{ptype}_live_{timestamp}.txt"
        with open(live_out, "w", encoding="utf-8") as f:
            for r in results:
                proxy = r.get("proxy", "")
                proxy_type = r.get("type", "http")
                if proxy:
                    f.write(f"{proxy_type}://{proxy}\n")
        
        # Save stats
        save("uptime.json", uptime)
        save("proxies_db.json", proxies_db)
        
        # Update check counts - FIXED: Use get with defaults
        checks = load("checks_count.json")
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Ensure checks dictionary has all required keys
        if "last_reset" not in checks:
            checks["last_reset"] = today
        if "today" not in checks:
            checks["today"] = 0
        if "total" not in checks:
            checks["total"] = 0
        
        # Reset today's count if it's a new day
        if checks["last_reset"] != today:
            checks["today"] = 0
            checks["last_reset"] = today
        
        # Update counts
        checks["total"] = checks.get("total", 0) + len(raw_proxies)
        checks["today"] = checks.get("today", 0) + len(raw_proxies)
        save("checks_count.json", checks)
        
        # Update user stats with defaults
        user_stats[str(uid)]["total_checks"] = user_stats[str(uid)].get("total_checks", 0) + len(raw_proxies)
        user_stats[str(uid)]["live_proxies"] = user_stats[str(uid)].get("live_proxies", 0) + len(results)
        save("user_stats.json", user_stats)
        
        # Prepare final message
        type_stats = defaultdict(int)
        country_stats = defaultdict(int)
        auth_stats = {"with_auth": 0, "without_auth": 0}
        
        for r in results:
            type_stats[r.get("type", "unknown")] += 1
            country_stats[r.get("country", "Unknown")] += 1
            if r.get("has_auth", False):
                auth_stats["with_auth"] += 1
            else:
                auth_stats["without_auth"] += 1
        
        # Format type breakdown
        type_text = "\n".join([f"  • {t.upper()}: {c}" for t, c in sorted(type_stats.items())]) if type_stats else "  • None"
        
        # Format top countries
        top_countries = sorted(country_stats.items(), key=lambda x: x[1], reverse=True)[:5]
        countries_text = "\n".join([f"  • {c}: {n}" for c, n in top_countries]) if top_countries else "  • None"
        
        # Format auth stats
        auth_text = f"  • With Auth: {auth_stats['with_auth']}\n  • Without Auth: {auth_stats['without_auth']}"
        
        await progress_msg.edit_text(
            f"✅ *Check Complete!*\n\n"
            f"📊 *Results Summary ({ptype.upper()} Mode):*\n"
            f"• Total Proxies: {len(raw_proxies)}\n"
            f"• ✅ Live: {len(results)}\n"
            f"• ❌ Dead: {len(raw_proxies)-len(results)}\n"
            f"• 📈 Success Rate: {success_rate:.1f}%\n"
            f"• ⏱️ Time Taken: {total_time:.1f}s\n\n"
            f"🔧 *Protocol Breakdown:*\n{type_text}\n\n"
            f"🔐 *Authentication:*\n{auth_text}\n\n"
            f"🌍 *Top Countries:*\n{countries_text}\n\n"
            f"📁 *Files Generated:*\n"
            f"1. `live_proxies.txt` - Clean list\n"
            f"2. `detailed_results.txt` - Full report",
            parse_mode="Markdown"
        )
        
        # Send files
        await update.message.reply_document(
            document=open(live_out, "rb"),
            filename=f"live_proxies_{timestamp}.txt",
            caption=f"📄 Live Proxies List ({len(results)} found)"
        )
        
        await update.message.reply_document(
            document=open(detailed_out, "rb"),
            filename=f"detailed_results_{timestamp}.txt",
            caption="📊 Detailed Results Report"
        )
        
    except Exception as e:
        logger.error(f"Error in handle_file: {e}", exc_info=True)
        # Try to send error message
        try:
            await update.message.reply_text(
                f"❌ *Error Processing File*\n\n"
                f"```\n{str(e)[:500]}\n```\n\n"
                f"⚠️ *Possible fixes:*\n"
                f"1. Delete the `data` folder and restart bot\n"
                f"2. Check proxy format matches examples\n"
                f"3. Try smaller file first",
                parse_mode="Markdown"
            )
        except:
            pass

# ================== ENHANCED ADMIN ==================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    
    if uid == OWNER_ID:
        # Owner stats
        users = load("users.json")
        checks = load("checks_count.json")
        user_stats = load("user_stats.json")
        
        # Calculate active users (last 7 days)
        week_ago = time.time() - (7 * 24 * 3600)
        active_users = 0
        for user_id, user_data in users.items():
            if isinstance(user_data, dict):
                last_active = user_data.get("last_active", 0)
            else:
                last_active = user_data
            if last_active > week_ago:
                active_users += 1
        
        await update.message.reply_text(
            f"👑 *ADMIN STATISTICS*\n\n"
            f"📈 *General Stats:*\n"
            f"• Total Users: {len(users)}\n"
            f"• Active Users (7d): {active_users}\n"
            f"• Total Checks: {checks.get('total', 0)}\n"
            f"• Today's Checks: {checks.get('today', 0)}\n\n"
            f"⚙️ *Bot Status:*\n"
            f"• GeoDB: {'✅ Ready' if geo_reader else '❌ Not loaded'}\n"
            f"• Storage: {DATA_DIR}\n"
            f"• Max Concurrency: {MAX_CONCURRENCY}",
            parse_mode="Markdown"
        )
    else:
        # User stats
        user_stats = load("user_stats.json").get(str(uid), {})
        users = load("users.json")
        user_data = users.get(str(uid), {})
        
        checks_made = user_stats.get("total_checks", 0)
        live_found = user_stats.get("live_proxies", 0)
        files_checked = user_stats.get("files_checked", 0)
        
        success_rate = (live_found / checks_made * 100) if checks_made > 0 else 0
        
        if isinstance(user_data, dict):
            first_seen = user_data.get("first_seen", time.time())
            try:
                first_seen_dt = datetime.fromtimestamp(first_seen)
                days_active = (datetime.now() - first_seen_dt).days
            except:
                days_active = "N/A"
        else:
            days_active = "N/A"
        
        await update.message.reply_text(
            f"📊 *YOUR STATISTICS*\n\n"
            f"• Files Checked: {files_checked}\n"
            f"• Total Proxies: {checks_made}\n"
            f"• Live Found: {live_found}\n"
            f"• Success Rate: {success_rate:.1f}%\n"
            f"• Days Active: {days_active}\n\n"
            f"💡 *Tips for Best Results:*\n"
            f"• Use **Auto Detect** for mixed files\n"
            f"• Remove duplicates before checking\n"
            f"• Check during off-peak hours (UTC 00:00-06:00)",
            parse_mode="Markdown"
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 *HELP & GUIDE*\n\n"
        "📋 *Commands:*\n"
        "• /start - Start the bot & see formats\n"
        "• /check - Check proxies (RECOMMENDED: Auto Detect)\n"
        "• /stats - View statistics\n"
        "• /help - This message\n\n"
        "📁 *Supported Proxy Formats:*\n"
        "```\n"
        "1.2.3.4:8080\n"
        "user:pass@5.6.7.8:3128\n"
        "9.10.11.12:1080:username:password\n"
        "```\n\n"
        "🤖 *Auto Detect Mode:*\n"
        "• Perfect for mixed proxy files\n"
        "• Tests all 4 protocols automatically\n"
        "• Returns fastest working protocol\n\n"
        "⚡ *Best Practices:*\n"
        "1. Remove duplicate proxies\n"
        "2. Use Auto Detect for unknown types\n"
        "3. Files up to 10,000 proxies work best",
        parse_mode="Markdown"
    )

# ================== FIXED MAIN FUNCTION ==================

def main():
    # First, ensure all storage exists
    logger.info("📁 Initializing storage...")
    ensure_storage()
    
    # Load GeoIP database
    logger.info("🌍 Loading GeoIP database...")
    try:
        ensure_geolite_db()
        global geo_reader
        geo_reader = geoip2.database.Reader(GEO_DB)
        logger.info("✅ GeoLite2 database loaded successfully")
    except Exception as e:
        logger.error(f"❌ Failed to load GeoLite2 database: {e}")
        geo_reader = None
    
    # Create bot application
    logger.info("🤖 Creating bot application...")
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("help", help_command))
    
    # Callback handlers
    app.add_handler(CallbackQueryHandler(recheck, pattern="recheck"))
    app.add_handler(CallbackQueryHandler(proxy_type))
    
    # File handler
    app.add_handler(
        MessageHandler(filters.Document.FileExtension("txt"), handle_file)
    )
    
    logger.info("🚀 BOT STARTED SUCCESSFULLY")
    logger.info(f"👑 Owner ID: {OWNER_ID}")
    logger.info(f"📊 Storage: {DATA_DIR}")
    logger.info(f"⚡ Max Concurrency: {MAX_CONCURRENCY}")
    
    # Verify JSON files exist
    json_files = ["users.json", "checks_count.json", "ban.json", "uptime.json", "user_stats.json", "proxies_db.json"]
    for json_file in json_files:
        filepath = f"{DATA_DIR}/{json_file}"
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            logger.info(f"✅ {json_file}: OK")
        else:
            logger.warning(f"⚠️ {json_file}: Missing or empty, will be created")
    
    # Run the bot
    app.run_polling(drop_pending_updates=True)

# ================== CLEANUP ON EXIT ==================

import atexit

def cleanup():
    """Cleanup function to close GeoIP reader on exit"""
    if geo_reader:
        geo_reader.close()
        logger.info("✅ GeoIP database closed")

atexit.register(cleanup)

if __name__ == "__main__":
    main()
