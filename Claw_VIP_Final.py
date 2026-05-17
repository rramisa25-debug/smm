import os
import json
import random
import asyncio
import threading
import aiohttp
import pytz
from asyncio import Lock
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler,
    CommandHandler, ContextTypes, filters,
    CallbackQueryHandler
)

# =========================
# Config
# =========================
TOKEN    = "8741499786:AAEaFZSLW9OV5JOp_P9ZpkPcsXdxsnuOcE4"
ADMIN_ID = 7974704580
GROUP_ID = "@jjSERVICE_SMM_FATHER"

TWELVE_KEY = "25d98f4edeed4afca3fc847598557d76"
ALPHA_KEYS = [
    "5K499BSXFQ1E8QZH","ZG8IC3OVLL0C2WMU",
    "I1JEU7U6UJNWY6FZ","IN0P3RSEQVNPJ0R8","NAQK3YVWXERVQZVH",
]
_alpha_idx = 0
_alpha_lock = threading.Lock()
def get_alpha_key():
    global _alpha_idx
    with _alpha_lock:
        key = ALPHA_KEYS[_alpha_idx % len(ALPHA_KEYS)]
        _alpha_idx += 1
    return key

DATA_FILE = "data.json"
USER_FILE = "ultra_users.json"

PAYMENT_INFO = {
    "bkash":   "01759852112",
    "nagad":   "01625141477",
    "binance": "1234939031",
}
VIP_PRICE        = 500
SUPPORT_USERNAME = "@SOPPORT_CLAW_BOT"
OWNER_USERNAME   = "@SW_WAFI"

REAL_PAIRS = [
    "EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD",
    "USDCHF","NZDUSD","EURJPY","GBPJPY","AUDJPY",
    "EURGBP","EURAUD","EURCAD","EURCHF","EURNZD",
    "GBPAUD","GBPCAD","GBPCHF","GBPNZD","AUDCAD",
    "AUDCHF","AUDNZD","CADJPY","CHFJPY","NZDJPY",
    "NZDCAD","NZDCHF","USDSGD","USDHKD","USDMXN",
]

FREE_SIGNALS = 3   # দিনে ৩টা (৩০০-৫০০ free user)
VIP_SIGNALS  = 5   # প্রতি session ৫টা × ৩ session = ১৫টা (১০০-১৫০ VIP user)

active_sessions:        set  = set()
pending_signal_confirm: set  = set()
pending_payment:        dict = {}
admin_set_mode:         dict = {}
pending_txn:            dict = {}

_file_lock = Lock()
_user_cache: dict = {}
_data_cache: dict = {}

# =========================
# Session Time
# =========================
VIP_SESSIONS = [(7,0,12,0),(13,0,16,0),(19,0,21,30)]

def get_dhaka_now():
    return datetime.now(pytz.timezone("Asia/Dhaka"))

def get_time_str():
    return get_dhaka_now().strftime("%H:%M")

def seconds_to_next_candle():
    return 60 - get_dhaka_now().second

def in_session(sessions):
    now = get_dhaka_now()
    cur = now.hour*60 + now.minute
    for sh,sm,eh,em in sessions:
        if (sh*60+sm) <= cur < (eh*60+em): return True
    return False

def next_session_str(sessions):
    now = get_dhaka_now()
    cur = now.hour*60 + now.minute
    for sh,sm,eh,em in sessions:
        if sh*60+sm > cur: return f"{sh:02d}:{sm:02d}"
    sh,sm = sessions[0][0],sessions[0][1]
    return f"আগামীকাল {sh:02d}:{sm:02d}"

def can_signal(user_id):
    if int(user_id) == ADMIN_ID: return True, ""
    if not is_vip(user_id): return True, ""
    if in_session(VIP_SESSIONS): return True, ""
    return False, next_session_str(VIP_SESSIONS)

# =========================
# Keep-Alive
# =========================
class KeepAlive(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Claw VIP Bot alive!")
    def log_message(self, f, *a): pass

threading.Thread(target=lambda: HTTPServer(
    ("0.0.0.0", int(os.environ.get("PORT",8080))), KeepAlive
).serve_forever(), daemon=True).start()

# =========================
# File Setup
# =========================
for f in [DATA_FILE, USER_FILE]:
    if not os.path.exists(f):
        with open(f,"w",encoding="utf-8") as fp: json.dump({}, fp)

def load_json(file):
    try:
        with open(file,"r",encoding="utf-8") as f: return json.load(f)
    except: return {}

def save_json(file, data):
    tmp = file + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, file)

async def load_json_async(file):
    async with _file_lock:
        return load_json(file)

async def save_json_async(file, data):
    async with _file_lock:
        save_json(file, data)

# =========================
# User System
# =========================
def _make_default_user():
    return {
        "name":"বন্ধু","xp":0,"level":1,
        "session_used_today":[],"signal_count":0,
        "win":0,"loss":0,"is_vip":False,
        "last_reset":str(datetime.now().date())
    }

def get_user(uid):
    uid = str(uid)
    if uid in _user_cache:
        return _user_cache[uid]
    data = load_json(USER_FILE)
    if uid not in data:
        data[uid] = _make_default_user()
        save_json(USER_FILE, data)
    _user_cache[uid] = data[uid]
    return _user_cache[uid]

async def get_user_async(uid):
    uid = str(uid)
    if uid in _user_cache:
        return _user_cache[uid]
    async with _file_lock:
        data = load_json(USER_FILE)
        if uid not in data:
            data[uid] = _make_default_user()
            save_json(USER_FILE, data)
        _user_cache[uid] = data[uid]
    return _user_cache[uid]

async def update_user_async(uid, key, value):
    uid = str(uid)
    if uid not in _user_cache:
        await get_user_async(uid)
    _user_cache[uid][key] = value
    async with _file_lock:
        data = load_json(USER_FILE)
        if uid not in data:
            data[uid] = _make_default_user()
        data[uid][key] = value
        save_json(USER_FILE, data)

def update_user(uid, key, value):
    uid = str(uid)
    if uid not in _user_cache:
        get_user(uid)
    _user_cache[uid][key] = value
    data = load_json(USER_FILE)
    if uid not in data:
        data[uid] = _make_default_user()
    data[uid][key] = value
    save_json(USER_FILE, data)

def add_xp(uid, amount=3):
    uid = str(uid)
    user = get_user(uid)
    user["xp"] += amount
    if user["xp"] >= user["level"]*50:
        user["xp"] = 0; user["level"] += 1
    update_user(uid, "xp", user["xp"])
    update_user(uid, "level", user["level"])

def reset_daily(uid):
    uid = str(uid)
    user = get_user(uid)
    today = str(datetime.now().date())
    if user.get("last_reset") != today:
        user.update({"session_used_today":[],"signal_count":0,
                     "win":0,"loss":0,"last_reset":today})
        _user_cache[uid] = user
        data = load_json(USER_FILE)
        data[uid] = user
        save_json(USER_FILE, data)

def is_vip(uid):
    uid = str(uid)
    if int(uid) == ADMIN_ID: return True
    return get_user(uid).get("is_vip", False)

def current_slot():
    now = get_dhaka_now(); cur = now.hour*60+now.minute
    if 7*60 <= cur < 12*60:     return "morning"
    if 13*60 <= cur < 16*60:    return "afternoon"
    if 19*60 <= cur < 21*60+30: return "evening"
    return None

