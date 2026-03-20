"""
tools/Yodel/1-browser/launch.py
================================
Step 1 — Launch a persistent Chromium browser, navigate to the target site,
and map its full API surface by intercepting every network request/response.

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/1-browser/launch.py

Output:
    - Live console: every request/response logged in real-time
    - screenshots/  folder: full-page PNG at each visited page
    - api_map.json  in 1-browser/: captured API surface (routes, payloads, headers)
    - dom_map.json  in 1-browser/: forms, inputs, buttons, nav links found on each page
"""

import json
import sys
import time
import re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root

from playwright.sync_api import sync_playwright, Request, Response, Page

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_URL   = "https://app.godelterminal.com/?page=register"
OUT_DIR      = Path(__file__).parent
SCREENSHOTS  = OUT_DIR / "screenshots"
API_MAP_FILE = OUT_DIR / "api_map.json"
DOM_MAP_FILE = OUT_DIR / "dom_map.json"

SCREENSHOTS.mkdir(exist_ok=True)

# ── State collectors ─────────────────────────────────────────────────────────
api_calls: list[dict] = []
dom_map:   list[dict] = []

# ── Helpers ───────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def is_api_request(req: Request) -> bool:
    """Filter to only interesting XHR / fetch / API calls."""
    url = req.url
    resource = req.resource_type
    if resource in ("xhr", "fetch", "websocket"):
        return True
    # also catch any JSON endpoint even if resource type is "other"
    if any(x in url for x in ("/api/", "/v1/", "/v2/", "/graphql", ".json")):
        return True
    return False


def safe_headers(headers: dict) -> dict:
    """Keep only non-sensitive headers for logging."""
    skip = {"cookie", "authorization", "x-auth-token", "set-cookie"}
    return {k: v for k, v in headers.items() if k.lower() not in skip}


def on_request(req: Request):
    if not is_api_request(req):
        return
    entry = {
        "time":     ts(),
        "method":   req.method,
        "url":      req.url,
        "type":     req.resource_type,
        "headers":  safe_headers(dict(req.headers)),
        "post_data": None,
        "response": None,
    }
    try:
        pd = req.post_data
        if pd:
            try:
                entry["post_data"] = json.loads(pd)
            except Exception:
                entry["post_data"] = pd
    except Exception:
        pass

    api_calls.append(entry)
    print(f"  [{ts()}] ➤ {req.method:6s} {req.url[:100]}")


def on_response(resp: Response):
    if not is_api_request(resp.request):
        return
    body_preview = ""
    try:
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            body = resp.json()
            body_preview = json.dumps(body)[:400]
        elif "text" in ct:
            body_preview = resp.text()[:400]
    except Exception:
        pass

    # Back-fill the response into the matching api_calls entry
    for entry in reversed(api_calls):
        if entry["url"] == resp.request.url and entry["response"] is None:
            entry["response"] = {
                "status":   resp.status,
                "headers":  safe_headers(dict(resp.headers)),
                "preview":  body_preview,
            }
            break

    status_icon = "✅" if resp.status < 400 else "❌"
    print(f"  [{ts()}] {status_icon} {resp.status} ← {resp.url[:100]}")
    if body_preview:
        print(f"            body: {body_preview[:120]}")


def on_websocket(ws):
    print(f"  [{ts()}] 🔌 WS OPEN  {ws.url[:100]}")
    ws.on("framereceived", lambda f: print(f"  [{ts()}] 📨 WS RECV  {str(f)[:120]}"))
    ws.on("framesent",     lambda f: print(f"  [{ts()}] 📤 WS SEND  {str(f)[:120]}"))
    ws.on("close",         lambda _: print(f"  [{ts()}] 🔌 WS CLOSE {ws.url[:60]}"))


