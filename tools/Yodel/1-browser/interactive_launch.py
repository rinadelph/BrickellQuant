"""
tools/Yodel/1-browser/interactive_launch.py
===========================================
Interactive browser launcher for Cloudflare-protected sites.

Workflow:
1. Launch browser and go to registration page
2. User manually handles Cloudflare challenge
3. User registers an account
4. User presses ENTER when ready
5. THEN we start capturing the API surface

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/1-browser/interactive_launch.py
"""

import json
import sys
import time
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Request,
    Response,
)


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
capture_enabled = False  # Only start capturing after user is ready

# ── Helpers ───────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def is_api_request(req: Request) -> bool:
    """Filter to only interesting XHR / fetch / API calls."""
    if not capture_enabled:
        return False
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


async def on_request(req: Request):
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


async def on_response(resp: Response):
    if not is_api_request(resp.request):
        return
    body_preview = ""
    try:
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            body = await resp.json()
            body_preview = json.dumps(body)[:400]
        elif "text" in ct:
            body_preview = await resp.text()
            body_preview = body_preview[:400]
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
    if not capture_enabled:
        return
    print(f"  [{ts()}] 🔌 WS OPEN  {ws.url[:100]}")
    ws.on("framereceived", lambda f: print(f"  [{ts()}] 📨 WS RECV  {str(f)[:120]}"))
    ws.on("framesent",     lambda f: print(f"  [{ts()}] 📤 WS SEND  {str(f)[:120]}"))
    ws.on("close",         lambda _: print(f"  [{ts()}] 🔌 WS CLOSE {ws.url[:60]}"))