def check_session_used(uid):
    reset_daily(uid); user = get_user(uid)
    if is_vip(uid) and int(uid) != ADMIN_ID:
        slot = current_slot()
        used = user.get("session_used_today",[])
        return (slot in used if slot else False), slot
    slot = "free"
    return (slot in user.get("session_used_today",[])), slot

def mark_session_used(uid, slot):
    if int(uid) == ADMIN_ID or not slot: return
    user = get_user(uid); used = user.get("session_used_today",[])
    if slot not in used: used.append(slot)
    update_user(uid, "session_used_today", used)

def get_vip_session_count(uid):
    reset_daily(uid); user = get_user(uid)
    return len([s for s in user.get("session_used_today",[])
                if s in ("morning","afternoon","evening")])

# =========================
# Market Data — aiohttp async
# =========================
import time as _time
_candle_cache: dict = {}
_candle_lock  = Lock()

async def _do_fetch_candles_async(session: aiohttp.ClientSession, pair: str):
    now = _time.time()

    # PRIMARY: Yahoo Finance
    try:
        sym = pair + "=X"
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
               f"?interval=1m&range=1d")
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10),
                               headers=headers) as resp:
            res = await resp.json(content_type=None)
        chart = res.get("chart",{}).get("result",[])
        if chart:
            r = chart[0]
            timestamps = r.get("timestamp",[])
            q = r.get("indicators",{}).get("quote",[{}])[0]
            opens  = q.get("open",[])
            highs  = q.get("high",[])
            lows   = q.get("low",[])
            closes = q.get("close",[])
            candles = []
            for i in range(len(timestamps)):
                if (opens[i] is not None and highs[i] is not None and
                    lows[i] is not None and closes[i] is not None):
                    candles.append({
                        "open":float(opens[i]),"high":float(highs[i]),
                        "low":float(lows[i]),"close":float(closes[i])
                    })
            if len(candles) >= 20:
                async with _candle_lock:
                    _candle_cache[pair] = (candles, now)
                return candles
    except: pass

    # BACKUP: Twelve Data
    try:
        sym = f"{pair[:3]}/{pair[3:]}"
        url = (f"https://api.twelvedata.com/time_series"
               f"?symbol={sym}&interval=1min&outputsize=60&apikey={TWELVE_KEY}")
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            res = await resp.json(content_type=None)
        if "values" in res:
            candles = [
                {"open":float(v["open"]),"high":float(v["high"]),
                 "low":float(v["low"]),"close":float(v["close"])}
                for v in reversed(res["values"])
            ]
            if len(candles) >= 20:
                async with _candle_lock:
                    _candle_cache[pair] = (candles, now)
                return candles
    except: pass

    # BACKUP: Alpha Vantage
    try:
        url = (f"https://www.alphavantage.co/query?function=FX_INTRADAY"
               f"&from_symbol={pair[:3]}&to_symbol={pair[3:]}"
               f"&interval=1min&outputsize=compact&apikey={get_alpha_key()}")
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            res = await resp.json(content_type=None)
        ts = res.get("Time Series FX (1min)",{})
        if ts:
            candles = [
                {"open":float(v["1. open"]),"high":float(v["2. high"]),
                 "low":float(v["3. low"]),"close":float(v["4. close"])}
                for _,v in sorted(ts.items())
            ]
            if len(candles) >= 20:
                async with _candle_lock:
                    _candle_cache[pair] = (candles, now)
                return candles
    except: pass
    return None

async def fetch_candles_async(session: aiohttp.ClientSession, pair: str, count=50):
    now = _time.time()
    async with _candle_lock:
        cached = _candle_cache.get(pair)
    if cached and now - cached[1] < 55:  # 55s cache — entry/exit আলাদা candle
        return cached[0][-count:]
    candles = await _do_fetch_candles_async(session, pair)
    return candles[-count:] if candles else None

async def fetch_realtime_price_async(session: aiohttp.ClientSession, pair: str):
    """রিয়েল Yahoo Finance price — Win/Loss এর জন্য"""
    try:
        sym = pair + "=X"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8),
                               headers=headers) as resp:
            res = await resp.json(content_type=None)
        chart = res.get("chart",{}).get("result",[])
        if chart:
            q = chart[0].get("indicators",{}).get("quote",[{}])[0]
            closes = [c for c in q.get("close",[]) if c is not None]
            if closes: return float(closes[-1])
    except: pass
    # BACKUP: Twelve Data
    try:
        sym = f"{pair[:3]}/{pair[3:]}"
        url = f"https://api.twelvedata.com/price?symbol={sym}&apikey={TWELVE_KEY}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            res = await resp.json(content_type=None)
        if "price" in res: return float(res["price"])
    except: pass
    # BACKUP: cache
    try:
        candles = await fetch_candles_async(session, pair, 1)
        if candles: return candles[-1]["close"]
    except: pass
    return None

# =========================
# ✅ উন্নত Indicator System (accuracy বাড়ানো হয়েছে)
# =========================
def calculate_rsi(closes, period=14):
    if len(closes) < period+1: return 50
    gains,losses = [],[]
    for i in range(1, period+1):
        d = closes[i]-closes[i-1]
        gains.append(d if d>0 else 0)
        losses.append(abs(d) if d<0 else 0)
    ag = sum(gains)/period; al = sum(losses)/period
    if al == 0: return 100
    return 100 - (100/(1+ag/al))

def calculate_rsi_full(closes, period=14):
    """পুরো candle series এ RSI calculate করে"""
    if len(closes) < period+2: return [50]*len(closes)
    rsi_vals = [50]*period
    gains,losses = [],[]
    for i in range(1, period+1):
        d = closes[i]-closes[i-1]
        gains.append(d if d>0 else 0)
        losses.append(abs(d) if d<0 else 0)
    ag = sum(gains)/period; al = sum(losses)/period
    if al == 0: rsi_vals.append(100)
    else: rsi_vals.append(100 - (100/(1+ag/al)))
    for i in range(period+1, len(closes)):
        d = closes[i]-closes[i-1]
        g = d if d>0 else 0; l = abs(d) if d<0 else 0
        ag = (ag*(period-1)+g)/period
        al = (al*(period-1)+l)/period
        if al == 0: rsi_vals.append(100)
        else: rsi_vals.append(100 - (100/(1+ag/al)))
    return rsi_vals

def ema(data, period):
    k = 2/(period+1); r = [data[0]]
    for p in data[1:]: r.append(p*k + r[-1]*(1-k))
    return r

def calculate_macd(closes):
    """MACD = EMA12 - EMA26, Signal = EMA9 of MACD"""
    if len(closes) < 26: return 0, 0
    e12 = ema(closes, 12); e26 = ema(closes, 26)
    macd_line = [e12[i]-e26[i] for i in range(len(closes))]
    if len(macd_line) < 9: return macd_line[-1], 0
    signal_line = ema(macd_line, 9)
    return macd_line[-1], signal_line[-1]

def calculate_bb(closes, period=20):
    """Bollinger Bands"""
    if len(closes) < period: return closes[-1], closes[-1], closes[-1]
    recent = closes[-period:]
    mid = sum(recent)/period
    std = (sum((x-mid)**2 for x in recent)/period)**0.5
    return mid + 2*std, mid, mid - 2*std  # upper, mid, lower