def snapshot_dom(page: Page, label: str):
    """Extract and record all interactive elements + page structure."""
    print(f"\n  📸 DOM snapshot: {label}")
    entry: dict = {"label": label, "url": page.url, "title": page.title()}

    # ── Navigation links ──────────────────────────────────────────────────────
    links = page.evaluate("""() =>
        [...document.querySelectorAll('a[href]')].map(a => ({
            text: a.innerText.trim().slice(0, 80),
            href: a.href,
        })).filter(l => l.href && !l.href.startsWith('javascript'))
    """)
    entry["links"] = links[:60]
    print(f"     links found: {len(links)}")

    # ── Forms & inputs ────────────────────────────────────────────────────────
    forms = page.evaluate("""() =>
        [...document.querySelectorAll('form')].map(f => ({
            id:     f.id,
            action: f.action,
            method: f.method || 'GET',
            inputs: [...f.querySelectorAll('input,textarea,select')].map(i => ({
                type:        i.type || i.tagName.toLowerCase(),
                name:        i.name,
                id:          i.id,
                placeholder: i.placeholder,
                required:    i.required,
            }))
        }))
    """)
    entry["forms"] = forms
    print(f"     forms found: {len(forms)}")
    for f in forms:
        print(f"       form action={f.get('action','?')} method={f.get('method','?')}")
        for inp in f.get("inputs", []):
            print(f"         input: type={inp.get('type')} name={inp.get('name')} placeholder={inp.get('placeholder')}")

    # ── Buttons ───────────────────────────────────────────────────────────────
    buttons = page.evaluate("""() =>
        [...document.querySelectorAll('button,[role=button],[type=submit]')].map(b => ({
            text:     b.innerText.trim().slice(0, 60),
            type:     b.type,
            id:       b.id,
            classes:  b.className.slice(0, 80),
        }))
    """)
    entry["buttons"] = buttons[:40]
    print(f"     buttons found: {len(buttons)}")
    for b in buttons[:10]:
        print(f"       btn: '{b.get('text','')}' type={b.get('type')} id={b.get('id')}")

    # ── Potential route tokens from <script> / window vars ───────────────────
    routes_in_scripts = page.evaluate("""() => {
        const text = document.documentElement.innerHTML;
        const matches = text.match(/["'](\/[a-zA-Z0-9_\-\/]+)["']/g) || [];
        return [...new Set(matches.map(m => m.slice(1,-1)))].slice(0, 80);
    }""")
    entry["route_tokens"] = routes_in_scripts
    print(f"     route tokens in HTML: {len(routes_in_scripts)}")

    # ── Page-level JS global keys ─────────────────────────────────────────────
    global_keys = page.evaluate("""() =>
        Object.keys(window).filter(k => !['chrome','0','window','self','top','parent',
            'frames','length','closed','opener','frameElement','external','screen',
            'history','location','document','navigator','performance','localStorage',
            'sessionStorage','indexedDB','caches','crypto','console','alert','confirm',
            'prompt','print','fetch','XMLHttpRequest','WebSocket','Worker','Blob',
            'ArrayBuffer','FormData','URL','URLSearchParams','Headers','Request',
            'Response','Event','CustomEvent','EventTarget','addEventListener',
            'removeEventListener','dispatchEvent','requestAnimationFrame',
            'cancelAnimationFrame','setTimeout','clearTimeout','setInterval',
            'clearInterval','getComputedStyle','scrollTo','scrollBy','scroll',
            'innerWidth','innerHeight','outerWidth','outerHeight','pageXOffset',
            'pageYOffset','screenX','screenY','screenLeft','screenTop','scrollX',
            'scrollY','origin','isSecureContext','visualViewport','devicePixelRatio',
            'matchMedia'].includes(k) && !k.startsWith('_'))
    """)
    entry["window_globals"] = global_keys[:60]
    print(f"     window globals: {global_keys[:15]}")

    dom_map.append(entry)
    return entry


def take_screenshot(page: Page, name: str):
    path = SCREENSHOTS / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  📷 Screenshot → {path}")
    return str(path)


