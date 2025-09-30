import os, math
from typing import Any, Dict, Optional, List
from fastapi import FastAPI, Request, HTTPException
import httpx

app = FastAPI(title="AlphaFlow — Discord Alerts")

# --- ENV ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
CHAN_FREE = os.getenv("DISCORD_CHANNEL_FREE", "")
CHAN_PRO  = os.getenv("DISCORD_CHANNEL_PRO", "")

DEFAULT_STOP_ATR = float(os.getenv("DEFAULT_STOP_ATR", "1.5"))
DEFAULT_TP1_RR   = float(os.getenv("DEFAULT_TP1_RR", "1.0"))
DEFAULT_TP2_RR   = float(os.getenv("DEFAULT_TP2_RR", "2.0"))

# Affiliate (per exchange). Default to your code; change in Render env if needed.
BINANCE_REF = os.getenv("BINANCE_REF", "1164241722")  # e.g. 1164241722

# ------------ helpers ------------
def _dir(side: str) -> int:
    return 1 if str(side).upper() in ("BUY", "LONG") else -1

def _fmt(n: Optional[float]) -> str:
    if n is None: return "—"
    return f"{float(n):.6f}".rstrip("0").rstrip(".")

def tradingview_url(exchange: Optional[str], tv_symbol: Optional[str], symbol: Optional[str]) -> Optional[str]:
    if tv_symbol and ":" in tv_symbol:
        return f"https://www.tradingview.com/chart/?symbol={tv_symbol}"
    if exchange and symbol:
        return f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}"
    return None

def rr_value(price: Optional[float], stop: Optional[float], tp: Optional[float]) -> Optional[float]:
    if price is None or stop is None or tp is None: return None
    risk = abs(price - stop)
    if risk <= 0: return None
    return abs(tp - price) / risk

def compute_levels(p: Dict[str, Any]) -> Dict[str, Optional[float]]:
    side  = (p.get("side") or "BUY").upper()
    price = p.get("price")
    stop  = p.get("stop")
    tp1   = p.get("tp1")
    tp2   = p.get("tp2")
    tech  = p.get("technicals") or {}
    atr   = tech.get("atr")

    if price is None:
        return {"price": None, "stop": stop, "tp1": tp1, "tp2": tp2}

    if atr and (stop is None or tp1 is None or tp2 is None):
        d = _dir(side)
        if stop is None:
            stop = price - d * (DEFAULT_STOP_ATR * float(atr))
        risk = abs(price - stop) if stop is not None else None
        if risk and tp1 is None: tp1 = price + d * (risk * DEFAULT_TP1_RR)
        if risk and tp2 is None: tp2 = price + d * (risk * DEFAULT_TP2_RR)
    return {"price": price, "stop": stop, "tp1": tp1, "tp2": tp2}

def estimate_confidence(p: Dict[str, Any], rr1: Optional[float], rr2: Optional[float]) -> int:
    if "confidence" in p and p["confidence"] is not None:
        try:
            c=float(p["confidence"])
            if 0<=c<=1: return max(0,min(100,round(c*100)))
            return max(0,min(100,round(c)))
        except: pass

    tech = p.get("technicals") or {}
    side = (p.get("side") or "BUY").upper()

    score = 50
    if rr1: score += min(20, (rr1 - 1.0) * 10)
    if rr2: score += min(10, (rr2 - 2.0) * 5)

    ef, es = tech.get("ema_fast"), tech.get("ema_slow")
    try:
        if ef is not None and es is not None:
            ef, es = float(ef), float(es)
            if side in ("BUY","LONG") and ef > es: score += 10
            if side in ("SELL","SHORT") and ef < es: score += 10
    except: pass

    try:
        rsi = float(tech.get("rsi")) if tech.get("rsi") is not None else None
        if rsi is not None:
            if side in ("BUY","LONG"):
                if rsi >= 55: score += 7
                elif rsi <= 45: score -= 7
            else:
                if rsi <= 45: score += 7
                elif rsi >= 55: score -= 7
    except: pass

    return max(5, min(95, int(round(score))))

MAJOR_ICON = { "BTC":"btc","ETH":"eth","SOL":"sol","BNB":"bnb","XRP":"xrp","DOGE":"doge","ADA":"ada","AVAX":"avax","LINK":"link","TON":"ton" }
def guess_logo_url(sym: str) -> Optional[str]:
    s = (sym or "").upper().replace("USDT","")
    if s in MAJOR_ICON:
        slug = MAJOR_ICON[s]
        return f"https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/{slug}.png"
    return None

def binance_spot_link(symbol: str) -> str:
    base = symbol.upper().replace("USDT","")
    ref  = BINANCE_REF.strip()
    q    = f"?ref={ref}" if ref else ""
    return f"https://www.binance.com/en/trade/{base}_USDT{q}"