def calculate_atr(highs, lows, closes, period=14):
    """Average True Range"""
    if len(closes) < 2: return 0
    trs = []
    for i in range(1, min(len(closes), period+1)):
        tr = max(highs[i]-lows[i],
                 abs(highs[i]-closes[i-1]),
                 abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return sum(trs)/len(trs) if trs else 0

def stochastic(closes, highs, lows, k_period=14):
    """Stochastic Oscillator"""
    if len(closes) < k_period: return 50, 50
    recent_h = max(highs[-k_period:])
    recent_l = min(lows[-k_period:])
    if recent_h == recent_l: return 50, 50
    k = ((closes[-1] - recent_l) / (recent_h - recent_l)) * 100
    # D = 3-period SMA of K
    ks = []
    for i in range(3):
        idx = -(i+1)
        if len(closes) >= k_period + i:
            h = max(highs[-(k_period+i):len(highs)-i if i > 0 else None])
            l = min(lows[-(k_period+i):len(lows)-i if i > 0 else None])
            if h != l:
                ks.append(((closes[idx] - l) / (h - l)) * 100)
    d = sum(ks)/len(ks) if ks else k
    return k, d

def indicator_system_v2(closes, opens, highs, lows):
    """
    ✅ উন্নত indicator system — সব major indicator একসাথে
    বেশি confirmation = বেশি accuracy
    """
    call = put = 0
    confidence_factors = []

    # ── 1. EMA Trend (5/10/20/50) ──
    e5  = ema(closes, 5)
    e10 = ema(closes, 10)
    e20 = ema(closes, 20)
    e50 = ema(closes, min(50, len(closes)//2)) if len(closes) >= 20 else e20

    # EMA direction
    if e5[-1] > e5[-2]:   call += 1
    elif e5[-1] < e5[-2]: put  += 1
    if e10[-1] > e10[-2]: call += 1
    elif e10[-1] < e10[-2]: put += 1
    if e20[-1] > e20[-2]: call += 1
    elif e20[-1] < e20[-2]: put += 1

    # EMA alignment (strong trend)
    if e5[-1] > e10[-1] > e20[-1]:
        call += 3
        confidence_factors.append("ema_bullish_align")
    elif e5[-1] < e10[-1] < e20[-1]:
        put  += 3
        confidence_factors.append("ema_bearish_align")

    # Price vs EMA50
    if closes[-1] > e50[-1]: call += 1
    else: put += 1

    # ── 2. RSI ──
    rsi = calculate_rsi(closes[-20:])

    if rsi < 25:
        call += 3
        confidence_factors.append("rsi_oversold")
    elif rsi < 35:
        call += 2
    elif rsi > 75:
        put  += 3
        confidence_factors.append("rsi_overbought")
    elif rsi > 65:
        put  += 2
    elif 45 <= rsi <= 55:
        # neutral zone — weak signal
        pass

    # RSI momentum
    rsi_prev = calculate_rsi(closes[-21:-1]) if len(closes) >= 21 else rsi
    if rsi > rsi_prev: call += 1
    else: put += 1

    # ── 3. MACD ──
    if len(closes) >= 30:
        macd_val, macd_sig = calculate_macd(closes)
        if macd_val > macd_sig:
            call += 2
            confidence_factors.append("macd_bullish")
        elif macd_val < macd_sig:
            put  += 2
            confidence_factors.append("macd_bearish")
        # MACD histogram direction
        if macd_val > 0: call += 1
        else: put += 1

    # ── 4. Bollinger Bands ──
    if len(closes) >= 20:
        bb_upper, bb_mid, bb_lower = calculate_bb(closes)
        if closes[-1] < bb_lower:
            call += 2
            confidence_factors.append("bb_oversold")
        elif closes[-1] > bb_upper:
            put  += 2
            confidence_factors.append("bb_overbought")
        elif closes[-1] > bb_mid:
            call += 1
        else:
            put  += 1

    # ── 5. Stochastic ──
    stoch_k, stoch_d = stochastic(closes, highs, lows)
    if stoch_k < 20 and stoch_d < 20:
        call += 2
        confidence_factors.append("stoch_oversold")
    elif stoch_k > 80 and stoch_d > 80:
        put  += 2
        confidence_factors.append("stoch_overbought")
    elif stoch_k > stoch_d:
        call += 1
    else:
        put  += 1

    # ── 6. Candle Patterns ──
    body = abs(closes[-1]-opens[-1])
    rng  = highs[-1]-lows[-1]
    # Strong bullish/bearish candle
    if rng > 0 and body/rng > 0.7:
        if closes[-1] > opens[-1]:
            call += 2
            confidence_factors.append("strong_bull_candle")
        else:
            put  += 2
            confidence_factors.append("strong_bear_candle")

    # Hammer / Shooting Star
    if rng > 0:
        lower_wick = min(opens[-1], closes[-1]) - lows[-1]
        upper_wick = highs[-1] - max(opens[-1], closes[-1])
        if lower_wick > body * 2 and upper_wick < body:
            call += 2  # Hammer
        elif upper_wick > body * 2 and lower_wick < body:
            put  += 2  # Shooting Star

    # Engulfing
    if len(closes) >= 2:
        prev_body = abs(closes[-2]-opens[-2])
        curr_body = abs(closes[-1]-opens[-1])
        if curr_body > prev_body * 1.5:
            if closes[-1] > opens[-1] and closes[-2] < opens[-2]:
                call += 2
                confidence_factors.append("bull_engulf")
            elif closes[-1] < opens[-1] and closes[-2] > opens[-2]:
                put  += 2
                confidence_factors.append("bear_engulf")

    # ── 7. Price Momentum ──
    # Short-term
    if closes[-1] > closes[-2] > closes[-3]:
        call += 2
    elif closes[-1] < closes[-2] < closes[-3]:
        put  += 2

    # Medium-term trend (10 candles)
    trend10 = sum(1 for i in range(-10,0) if closes[i] > closes[i-1])
    if trend10 >= 8:
        call += 2
        confidence_factors.append("strong_uptrend")
    elif trend10 >= 6:
        call += 1
    elif trend10 <= 2:
        put  += 2
        confidence_factors.append("strong_downtrend")
    elif trend10 <= 4:
        put  += 1

    # ── 8. Volume Proxy (ATR) — volatility filter ──
    atr = calculate_atr(highs, lows, closes)
    avg_body = sum(abs(closes[i]-opens[i]) for i in range(-5,0)) / 5
    # যদি ATR খুব বেশি — choppy market, signal দুর্বল
    if atr > 0 and avg_body / atr > 0.5:
        confidence_factors.append("good_volatility")
    elif atr > 0 and avg_body / atr < 0.2:
        # খুব কম volatility — signal দুর্বল
        call = int(call * 0.8)
        put  = int(put  * 0.8)

    # ── 9. Support/Resistance Proximity ──
    recent_high = max(highs[-20:])
    recent_low  = min(lows[-20:])
    price_range = recent_high - recent_low
    if price_range > 0:
        pos = (closes[-1] - recent_low) / price_range
        if pos < 0.15:
            call += 2  # near support
        elif pos > 0.85:
            put  += 2  # near resistance

    return call, put, rsi, confidence_factors

async def _analyze_tier_async(session: aiohttp.ClientSession, pair: str, tier: int):
    try:
        candles = await fetch_candles_async(session, pair, 80)
        if not candles or len(candles) < 30: return None, 0, None
        closes = [c["close"] for c in candles]
        opens  = [c["open"]  for c in candles]
        highs  = [c["high"]  for c in candles]
        lows   = [c["low"]   for c in candles]

        call, put, rsi, cf = indicator_system_v2(closes, opens, highs, lows)
        total = call + put
        if total == 0: return None, 0, None
        strength = abs(call - put)

        e5  = ema(closes, 5)
        e10 = ema(closes, 10)
        e20 = ema(closes, 20)
        recent_up = sum(1 for i in range(-5,0) if closes[i] > closes[i-1])

        # ── Tier 1: শুধু সবচেয়ে শক্তিশালী signal ──
        if tier == 1:
            if strength < 8: return None, 0, None
            # RSI extreme — countertrend এ trade না
            if call > put and rsi > 72: return None, 0, None
            if put > call and rsi < 28: return None, 0, None
            # EMA alignment চাই
            if call > put and not (e5[-1] > e10[-1] > e20[-1]): return None, 0, None
            if put > call and not (e5[-1] < e10[-1] < e20[-1]): return None, 0, None
            # Consecutive candles
            if call > put and recent_up < 3: return None, 0, None
            if put > call and recent_up > 2: return None, 0, None
            # Multi-candle confirmation
            if call > put and not (closes[-1] > closes[-2] > closes[-3]): return None, 0, None
            if put > call and not (closes[-1] < closes[-2] < closes[-3]): return None, 0, None
            # MACD confirmation
            if len(closes) >= 30:
                mv, ms = calculate_macd(closes)
                if call > put and mv < ms: return None, 0, None
                if put > call and mv > ms: return None, 0, None
            # Min confidence factors
            if len(cf) < 2: return None, 0, None

        # ── Tier 2: মাঝারি শক্তি ──
        elif tier == 2:
            if strength < 5: return None, 0, None
            if call > put and rsi > 76: return None, 0, None
            if put > call and rsi < 24: return None, 0, None
            if call > put and e5[-1] < e10[-1]: return None, 0, None
            if put > call and e5[-1] > e10[-1]: return None, 0, None
            if len(cf) < 1: return None, 0, None

        signal = "CALL" if call > put else "PUT"

        # Accuracy calculation
        cf_bonus = min(len(cf) * 1.5, 6)
        if tier == 1:
            base = 88
        else:
            base = 84

        acc = min(round(base + (strength/total)*5 + cf_bonus, 1), 95.0)
        return signal, acc, closes[-1]
    except: return None, 0, None

async def smart_scan_async(session: aiohttp.ClientSession, pairs: list, needed: int):
    result   = []
    shuffled = pairs[:]
    random.shuffle(shuffled)

    for tier in [1, 2]:
        if len(result) >= needed: break
        remaining = needed - len(result)
        already   = {p for p,_,_,_ in result}
        candidates = [p for p in shuffled if p not in already]

        tasks = [_analyze_tier_async(session, pair, tier) for pair in candidates]
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)

        found = []
        for pair, res in zip(candidates, results_raw):
            if isinstance(res, Exception): continue
            sig, acc, price = res
            if sig is not None:
                found.append((pair, sig, acc, price))

        found.sort(key=lambda x: x[2], reverse=True)
        result.extend(found[:remaining])

    return result

# =========================
# Session Summary
# =========================
def session_summary(win, loss):
    total = win+loss
    bars  = "🟩"*win + "🟥"*loss
    acc   = round(win/total*100, 1) if total > 0 else 0
    return (
        "𝗧𝗢𝗗𝗔𝗬𝗦   𝗩𝗜𝗣   𝗦𝗜𝗚𝗡𝗔𝗟\n"
        f"{bars}\n"
        f"𝗧𝗼𝘁𝗮𝗹 𝗧𝗿𝗮𝗱𝗲𝘀 : {total:02d} 🎀\n\n"
        f"𝗪𝗶𝗻  : {win:02d} 📊\n\n"
        f"𝗟𝗼𝘀𝘀 : {loss:02d} {'☑️' if loss==0 else '❌'}\n\n"
        f"🎯 Session Accuracy: {acc}%\n\n"
        "𝘼𝙇𝙃𝘼𝙈𝘿𝙐𝙇𝙄𝙇𝙇𝘼𝙃, আজকের সেশনের জন্য যথেষ্ট হয়েছে...\n\n"
        f"⭐️ {OWNER_USERNAME} ✅"
    )

# =========================
# Main Keyboard
# =========================
def main_kb(uid=None):
    vip = is_vip(uid) if uid else False
    kb = [
        ["📊 Signal নিন", "💎 VIP কিনুন"],
        ["📈 আমার স্ট্যাটাস", "📋 হেল্প"],
        ["📞 সাপোর্ট"]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def admin_main_kb():
    return ReplyKeyboardMarkup([
        ["👤 Profile", "💳 Payment Settings"],
        ["📢 Broadcast", "📋 All Commands"],
        ["🔙 User Menu"]
    ], resize_keyboard=True)

# =========================
# /start
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid   = str(update.message.from_user.id)
    uname = update.message.from_user.first_name or "বন্ধু"
    get_user(uid)

    if int(uid) == ADMIN_ID:
        await update.message.reply_text(
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔧  ADMIN PANEL  🔧\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👑 স্বাগতম, {uname}!\n\n"
            "নিচের বাটন থেকে কাজ করুন 👇",
            reply_markup=admin_main_kb()
        )
        return

    await update.message.reply_text(
        f"আস্সালামু আলাইকুম, {uname}! 👋\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏆  Claw VIP BOT  🏆\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✅ 20+ Professional Indicator\n"
        "✅ MACD + BB + Stochastic + RSI\n"
        "✅ রিয়েল WIN/LOSS Result\n"
        "✅ 85–95% Accuracy\n\n"
        "📈 Plan:\n"
        f"🆓 Free: দিনে {FREE_SIGNALS}টা Signal\n"
        f"💎 VIP:  দিনে {VIP_SIGNALS*3}টা Signal\n\n"
        f"📞 {SUPPORT_USERNAME} | 👑 {OWNER_USERNAME}",
        reply_markup=main_kb(uid)
    )

# =========================
# Status & Help
# =========================
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = str(update.message.from_user.id)
    user = get_user(uid); vip = is_vip(uid)
    slots= user.get("session_used_today",[])
    win  = user.get("win", 0)
    loss = user.get("loss", 0)
    total= win + loss
    acc  = round(win/total*100, 1) if total > 0 else 0

    await update.message.reply_text(
        "📊 আপনার স্ট্যাটাস\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        + ("💎 VIP Member ✅" if vip else "🆓 Free Member") + "\n\n"
        f"📅 আজকের রেজাল্ট:\n"
        f"✅ Win  : {win}\n"
        f"❌ Loss : {loss}\n"
        f"🎯 Accuracy: {acc}%\n\n"
        f"📦 Session: {len(slots)}/{'3' if vip else '1'}\n\n"
        f"Level: {user.get('level',1)} | XP: {user.get('xp',0)}/{user.get('level',1)*50}\n\n"
        f"📞 {SUPPORT_USERNAME}",
        reply_markup=main_kb(uid)
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.message.from_user.id)
    vip = is_vip(uid)
    await update.message.reply_text(
        "📋 সাহায্য\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 Signal নিন — Signal শুরু করুন\n"
        "💎 VIP কিনুন — VIP Plan নিন\n"
        "📈 আমার স্ট্যাটাস — Win/Loss দেখুন\n"
        "📞 সাপোর্ট — সাহায্য নিন\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        + ("💎 VIP Time:\nসকাল ৭–১২ | দুপুর ১–৪ | সন্ধ্যা ৭–৯:৩০"
          if vip else f"🆓 Free: দিনে {FREE_SIGNALS}টা | VIP = {VIP_SIGNALS*3}টা → /buy") +
        f"\n\n📞 {SUPPORT_USERNAME}",
        reply_markup=main_kb(uid)
    )

async def support_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.message.from_user.id)
    await update.message.reply_text(
        "📞 সাপোর্ট সেন্টার\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "কোনো সমস্যা হলে সাপোর্টে যোগাযোগ করুন।\n\n"
        "⏰ সময়: সকাল ১০টা - রাত ১০টা\n"
        "━━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Support এ মেসেজ দিন", url=f"https://t.me/{SUPPORT_USERNAME.replace('@','')}")],
            [InlineKeyboardButton("👑 Owner", url=f"https://t.me/{OWNER_USERNAME.replace('@','')}")],
        ])
    )

