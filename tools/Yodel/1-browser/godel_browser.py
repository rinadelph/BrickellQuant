"""
tools/Yodel/1-browser/godel_browser.py
========================================
Godel Terminal data extractor.

For a given symbol, extracts:
  - OHLCV bars (1m / 5m / 1H / 1D)
  - Options chain (all expirations)
  - News items
  - Transcripts / filings (via news category filter)
  - Search results (instruments + news + people)
  - Chat messages (all channels)
  - Breaking news feed
  - Watchlists
  - Notifications

Everything goes through the live browser session — real cookies, real CF clearance.
Auto-registers a fresh @goyslop.info account when session expires.

Run:
    cd /home/rincon/BrickellQuant
    DISPLAY=:1 .venv/bin/python tools/Yodel/1-browser/godel_browser.py
"""

import json
import time
import random
import string
from datetime import datetime
from pathlib import Path

from cloakbrowser import launch
from playwright.sync_api import Page

# ── Config ────────────────────────────────────────────────────────────────────
REGISTER_URL = "https://app.godelterminal.com/?page=register"
APP_URL      = "https://app.godelterminal.com"
API_URL      = "https://api.godelterminal.com"
CAPTURE_DIR  = Path(__file__).parent / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

SKIP = {
    "sentry.io", "google", "analytics", "adroll", "facebook",
    "twitter", "gtm", "doubleclick", "pippio", "cdn-cgi",
    "rum?", "cloudflare-insights", "challenge-platform",
    "beacon.min", "fbevents", "uwt.js", "roundtrip",
}

def ts():   return datetime.now().strftime("%H:%M:%S")
def log(m): print(f"[{ts()}] {m}", flush=True)

def rand_email():
    slug = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"{slug}@goyslop.info"

def rand_pass():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))


# ══════════════════════════════════════════════════════════════════════════════
# Browser session — handles launch, auto-register, and passive capture
# ══════════════════════════════════════════════════════════════════════════════