def build_links(p: Dict[str, Any]) -> List[str]:
    links: List[str] = []
    sym = (p.get("symbol") or "").upper()
    tvs = p.get("tv_symbol") or (f"BINANCE:{sym}" if sym else None)
    tv = tradingview_url("BINANCE", tvs, sym)
    if tv: links.append(f"[TradingView]({tv})")
    if sym.endswith("USDT"):
        links.append(f"[Binance]({binance_spot_link(sym)})")
    return links

def build_embed(payload: Dict[str, Any], source: str) -> Dict[str, Any]:
    symbol     = payload.get("symbol", "—")
    timeframe  = payload.get("timeframe", "—")
    side       = (payload.get("side") or "BUY").upper()
    reason     = payload.get("reason") or "Automated setup"
    tech       = payload.get("technicals") or {}

    lv = compute_levels(payload)
    price, stop, tp1, tp2 = lv["price"], lv["stop"], lv["tp1"], lv["tp2"]
    rr1 = rr_value(price, stop, tp1)
    rr2 = rr_value(price, stop, tp2)
    conf = estimate_confidence(payload, rr1, rr2)

    title = f"{symbol} • {side} • {timeframe}"
    color = 0x19FD8D if side in ("BUY","LONG") else 0xF04F4F

    fields = [
        {"name":"Price","value":_fmt(price),"inline":True},
        {"name":"Stop","value":_fmt(stop),"inline":True},
        {"name":"TP1","value":_fmt(tp1),"inline":True},
        {"name":"TP2","value":_fmt(tp2),"inline":True},
        {"name":"Confidence","value":f"{conf} / 100","inline":True},
    ]
    rr_txt = []
    if rr1 is not None: rr_txt.append(f"TP1 RR {_fmt(rr1)}")
    if rr2 is not None: rr_txt.append(f"TP2 RR {_fmt(rr2)}")
    if rr_txt: fields.append({"name":"Risk/Reward","value":" • ".join(rr_txt),"inline":True})

    if tech:
        parts = []
        for k in ("rsi","ema_fast","ema_slow","atr"):
            if k in tech and tech[k] is not None:
                try: parts.append(f"{k.upper()} {_fmt(float(tech[k]))}")
                except: parts.append(f"{k.upper()} {tech[k]}")
        if parts: fields.append({"name":"Technicals","value":"  |  ".join(parts),"inline":False})

    author_name = f"AlphaFlow • {source or 'signal'}"
    logo = guess_logo_url(symbol)

    embed: Dict[str, Any] = {
        "title": title, "type":"rich", "color": color,
        "description": reason, "fields": fields,
        "footer": {"text": f"Binance • {timeframe}"},
    }
    if logo:
        embed["thumbnail"] = {"url": logo}
        embed["author"] = {"name": author_name, "icon_url": logo}
    else:
        embed["author"] = {"name": author_name}
    return embed

def build_components(links: List[str]) -> List[Dict[str, Any]]:
    rows = []
    row = {"type":1, "components":[]}
    for md in links:
        try:
            l = md.split("](",1)
            label = l[0][1:]
            url = l[1][:-1]
        except Exception:
            continue
        row["components"].append({"type":2, "style":5, "label":label[:80], "url":url})
        if len(row["components"]) == 5:
            rows.append(row); row={"type":1,"components":[]}
    if row["components"]:
        rows.append(row)
    return rows

async def post_to_discord(channel_id: str, embed: Dict[str, Any], links: Optional[List[str]] = None) -> Dict[str, Any]:
    if not DISCORD_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="DISCORD_BOT_TOKEN not set")
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"}
    payload: Dict[str, Any] = {"embeds":[embed]}
    if links:
        comps = build_components(links)
        if comps: payload["components"] = comps
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 300:
            try: err = r.json()
            except Exception: err = {"text": r.text}
            raise HTTPException(status_code=500, detail={"discord_status": r.status_code, "error": err})
    return {"ok": True}

def pick_channel(tier: Optional[str]) -> str:
    t = (tier or "").lower()
    if t in ("pro","premium","paid"):
        return CHAN_PRO or CHAN_FREE
    return CHAN_FREE or CHAN_PRO

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.post("/send")
async def send(req: Request):
    body = await req.json()
    if "payload" in body:
        tier = body.get("tier")
        source = body.get("source") or "signal"
        payload = body["payload"]
    else:
        tier = body.get("tier")
        source = body.get("source") or "signal"
        payload = body
    channel_id = pick_channel(tier)
    if not channel_id:
        raise HTTPException(status_code=500, detail="No Discord channel configured")
    embed = build_embed(payload, source)
    links = build_links(payload)
    return await post_to_discord(channel_id, embed, links)