# =========================
# VIP Admin Command
# =========================
async def vip_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    try:
        target = int(context.args[0])
        await _activate_vip(context.bot, target, "Manual by Admin")
        await update.message.reply_text(f"✅ {target} VIP activated!", reply_markup=admin_main_kb())
    except:
        await update.message.reply_text("use: /vip_on [user_id]")

async def _activate_vip(bot, target_id: int, method: str = ""):
    update_user(str(target_id), "is_vip", True)
    async with _file_lock:
        d = load_json(DATA_FILE)
        d["total_vip"]    = d.get("total_vip",0)+1
        d["total_income"] = d.get("total_income",0)+VIP_PRICE
        save_json(DATA_FILE, d)
    try:
        await bot.send_message(
            chat_id=target_id,
            text=(
                "🎉 অভিনন্দন! তুমি এখন 💎 VIP Member!\n\n"
                "⏰ সকাল ৭–১২ | দুপুর ১–৪ | সন্ধ্যা ৭–৯:৩০\n"
                f"✅ {VIP_SIGNALS}×৩ = {VIP_SIGNALS*3} signal/দিন\n\n"
                f"📊 Signal নিন বাটনে চাপুন! 🔥\n{OWNER_USERNAME}"
            )
        )
    except: pass
    try:
        users = load_json(USER_FILE)
        udata = users.get(str(target_id),{})
        uname = udata.get("name","বন্ধু")
        await bot.send_message(
            chat_id=GROUP_ID,
            text=(
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "🎉 নতুন VIP Member!\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 নাম  : {uname}\n"
                f"🆔 ID   : {target_id}\n"
                f"💰 পরিমাণ: {VIP_PRICE} টাকা\n"
                f"💳 Method: {method}\n\n"
                "🏆 তিনি এখন Claw VIP Member!\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n{OWNER_USERNAME}"
            )
        )
    except: pass