class GodelSession:
    def __init__(self):
        self.page:         Page = None
        self.browser             = None
        self.logged_in           = False
        self.dead                = False
        self._calls:       list  = []
        self._consecutive_403    = 0

    def start(self):
        log("🚀 Launching fresh CloakBrowser (zero cookies)…")
        self.browser = launch(
            headless=False,
            humanize=True,
            args=[f"--fingerprint={random.randint(10000,99999)}", "--start-maximized"],
        )
        ctx  = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US", timezone_id="America/New_York",
        )
        self.page = ctx.new_page()

        # Passive listeners — no route interception
        self.page.on("response", self._on_response)

        # Open registration page
        log(f"🌐 {REGISTER_URL}")
        try:
            self.page.goto(REGISTER_URL, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            log(f"  nav: {e}")

        # Wait for page to settle before touching anything
        time.sleep(4)
        self._auto_register()

        # Wait for any API call to return 200 (means we're logged in)
        # Use expect_response — proper sync Playwright API, no threading needed
        log("⏳ Waiting for session to go live (up to 3 min)…")
        try:
            with self.page.expect_response(
                lambda r: any(x in r.url for x in ["/api/", "/v1/", "/v2/"]) and r.status < 400,
                timeout=180_000
            ) as resp_info:
                pass
            self.logged_in = True
            log("✅ Session live!")
            return True
        except Exception as e:
            log(f"⚠  Could not detect login: {e}")
            return False

    def _auto_register(self):
        email = rand_email()
        pwd   = rand_pass()
        log(f"📧 Registering: {email}")
        try:
            self.page.wait_for_selector(
                "input[type=email], input[name=username], input[name=email]",
                timeout=15000
            )
            time.sleep(0.6)
            for sel, val in [
                ("input[type=email], input[name=username], input[name=email]", email),
                ("input[type=password], input[name=password]",                 pwd),
            ]:
                el = self.page.query_selector(sel)
                if el:
                    el.click(); time.sleep(0.2)
                    self.page.keyboard.type(val, delay=55)
                    time.sleep(0.3)

            submit = self.page.query_selector(
                "button[type=submit], button:has-text('Register'), "
                "button:has-text('Sign Up'), button:has-text('Create')"
            )
            time.sleep(0.4)
            if submit:
                submit.click()
            else:
                self.page.keyboard.press("Enter")
            log("✅ Registration submitted")
            time.sleep(3)
        except Exception as e:
            log(f"⚠  Register: {e}")

    def _on_response(self, response):
        url    = response.url
        status = response.status
        if any(s in url for s in SKIP): return
        if not any(x in url for x in ["/api/", "/v1/", "/v2/"]): return

        # Parse body
        body = None
        try:
            ct = response.headers.get("content-type", "")
            if "json" in ct:
                body = response.json()
        except: pass

        clean = url.replace(API_URL,"").replace(APP_URL,"")
        icon  = "✅" if status < 400 else "❌"
        log(f"  {icon} {status} {response.request.method} {clean[:70]}")

        if status < 400:
            if not self.logged_in:
                log("🟢 SESSION LIVE")
            self.logged_in        = True
            self._consecutive_403 = 0
            if body:
                preview = json.dumps(body)[:120] if isinstance(body,(dict,list)) else str(body)[:120]
                log(f"     → {preview}")
        elif status == 403:
            self._consecutive_403 += 1
            if self.logged_in and self._consecutive_403 >= 5:
                log("💀 Session expired")
                self.dead = True

        self._calls.append({
                "ts": datetime.now().isoformat(),
                "method": response.request.method,
                "url": url, "status": status, "resp": body,
            })

    def close(self):
        try: self.browser.close()
        except: pass

    def calls(self): return list(self._calls)

    # ── Core: navigate and wait for a specific API response ──────────────
    def _get(self, url_fragment: str, nav_url: str, wait_ms: int = 10000):
        """Navigate to nav_url and wait for a response matching url_fragment."""
        try:
            with self.p.expect_response(
                lambda r: url_fragment in r.url and r.status < 400,
                timeout=wait_ms
            ) as resp_info:
                self._go(nav_url, wait=0)
            resp = resp_info.value
            ct   = resp.headers.get("content-type","")
            return resp.json() if "json" in ct else None
        except Exception as e:
            log(f"  ⚠  _get({url_fragment}): {e}")
            return None


# ══════════════════════════════════════════════════════════════════════════════
# Data extractors — the actual useful methods
# ══════════════════════════════════════════════════════════════════════════════

class GodelData:
    """
    High-level data extraction API for Godel Terminal.
    Each method returns clean data for a given symbol or feed.
    """

    def __init__(self, session: GodelSession):
        self.s = session
        self.p = session.page

    # ── Navigate to a page and wait ───────────────────────────────────────
    def _go(self, url: str, wait=2):
        try:
            self.p.goto(url, timeout=15000, wait_until="domcontentloaded")
            time.sleep(wait)
        except Exception as e:
            log(f"  nav {url}: {e}")

    def bars(self, symbol: str, timeframe: str = "1D", count: int = 300) -> dict:
        """OHLCV bars for any symbol and timeframe."""
        log(f"\n📊 bars({symbol}, {timeframe})")
        r = self._get("/api/tv-advanced/bars", f"{APP_URL}?ticker={symbol}")
        return r or {}

    def options(self, symbol: str) -> dict:
        """Full options chain (all expirations, all strikes)."""
        log(f"\n📐 options({symbol})")
        r = self._get("/api/v1/optionsv2", f"{APP_URL}?ticker={symbol}")
        return r or {}

    def news(self, symbol: str = None, size: int = 50) -> list:
        """News items."""
        log(f"\n📰 news({symbol or 'market'})")
        nav = f"{APP_URL}?ticker={symbol}&page=news" if symbol else f"{APP_URL}?page=news"
        r   = self._get("/api/news/items", nav)
        if isinstance(r, dict):
            return r.get("content", [])
        return r or []

    def breaking(self) -> list:
        """Real-time breaking news with impact analysis."""
        log(f"\n🔴 breaking()")
        r = self._get("fetchBreaking", APP_URL)
        return r or []

    def chat_channels(self) -> list:
        """All available chat channels."""
        log(f"\n💬 chat_channels()")
        r = self._get("/api/chat/channels", APP_URL)
        return r or []

    def chat_messages(self, channel_id: str, size: int = 100) -> list:
        """Messages from a chat channel."""
        log(f"\n💬 chat_messages({channel_id[:20]}…)")
        r = self._get(f"/channels/{channel_id}/messages", f"{APP_URL}?page=chat")
        if isinstance(r, dict):
            return r.get("content", [])
        return r or []

    def search(self, query: str) -> dict:
        """Search across instruments, news, and people."""
        log(f"\n🔍 search({query})")
        results = {"instruments": [], "news": [], "people": []}
        # Type in command bar
        try:
            self.p.keyboard.press("Control+k")
            time.sleep(0.3)
            self.p.keyboard.type(query, delay=60)
        except: pass

        for kind in ["instruments", "news", "people"]:
            try:
                with self.p.expect_response(
                    lambda r, k=kind: f"types={k}" in r.url and query in r.url and r.status < 400,
                    timeout=5000
                ) as ri:
                    pass
                results[kind] = ri.value.json().get(kind, [])
            except: pass

        try: self.p.keyboard.press("Escape")
        except: pass
        return results

    def watchlists(self) -> list:
        """All user watchlists."""
        log(f"\n📋 watchlists()")
        r = self._get("/api/v1/watchlists", f"{APP_URL}?page=watchlist")
        return r or []

    def resolve(self, symbol: str) -> dict:
        """Full metadata for a symbol."""
        log(f"\n🏷  resolve({symbol})")
        r = self._get("resolve-symbol", f"{APP_URL}?ticker={symbol}")
        if isinstance(r, dict):
            return r.get("data", r)
        return {}

    def full_symbol_dump(self, symbol: str) -> dict:
        """Everything Godel has on a symbol."""
        log(f"\n{'═'*60}\n  🎯 Full dump: {symbol}\n{'═'*60}")
        out = {
            "symbol":    symbol,
            "timestamp": datetime.now().isoformat(),
            "metadata":  self.resolve(symbol),
            "bars_1D":   self.bars(symbol, "1D"),
            "bars_1H":   self.bars(symbol, "1H"),
            "options":   self.options(symbol),
            "news":      self.news(symbol),
            "search":    self.search(symbol),
        }
        f = CAPTURE_DIR / f"{symbol}_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        f.write_text(json.dumps(out, indent=2, default=str))
        log(f"  💾 {f.name}")
        return out

    def full_market_dump(self) -> dict:
        """Everything market-wide."""
        log(f"\n{'═'*60}\n  🌍 Full market dump\n{'═'*60}")
        channels  = self.chat_channels()
        chat_data = {}
        for ch in channels[:10]:
            cid = ch.get("id","")
            if cid:
                chat_data[ch.get("title", cid)] = self.chat_messages(cid)
        out = {
            "timestamp":  datetime.now().isoformat(),
            "breaking":   self.breaking(),
            "news":       self.news(),
            "watchlists": self.watchlists(),
            "chat":       chat_data,
        }
        f = CAPTURE_DIR / f"market_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        f.write_text(json.dumps(out, indent=2, default=str))
        log(f"  💾 {f.name}")
        return out


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "═"*70)
    print("  🔬 GODEL DATA EXTRACTOR")
    print("  Extracts: bars, options, news, chat, breaking, search")
    print("═"*70)

    while True:
        session = GodelSession()
        ok      = session.start()

        if not ok:
            log("Session failed, retrying in 5s…")
            session.close()
            time.sleep(5)
            continue

        data = GodelData(session)

        print("\n" + "─"*70)
        print("  [1] Full symbol dump  (bars + options + news + search)")
        print("  [2] Full market dump  (breaking + chat + watchlists + news)")
        print("  [3] Bars only")
        print("  [4] Options only")
        print("  [5] News only")
        print("  [6] Chat dump")
        print("  [7] Breaking news")
        print("  [q] Quit")
        print("─"*70)

        choice = input("  Choice: ").strip().lower()

        if choice == "q":
            session.close()
            break

        elif choice == "1":
            sym = input("  Symbol: ").strip().upper()
            result = data.full_symbol_dump(sym)
            print(f"\n  bars_1D rows : {len(result.get('bars_1D',{}).get('data',{}).get('data',[]))}")
            print(f"  options exp  : {len(result.get('options',{}).get('expirations',[]))}")
            print(f"  news items   : {len(result.get('news',[]))}")
            print(f"  search hits  : {len(result.get('search',{}).get('instruments',[]))}")

        elif choice == "2":
            result = data.full_market_dump()
            print(f"\n  breaking     : {len(result.get('breaking',[]))} items")
            print(f"  news         : {len(result.get('news',[]))} items")
            print(f"  watchlists   : {len(result.get('watchlists',[]))}")
            print(f"  chat chans   : {len(result.get('chat',{}))}")

        elif choice == "3":
            sym = input("  Symbol: ").strip().upper()
            tf  = input("  Timeframe (1D/1H/5/1): ").strip() or "1D"
            r   = data.bars(sym, tf)
            rows = r.get("data",{}).get("data",[])
            print(f"\n  {len(rows)} bars | latest: {rows[-1] if rows else 'none'}")

        elif choice == "4":
            sym = input("  Symbol: ").strip().upper()
            r   = data.options(sym)
            exps = r.get("expirations",[])
            print(f"\n  {len(exps)} expirations")
            for e in exps[:5]:
                print(f"    {e.get('date')}  ({len(e.get('options',[]))} strikes)")

        elif choice == "5":
            sym = input("  Symbol (blank=market): ").strip().upper() or None
            r   = data.news(sym)
            print(f"\n  {len(r)} articles")
            for item in r[:5]:
                print(f"    [{item.get('providerName','?')}] {item.get('id','')[:60]}")

        elif choice == "6":
            channels = data.chat_channels()
            print(f"\n  {len(channels)} channels:")
            for i, ch in enumerate(channels):
                print(f"    [{i}] {ch.get('title')} ({ch.get('id','')})")
            idx = input("  Channel index: ").strip()
            if idx.isdigit() and int(idx) < len(channels):
                ch   = channels[int(idx)]
                msgs = data.chat_messages(ch["id"], 100)
                print(f"\n  {len(msgs)} messages in #{ch.get('title')}:")
                for m in msgs[:10]:
                    print(f"    [{m.get('createdAt','')}] {m.get('content','')[:80]}")

        elif choice == "7":
            r = data.breaking()
            print(f"\n  {len(r)} breaking items:")
            for item in r[:10]:
                impact = [i.get("symbol") for i in item.get("impact",[])]
                print(f"\n  [{item.get('time','')}] {item.get('data',{}).get('content','')[:100]}")
                if impact:
                    print(f"    Impact: {impact}")

        # Check if session died
        if session.dead:
            log("\n💀 Session expired — restarting with fresh account…")
            session.close()
            time.sleep(2)
            continue

        another = input("\n  Another action? [y/n]: ").strip().lower()
        if another != "y":
            session.close()
            break


if __name__ == "__main__":
    main()