async def snapshot_dom(page: Page, label: str):
    """Extract and record all interactive elements + page structure."""
    print(f"\n  📸 DOM snapshot: {label}")
    entry: dict = {"label": label, "url": page.url, "title": await page.title()}

    # ── Navigation links ──────────────────────────────────────────────────────
    links = await page.evaluate("""() =>
        [...document.querySelectorAll('a[href]')].map(a => ({
            text: a.innerText.trim().slice(0, 80),
            href: a.href,
        })).filter(l => l.href && !l.href.startsWith('javascript'))
    """)
    entry["links"] = links[:60]
    print(f"     links found: {len(links)}")

    # ── Forms & inputs ────────────────────────────────────────────────────────
    forms = await page.evaluate("""() =>
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

    # ── Buttons ───────────────────────────────────────────────────────────────
    buttons = await page.evaluate("""() =>
        [...document.querySelectorAll('button,[role=button],[type=submit]')].map(b => ({
            text:     b.innerText.trim().slice(0, 60),
            type:     b.type,
            id:       b.id,
            classes:  b.className.slice(0, 80),
        }))
    """)
    entry["buttons"] = buttons[:40]
    print(f"     buttons found: {len(buttons)}")

    # ── Page-level JS global keys ─────────────────────────────────────────────
    global_keys = await page.evaluate("""() =>
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

    dom_map.append(entry)
    return entry


async def take_screenshot(page: Page, name: str):
    path = SCREENSHOTS / f"{name}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"  📷 Screenshot → {path}")
    return str(path)


def save_maps():
    API_MAP_FILE.write_text(json.dumps(api_calls, indent=2, default=str))
    DOM_MAP_FILE.write_text(json.dumps(dom_map,   indent=2, default=str))
    print(f"\n  💾 api_map.json → {API_MAP_FILE}  ({len(api_calls)} calls)")
    print(f"  💾 dom_map.json → {DOM_MAP_FILE}  ({len(dom_map)} snapshots)")


# ── Interactive functions ─────────────────────────────────────────────────────

async def wait_for_user() -> bool:
    """Wait for user to press ENTER, or 'q' to quit."""
    print("\n" + "─" * 70)
    print("  ⏸  ACTION REQUIRED:")
    print("  1. Complete the Cloudflare challenge (if any)")
    print("  2. Register a new account")
    print("  3. Log in to the application")
    print("  4. Press ENTER when ready to start capturing API calls")
    print("     (or type 'q' + ENTER to quit)")
    print("─" * 70)

    loop = asyncio.get_event_loop()
    future = loop.create_future()

    def on_input():
        line = sys.stdin.readline().strip().lower()
        future.set_result(line != 'q')

    loop.add_reader(sys.stdin.fileno(), on_input)
    try:
        return await future
    finally:
        loop.remove_reader(sys.stdin.fileno())


async def explore_routes(page: Page):
    """Once logged in, explore common routes."""
    candidate_routes = [
        ("", "home"),
        ("?page=dashboard", "dashboard"),
        ("?page=portfolio", "portfolio"),
        ("?page=research", "research"),
        ("?page=screener", "screener"),
        ("?page=watchlist", "watchlist"),
        ("?page=alerts", "alerts"),
        ("?page=settings", "settings"),
        ("?page=options", "options"),
        ("?page=chat", "chat"),
        ("?page=news", "news"),
    ]

    for route, label in candidate_routes:
        url = f"https://app.godelterminal.com/{route}"
        print(f"\n  ▶ Exploring: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            await asyncio.sleep(2)  # Let JS load
            final_url = page.url
            title = await page.title()
            print(f"     → {final_url[:80]}  [{title[:40]}]")
            await take_screenshot(page, f"route_{label}")
            await snapshot_dom(page, f"route_{label}")
            save_maps()  # Save after each route
        except Exception as e:
            print(f"     ⚠ {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    global capture_enabled

    print("\n" + "═" * 70)
    print("  🔭 GODEL TERMINAL — Interactive API Explorer")
    print(f"  Target: {TARGET_URL}")
    print("  Mode: User-controlled (handles Cloudflare)")
    print("═" * 70)

    async with async_playwright() as pw:
        # ── Launch a VISIBLE browser ─────────────────────────────────────────
        browser = await pw.chromium.launch(
            headless=False,
            slow_mo=100,
            args=["--start-maximized"],
        )

        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            record_har_path=str(OUT_DIR / "godel.har"),
        )

        # ── Wire up network interceptors (but don't capture yet) ─────────────
        context.on("request",   on_request)
        context.on("response",  on_response)
        context.on("websocket", on_websocket)

        page = await context.new_page()

        # ── 1. Navigate to register page ─────────────────────────────────────
        print(f"\n  ▶ Opening registration page…")
        try:
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
        except Exception as e:
            print(f"  ⚠ Initial navigation: {e}")

        # ── 2. Wait for user to handle Cloudflare + registration ─────────────
        if not await wait_for_user():
            print("\n  👋 User quit. Closing browser…")
            await context.close()
            await browser.close()
            return

        # ── 3. Start capturing ────────────────────────────────────────────────
        capture_enabled = True
        print("\n  🚀 API CAPTURE ENABLED! Starting exploration…\n")

        # Take initial snapshot
        await take_screenshot(page, "01_logged_in")
        await snapshot_dom(page, "logged_in_state")

        # ── 4. Explore routes ─────────────────────────────────────────────────
        await explore_routes(page)

        # ── 5. Interactive mode ───────────────────────────────────────────────
        print("\n" + "═" * 70)
        print("  ✅ Initial exploration complete!")
        print(f"  📁 Artifacts in: {OUT_DIR}")
        print("\n  INTERACTIVE MODE:")
        print("  - Navigate anywhere in the browser")
        print("  - All API calls are being captured")
        print("  - Press ENTER in this terminal to take a snapshot")
        print("  - Type 'q' + ENTER to quit")
        print("═" * 70)

        snapshot_num = 1
        while True:
            if not await wait_for_user():
                break
            # User pressed ENTER — take a manual snapshot
            await take_screenshot(page, f"manual_{snapshot_num:02d}")
            await snapshot_dom(page, f"manual_snapshot_{snapshot_num}")
            save_maps()
            snapshot_num += 1
            print(f"  ✅ Snapshot {snapshot_num} saved!")

        # ── 6. Final save and cleanup ─────────────────────────────────────────
        print("\n  👋 Shutting down…")
        save_maps()
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())