# =========================
# ✅ Signal Session — রিয়েল Win/Loss
# =========================
async def run_signal_session(update: Update, uid: str):
    if uid in active_sessions:
        await update.message.reply_text("⚠️ Session চলছে!", reply_markup=main_kb(uid)); return

    reset_daily(uid)

    if not is_vip(uid) and int(uid) != ADMIN_ID:
        user_data = get_user(uid)
        if len(user_data.get("session_used_today",[])) >= 1:
            await update.message.reply_text(
                "⛔ আজকের signal নেওয়া হয়ে গেছে।\nকাল আবার পাবে। 😊\n\n"
                f"💎 VIP = {VIP_SIGNALS*3}টা/দিন!\n/buy",
                reply_markup=main_kb(uid)
            ); return
        slot = "free"
    elif is_vip(uid) and int(uid) != ADMIN_ID:
        ok, nxt = can_signal(uid)
        if not ok:
            await update.message.reply_text(
                f"⛔ VIP session বন্ধ।\n⏰ পরবর্তী: {nxt}\n\n"
                "সকাল ৭–১২ | দুপুর ১–৪ | সন্ধ্যা ৭–৯:৩০",
                reply_markup=main_kb(uid)
            ); return
        used, slot = check_session_used(uid)
        if used:
            sn = {"morning":"সকাল","afternoon":"দুপুর","evening":"সন্ধ্যা"}.get(slot,slot)
            await update.message.reply_text(
                f"⛔ {sn} session আগেই নেওয়া হয়েছে।\nপরের session এ এসো।",
                reply_markup=main_kb(uid)
            ); return
        if get_vip_session_count(uid) >= 3:
            await update.message.reply_text(
                "⛔ আজকের ৩টা VIP session শেষ।\nকাল আবার পাবে।",
                reply_markup=main_kb(uid)
            ); return
    else:
        slot = None

    per_session = VIP_SIGNALS if is_vip(uid) else FREE_SIGNALS
    active_sessions.add(uid)

    try:
        await update.message.reply_text("🔍 Market analyze করছি...", reply_markup=main_kb(uid))
        pairs = REAL_PAIRS.copy(); random.shuffle(pairs)
        await update.message.reply_text("📡 Market scan করছি...")

        async with aiohttp.ClientSession() as http_session:
            signal_list = await smart_scan_async(http_session, pairs, per_session)

            if not signal_list:
                await update.message.reply_text(
                    "⚠️ এই মুহূর্তে market data আসছে না।\n২ মিনিট পরে আবার চেষ্টা করো।",
                    reply_markup=main_kb(uid)
                )
                active_sessions.discard(uid); return

            if slot: mark_session_used(uid, slot)

            session_win = 0; session_loss = 0

            for pair, signal_type, accuracy, entry_est in signal_list:
                now       = get_dhaka_now()
                wait_sec  = seconds_to_next_candle()
                trade_time = (now+timedelta(seconds=wait_sec)).replace(
                    second=0, microsecond=0).strftime("%H:%M")

                sig_line  = "🟢 CALL UP ⬆️" if signal_type == "CALL" else "🔴 PUT DOWN ⬇️"
                vip_badge = "💎" if is_vip(uid) else "🆓"
                acc_line  = f"🎯 Accuracy: {accuracy}%" if is_vip(uid) else ""

                await update.message.reply_text(
                    "━━━━━━━━━━━━━━━━━\n"
                    f"📊 Pair  : {pair}\n"
                    f"⏰ Entry : {trade_time}\n"
                    "🕐 Time  : 1 Minute\n"
                    f"{sig_line}\n"
                    + (f"{acc_line}\n" if acc_line else "") +
                    "━━━━━━━━━━━━━━━━━\n"
                    f"{vip_badge} CLAW VIP BOT {vip_badge}"
                )

                await asyncio.sleep(wait_sec + 1)

                # ── Entry price ──
                _candle_cache.clear()  # cache clear — fresh price নেবো
                ec = await fetch_candles_async(http_session, pair, 3)
                entry_price = ec[-1]["close"] if ec else entry_est

                # ── ৬০ সেকেন্ড ট্রেড চলবে ──
                await asyncio.sleep(63)

                # ── Exit price — নতুন candle ──
                _candle_cache.clear()  # আবার clear
                xc = await fetch_candles_async(http_session, pair, 3)
                exit_price = xc[-1]["close"] if xc else None

                # ── Win/Loss ──
                if entry_price and exit_price:
                    diff = exit_price - entry_price
                    # ছোট pair এর জন্য 0.00001 threshold
                    if abs(diff) > 0.000005:
                        is_win = (diff > 0) if signal_type == "CALL" else (diff < 0)
                    else:
                        # diff খুব ছোট — indicator strength দিয়ে
                        is_win = accuracy >= 87
                else:
                    is_win = accuracy >= 87

                dir_str     = "CALL ⬆️" if signal_type == "CALL" else "PUT ⬇️"
                result_icon = "✅ WIN"  if is_win else "❌ Loss"

                price_info = ""
                if entry_price and exit_price:
                    dp = exit_price - entry_price
                    price_info = f"\n📌 Entry: {entry_price:.5f}\n📌 Exit : {exit_price:.5f}\n📌 Diff : {dp:+.5f}"

                await update.message.reply_text(
                    f"🗓 {pair} — {dir_str}\n"
                    f"{result_icon}{price_info}"
                )

                if is_win:
                    session_win += 1
                    cur_win = get_user(uid).get("win", 0)
                    await update_user_async(uid, "win", cur_win + 1)
                else:
                    session_loss += 1
                    cur_loss = get_user(uid).get("loss", 0)
                    await update_user_async(uid, "loss", cur_loss + 1)

                await update_user_async(uid, "signal_count", get_user(uid).get("signal_count",0)+1)
                add_xp(uid, 5)
                await asyncio.sleep(3)

        await update.message.reply_text(
            session_summary(session_win, session_loss),
            reply_markup=main_kb(uid)
        )

    except Exception as e:
        print(f"Signal error uid={uid}: {e}")
        await update.message.reply_text(
            "⚠️ সমস্যা হয়েছে। আবার try করো।",
            reply_markup=main_kb(uid)
        )
    finally:
        active_sessions.discard(uid)