def save_maps():
    API_MAP_FILE.write_text(json.dumps(api_calls, indent=2, default=str))
    DOM_MAP_FILE.write_text(json.dumps(dom_map,   indent=2, default=str))
    print(f"\n  💾 api_map.json → {API_MAP_FILE}  ({len(api_calls)} calls)")
    print(f"  💾 dom_map.json → {DOM_MAP_FILE}  ({len(dom_map)} snapshots)")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 70)
    print("  🔭 GODEL TERMINAL — API Surface Explorer")
    print(f"  Target: {TARGET_URL}")
    print("═" * 70)

    with sync_playwright() as pw:
        # ── Launch a VISIBLE browser ─────────────────────────────────────────
        browser = pw.chromium.launch(
            headless=False,
            slow_mo=80,
            args=["--start-maximized"],
        )

        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            record_har_path=str(OUT_DIR / "godel.har"),  # full HAR dump too
        )

        # ── Wire up network interceptors ─────────────────────────────────────
        context.on("request",   on_request)
        context.on("response",  on_response)
        context.on("websocket", on_websocket)

        page = context.new_page()

        # ── 1. Register page ─────────────────────────────────────────────────
        print(f"\n  ▶ Navigating to register page…")
        page.goto(TARGET_URL, wait_until="networkidle", timeout=30_000)
        time.sleep(2)

        take_screenshot(page, "01_register")
        snapshot_dom(page, "register_page")

        # ── 2. Check for login link / page ───────────────────────────────────
        print(f"\n  ▶ Looking for login link…")
        login_link = page.query_selector("a[href*='login'], a[href*='signin'], button:has-text('Sign In'), button:has-text('Log In'), a:has-text('Login')")
        if login_link:
            href = login_link.get_attribute("href") or ""
            text = login_link.inner_text()
            print(f"     found: '{text}' → {href}")

        # Check if there's a ?page=login route
        print(f"\n  ▶ Navigating to login page…")
        page.goto("https://app.godelterminal.com/?page=login", wait_until="networkidle", timeout=20_000)
        time.sleep(2)
        take_screenshot(page, "02_login")
        snapshot_dom(page, "login_page")

        # ── 3. Explore dashboard / home (may redirect if not authed) ─────────
        print(f"\n  ▶ Navigating to home/dashboard…")
        page.goto("https://app.godelterminal.com/", wait_until="networkidle", timeout=20_000)
        time.sleep(2)
        take_screenshot(page, "03_home")
        snapshot_dom(page, "home_page")

        # ── 4. Try common sub-routes ──────────────────────────────────────────
        candidate_routes = [
            "?page=dashboard",
            "?page=portfolio",
            "?page=research",
            "?page=screener",
            "?page=watchlist",
            "?page=alerts",
            "?page=settings",
            "?page=pricing",
        ]
        for route in candidate_routes:
            url = f"https://app.godelterminal.com/{route}"
            print(f"\n  ▶ Probing {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=10_000)
                time.sleep(1)
                final_url = page.url
                title = page.title()
                print(f"     → {final_url}  [{title}]")
                # Only screenshot if we actually got somewhere different
                slug = route.replace("?page=", "").replace("/", "_")
                take_screenshot(page, f"04_{slug}")
                snapshot_dom(page, f"route_{slug}")
            except Exception as e:
                print(f"     ⚠ {e}")

        # ── 5. Save everything ────────────────────────────────────────────────
        save_maps()

        print("\n" + "═" * 70)
        print("  ✅ Initial scan complete!")
        print(f"  📁 Artifacts in: {OUT_DIR}")
        print("  🌐 Browser staying open — press Ctrl+C to quit")
        print("═" * 70)

        # ── Keep the browser alive ────────────────────────────────────────────
        try:
            while True:
                time.sleep(2)
                save_maps()   # keep refreshing JSON as new requests come in
        except KeyboardInterrupt:
            print("\n  👋 Shutting down…")
            save_maps()
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