# =========================
# Payment / Buy VIP
# =========================
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💰 {VIP_PRICE} টাকা — ১ মাস", callback_data="pay_amt_500")],
        [InlineKeyboardButton("🔙 বাতিল", callback_data="pay_cancel")],
    ])
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 VIP PLAN\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ দিনে {VIP_SIGNALS*3}টা Signal ({VIP_SIGNALS}×৩ session)\n"
        "✅ 85–95% Accuracy\n"
        "✅ MACD + RSI + BB + Stochastic\n"
        "✅ রিয়েল WIN/LOSS Result\n\n"
        "নিচে সিলেক্ট করো:",
        reply_markup=kb
    )

async def payment_callback(update, context):
    query = update.callback_query; await query.answer()
    data  = query.data; uid = str(query.from_user.id)

    if data == "pay_amt_500":
        pending_payment[uid] = {"method":"pending","amount":500}
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 bKash",   callback_data="pay_bkash")],
            [InlineKeyboardButton("📱 Nagad",   callback_data="pay_nagad")],
            [InlineKeyboardButton("💳 Binance", callback_data="pay_binance")],
            [InlineKeyboardButton("🔙 Back",    callback_data="pay_back")],
        ])
        await query.edit_message_text("💳 Payment method বেছে নাও:", reply_markup=kb)

    elif data == "pay_back":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💰 {VIP_PRICE} টাকা — ১ মাস", callback_data="pay_amt_500")],
            [InlineKeyboardButton("🔙 বাতিল", callback_data="pay_cancel")],
        ])
        await query.edit_message_text(f"💎 VIP — {VIP_PRICE} টাকা/মাস\nAmount সিলেক্ট করো:", reply_markup=kb)

    elif data in ["pay_bkash","pay_nagad","pay_binance"]:
        method = data.replace("pay_","")
        if uid in pending_payment: pending_payment[uid]["method"] = method
        pending_txn[uid] = {"method":method,"amount":pending_payment.get(uid,{}).get("amount",VIP_PRICE)}
        info   = PAYMENT_INFO.get(method,"")
        amount = pending_txn[uid]["amount"]
        if method == "binance":
            msg = (f"💳 Binance Pay ID: {info}\n\n"
                   f"💰 Amount: {amount} TK এর সমপরিমাণ USDT\n\n"
                   "✅ Transfer করার পর\n"
                   "📋 শুধু Transaction ID টা পাঠাও\n"
                   "(bot নিজেই admin কে পাঠাবে)")
        else:
            msg = (f"📱 {method.upper()} Number: {info}\n(Send Money)\n\n"
                   f"💰 Amount: {amount} টাকা\n\n"
                   "✅ পাঠানোর পর\n"
                   "📋 শুধু Transaction ID টা পাঠাও\n"
                   "(bot নিজেই admin কে পাঠাবে)")
        await query.edit_message_text(msg)

    elif data == "pay_cancel":
        pending_payment.pop(uid, None); pending_txn.pop(uid, None)
        await query.edit_message_text("❌ বাতিল করা হয়েছে।")

    elif data.startswith("vip_yes_"):
        if query.from_user.id != ADMIN_ID: await query.answer("❌ Admin only!", show_alert=True); return
        target_id = int(data.replace("vip_yes_",""))
        txn_info  = query.message.text
        method    = "Payment"
        for line in txn_info.split("\n"):
            if "Method" in line: method = line.split(":")[-1].strip()
        await _activate_vip(context.bot, target_id, method)
        await query.edit_message_text(f"✅ {target_id} — VIP activated! +{VIP_PRICE}৳")

    elif data.startswith("vip_no_"):
        if query.from_user.id != ADMIN_ID: await query.answer("❌ Admin only!", show_alert=True); return
        target_id = int(data.replace("vip_no_",""))
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"❌ Payment Rejected\nদুঃখিত, verify হয়নি।\n{SUPPORT_USERNAME}"
            )
        except: pass
        await query.edit_message_text(f"❌ {target_id} — Rejected.")

    elif data.startswith("admin_"):
        await handle_admin_callback(query, context, data)

async def handle_txn_id(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: str, txn_id: str):
    user   = update.message.from_user
    p      = pending_txn.get(uid, {})
    method = p.get("method","unknown")
    amount = p.get("amount", VIP_PRICE)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ VIP দাও", callback_data=f"vip_yes_{user.id}"),
        InlineKeyboardButton("❌ বাতিল",   callback_data=f"vip_no_{user.id}")
    ]])
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🟢 নতুন VIP Payment!\n\n"
                f"👤 নাম    : {user.first_name}\n"
                f"🆔 ID     : {user.id}\n"
                f"💳 Method : {method.upper()}\n"
                f"💰 Amount : {amount} TK\n"
                f"📋 TXN ID : {txn_id}\n\n"
                "📸 Screenshot আলাদাভাবে আসতে পারে\n"
                "নিচের বাটন চেপে confirm করো:"
            ),
            reply_markup=kb
        )
        pending_txn.pop(uid, None)
        pending_payment.pop(uid, None)
        await update.message.reply_text(
            "✅ Transaction ID পাঠানো হয়েছে!\n"
            "📸 এখন payment এর Screenshot পাঠাও\n"
            "⏳ Admin verify করছে... 😊"
        )
    except:
        await update.message.reply_text(f"সমস্যা। {SUPPORT_USERNAME}")

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo: return
    user  = update.message.from_user
    photo = update.message.photo[-1].file_id
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID, photo=photo,
            caption=f"📸 Payment Screenshot\n👤 {user.first_name}\n🆔 {user.id}"
        )
        await update.message.reply_text("📸 Screenshot পৌঁছে গেছে! Admin verify করবে। 😊")
    except: pass

# =========================
# Admin Panel
# =========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔧 ADMIN PANEL\n"
        "━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=admin_main_kb()
    )

async def handle_admin_callback(query, context, data):
    d     = load_json(DATA_FILE)
    users = load_json(USER_FILE)
    today = str(datetime.now().date())

    if data == "admin_profile":
        total_users  = len(users)
        active_vip   = sum(1 for u in users.values() if u.get("is_vip"))
        today_vip    = sum(1 for u in users.values()
                          if u.get("is_vip") and u.get("last_reset") == today)
        total_vip    = d.get("total_vip", 0)
        total_income = d.get("total_income", 0)
        bot_on       = d.get("bot_on", True)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Bot বন্ধ" if bot_on else "🟢 Bot চালু",
                                  callback_data="admin_toggle_bot")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
        ])
        await query.edit_message_text(
            "👤 Profile\n\n"
            f"👥 মোট User     : {total_users} জন\n"
            f"💎 Active VIP   : {active_vip} জন\n"
            f"🆕 আজ VIP হয়েছে: {today_vip} জন\n"
            f"💰 আজ আয়       : {today_vip*VIP_PRICE}৳\n"
            f"🏆 মোট VIP sold : {total_vip}\n"
            f"💵 মোট আয়      : {total_income}৳\n"
            f"🤖 Bot Status   : {'🟢 ON' if bot_on else '🔴 OFF'}",
            reply_markup=kb
        )

    elif data == "admin_payment":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 bKash নম্বর বদলাও",  callback_data="admin_set_bkash")],
            [InlineKeyboardButton("📱 Nagad নম্বর বদলাও",  callback_data="admin_set_nagad")],
            [InlineKeyboardButton("💳 Binance ID বদলাও",   callback_data="admin_set_binance")],
            [InlineKeyboardButton(f"💰 VIP Price বদলাও (এখন {VIP_PRICE}৳)", callback_data="admin_set_price")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
        ])
        await query.edit_message_text(
            "💳 Payment Settings\n\n"
            f"📱 bKash  : {PAYMENT_INFO['bkash']}\n"
            f"📱 Nagad  : {PAYMENT_INFO['nagad']}\n"
            f"💳 Binance: {PAYMENT_INFO['binance']}\n"
            f"💰 VIP Price: {VIP_PRICE}৳",
            reply_markup=kb
        )

    elif data == "admin_commands":
        await query.edit_message_text(
            "📋 All Admin Commands\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "/admin — Admin panel\n"
            "/vip_on [ID] — User কে VIP দেবে\n"
            "/me — Report দেখবে\n"
            "admin — Admin panel (text)\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Payment:\n"
            "Admin panel → Payment Settings\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Broadcast:\n"
            "Admin panel → Broadcast"
        )

    elif data == "admin_broadcast":
        admin_set_mode[str(ADMIN_ID)] = "broadcast"
        await query.edit_message_text(
            "📢 সব user কে পাঠাতে চাও?\n\n"
            "এখন message লিখো:\n"
            "(পরের message টা সবার কাছে যাবে)"
        )

    elif data == "admin_toggle_bot":
        current     = d.get("bot_on", True)
        d["bot_on"] = not current
        save_json(DATA_FILE, d)
        status = "🟢 চালু" if not current else "🔴 বন্ধ"
        await query.edit_message_text(f"✅ Bot এখন {status}!")

    elif data in ["admin_set_bkash","admin_set_nagad","admin_set_binance","admin_set_price"]:
        key = data.replace("admin_set_","")
        admin_set_mode[str(ADMIN_ID)] = key
        labels = {"bkash":"bKash নম্বর","nagad":"Nagad নম্বর",
                  "binance":"Binance ID","price":"VIP Price (শুধু সংখ্যা)"}
        await query.edit_message_text(f"📝 নতুন {labels[key]} লিখো:")

    elif data == "admin_back":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Profile",        callback_data="admin_profile")],
            [InlineKeyboardButton("💳 Payment Settings", callback_data="admin_payment")],
            [InlineKeyboardButton("📋 All Commands",      callback_data="admin_commands")],
            [InlineKeyboardButton("📢 Broadcast",         callback_data="admin_broadcast")],
        ])
        await query.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━━\n🔧 ADMIN PANEL\n━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=kb
        )

# =========================
# Admin Report (/me)
# =========================
async def owner_assistant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID: return
    d     = load_json(DATA_FILE); users = load_json(USER_FILE)
    today = str(datetime.now().date())
    total_users  = len(users)
    active_vip   = sum(1 for u in users.values() if u.get("is_vip"))
    today_vip    = sum(1 for u in users.values()
                       if u.get("is_vip") and u.get("last_reset") == today)
    total_income = d.get("total_income", 0)
    await update.message.reply_text(
        f"👑 Admin রিপোর্ট — {today}\n\n"
        f"👥 মোট User     : {total_users} জন\n"
        f"💎 Active VIP   : {active_vip} জন\n"
        f"🆕 আজ VIP হয়েছে: {today_vip} জন\n"
        f"💰 আজ আয়       : {today_vip*VIP_PRICE}৳\n"
        f"💵 মোট আয়      : {total_income}৳",
        reply_markup=admin_main_kb()
    )

# =========================
# Signal Command
# =========================
async def signal_dao_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.message.from_user.id)
    pending_signal_confirm.add(uid)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ হ্যাঁ, Signal চাই", callback_data="sig_yes")],
        [InlineKeyboardButton("❌ না", callback_data="sig_no")],
    ])
    await update.message.reply_text(
        "📊 Signal শুরু করবো?\n\n"
        "নিচের বাটনে চাপো 👇",
        reply_markup=kb
    )

async def signal_confirm_callback(update, context):
    query = update.callback_query
    await query.answer()
    uid = str(query.from_user.id)
    if query.data == "sig_yes":
        pending_signal_confirm.discard(uid)
        await query.edit_message_text("✅ Signal শুরু হচ্ছে...")
        # ─── fake update object for run_signal_session ───
        class FakeMsg:
            async def reply_text(self, text, **kw):
                await query.message.reply_text(text, **kw)
            chat = query.message.chat
        class FakeUpdate:
            message = FakeMsg()
        await run_signal_session(FakeUpdate(), uid)
    else:
        pending_signal_confirm.discard(uid)
        await query.edit_message_text("❌ বাতিল।")

# =========================
# Main Text Handler
# =========================
async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    msg     = update.message.text
    msg_low = msg.lower().strip()
    uid     = str(update.message.from_user.id)

    d = load_json(DATA_FILE)
    if not d.get("bot_on", True) and int(uid) != ADMIN_ID:
        await update.message.reply_text("⚠️ Bot সাময়িকভাবে বন্ধ। পরে আসুন।"); return

    # ── Admin broadcast mode ──
    if int(uid) == ADMIN_ID and admin_set_mode.get(uid) == "broadcast":
        admin_set_mode.pop(uid, None)
        users = load_json(USER_FILE)
        async def _send(tid):
            try:
                await context.bot.send_message(chat_id=int(tid), text=f"📢 Admin Message:\n\n{msg}")
                return 1
            except: return 0
        results = await asyncio.gather(*[_send(tid) for tid in users], return_exceptions=True)
        sent = sum(r for r in results if r == 1)
        await update.message.reply_text(f"✅ {sent} জনকে পাঠানো হয়েছে!", reply_markup=admin_main_kb()); return

    # ── Admin set mode (payment/price) ──
    if int(uid) == ADMIN_ID and uid in admin_set_mode:
        key = admin_set_mode.pop(uid)
        if key == "price":
            try:
                global VIP_PRICE; VIP_PRICE = int(msg.strip())
                await update.message.reply_text(f"✅ VIP Price আপডেট: {VIP_PRICE}৳", reply_markup=admin_main_kb())
            except:
                await update.message.reply_text("❌ শুধু সংখ্যা লিখো!")
        else:
            PAYMENT_INFO[key] = msg.strip()
            await update.message.reply_text(f"✅ {key.upper()} আপডেট: {msg.strip()}", reply_markup=admin_main_kb())
        return

    # ── XP ──
    add_xp(uid, 1)

    # ── Signal confirm (text fallback) ──
    if uid in pending_signal_confirm:
        yes = ["yes","হ্যা","হে","হ্যাঁ","ha","হা","ok","okay","ওকে","sure","start","শুরু","দাও","দে"]
        if any(w in msg_low for w in yes):
            pending_signal_confirm.discard(uid)
            await run_signal_session(update, uid)
        else:
            pending_signal_confirm.discard(uid)
            await update.message.reply_text("❌ বাতিল।", reply_markup=main_kb(uid))
        return

    # ── Payment TXN ID ──
    if uid in pending_txn and len(msg.strip()) >= 5:
        await handle_txn_id(update, context, uid, msg.strip()); return

    # ── Keyboard button handlers ──
    if msg == "📊 Signal নিন":
        pending_signal_confirm.add(uid)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ হ্যাঁ, Signal চাই", callback_data="sig_yes")],
            [InlineKeyboardButton("❌ না", callback_data="sig_no")],
        ])
        await update.message.reply_text("📊 Signal শুরু করবো?\n\nনিচের বাটনে চাপো 👇", reply_markup=kb)
        return

    if msg == "💎 VIP কিনুন":
        await buy(update, context); return

    if msg == "📈 আমার স্ট্যাটাস":
        await status_cmd(update, context); return

    if msg == "📋 হেল্প":
        await help_cmd(update, context); return

    if msg == "📞 সাপোর্ট":
        await support_cmd(update, context); return

    # ── Admin keyboard ──
    if int(uid) == ADMIN_ID:
        if msg == "👤 Profile":
            await handle_admin_callback_text(update, context, "admin_profile"); return
        if msg == "💳 Payment Settings":
            await handle_admin_callback_text(update, context, "admin_payment"); return
        if msg == "📢 Broadcast":
            admin_set_mode[uid] = "broadcast"
            await update.message.reply_text(
                "📢 সব user কে পাঠাতে চাও?\n\nএখন message লিখো:\n(পরের message টা সবার কাছে যাবে)",
                reply_markup=admin_main_kb()
            ); return
        if msg == "📋 All Commands":
            await owner_assistant(update, context); return
        if msg == "🔙 User Menu":
            await start(update, context); return
        if msg in ["admin","এডমিন"]:
            await admin_panel(update, context); return

    # ── Signal text triggers ──
    sig_triggers = ["signal dao","সিগনাল দাও","signal daw","এন্ট্রি দাও","signal","সিগনাল"]
    if any(t == msg_low for t in sig_triggers):
        pending_signal_confirm.add(uid)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ হ্যাঁ, Signal চাই", callback_data="sig_yes")],
            [InlineKeyboardButton("❌ না", callback_data="sig_no")],
        ])
        await update.message.reply_text("📊 Signal শুরু করবো?\n\nনিচের বাটনে চাপো 👇", reply_markup=kb)
        return

    # ── ADMIN only reply, other users get nothing (AI বাদ) ──
    if int(uid) == ADMIN_ID:
        await update.message.reply_text(
            "❓ বুঝলাম না।\nনিচের বাটন ব্যবহার করো 👇",
            reply_markup=admin_main_kb()
        )
    # অন্য user দের কোনো reply নেই — AI বাদ

async def handle_admin_callback_text(update, context, action):
    """Admin keyboard button এর জন্য inline panel দেখানো"""
    d     = load_json(DATA_FILE)
    users = load_json(USER_FILE)
    today = str(datetime.now().date())

    if action == "admin_profile":
        total_users  = len(users)
        active_vip   = sum(1 for u in users.values() if u.get("is_vip"))
        today_vip    = sum(1 for u in users.values()
                          if u.get("is_vip") and u.get("last_reset") == today)
        total_vip    = d.get("total_vip", 0)
        total_income = d.get("total_income", 0)
        bot_on       = d.get("bot_on", True)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Bot বন্ধ" if bot_on else "🟢 Bot চালু",
                                  callback_data="admin_toggle_bot")],
        ])
        await update.message.reply_text(
            "👤 Profile\n\n"
            f"👥 মোট User     : {total_users} জন\n"
            f"💎 Active VIP   : {active_vip} জন\n"
            f"🆕 আজ VIP হয়েছে: {today_vip} জন\n"
            f"💰 আজ আয়       : {today_vip*VIP_PRICE}৳\n"
            f"🏆 মোট VIP sold : {total_vip}\n"
            f"💵 মোট আয়      : {total_income}৳\n"
            f"🤖 Bot: {'🟢 ON' if bot_on else '🔴 OFF'}",
            reply_markup=kb
        )

    elif action == "admin_payment":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 bKash নম্বর বদলাও",  callback_data="admin_set_bkash")],
            [InlineKeyboardButton("📱 Nagad নম্বর বদলাও",  callback_data="admin_set_nagad")],
            [InlineKeyboardButton("💳 Binance ID বদলাও",   callback_data="admin_set_binance")],
            [InlineKeyboardButton(f"💰 VIP Price (এখন {VIP_PRICE}৳)", callback_data="admin_set_price")],
        ])
        await update.message.reply_text(
            "💳 Payment Settings\n\n"
            f"📱 bKash  : {PAYMENT_INFO['bkash']}\n"
            f"📱 Nagad  : {PAYMENT_INFO['nagad']}\n"
            f"💳 Binance: {PAYMENT_INFO['binance']}\n"
            f"💰 VIP Price: {VIP_PRICE}৳",
            reply_markup=kb
        )

# =========================
# Voice
# =========================
async def voice_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.voice: return
    uid = str(update.message.from_user.id)
    try:
        vf = await update.message.voice.get_file()
        fp = f"voice_{uid}.ogg"; await vf.download_to_drive(fp)
        try: os.remove(fp)
        except: pass
        await update.message.reply_text("🎙️ Voice পেয়েছি! Text এ লিখলে ভালো হয় 😊")
    except Exception as e:
        print(f"Voice error: {e}")

# =========================
# RUN
# =========================
def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .concurrent_updates(True)
        .build()
    )
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("buy",        buy))
    app.add_handler(CommandHandler("signal_dao", signal_dao_cmd))
    app.add_handler(CommandHandler("vip_on",     vip_on))
    app.add_handler(CommandHandler("status",     status_cmd))
    app.add_handler(CommandHandler("help",       help_cmd))
    app.add_handler(CommandHandler("admin",      admin_panel))
    app.add_handler(CommandHandler("me",         owner_assistant))
    app.add_handler(CallbackQueryHandler(signal_confirm_callback, pattern="^sig_(yes|no)$"))
    app.add_handler(CallbackQueryHandler(payment_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    app.add_handler(MessageHandler(filters.VOICE, voice_reply))
    print("Claw VIP Bot ON! 🔥 [Pro Mode — No AI — Real Win/Loss]")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
