"""
tools/Yodel/2-setup/live_api_scanner.py
========================================
Uses CloakBrowser with an authenticated session to:
1. Intercept and log EVERY network request/response with full bodies
2. Download every JS chunk the authenticated app loads
3. Extract all API routes from those chunks
4. Trigger every UI section (command bar, sidebar, panels) to force API calls

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/2-setup/live_api_scanner.py
"""

import re
import json
import hashlib
import asyncio
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from urllib.parse import urlparse

from cloakbrowser import launch_async


# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL  = "https://app.godelterminal.com"
OUT_DIR   = Path(__file__).parent
JS_DIR    = OUT_DIR / "js_bundles"
ROUTES    = OUT_DIR / "extracted_routes"
SESSION   = Path(__file__).parent.parent / "1-browser" / "captures" / "session_state.json"

JS_DIR.mkdir(exist_ok=True)
ROUTES.mkdir(exist_ok=True)

def ts(): return datetime.now().strftime("%H:%M:%S")
def log(msg): print(f"  [{ts()}] {msg}")


# ── Route extraction ───────────────────────────────────────────────────────────
def extract_routes(content: str) -> list[str]:
    routes = set()
    patterns = [
        r'["`]((?:https?://(?:api|app|wojak)\.godelterminal\.com)?/(?:api|v1|v2)/[^"`\s\\]{3,150})["`]',
        r'["`](/(?:api|v1|v2)/[^"`\s\\]{3,100})["`]',
        r'fetch\s*\(\s*["`]([^"`]+)["`]',
        r'\.(?:get|post|put|patch|delete)\s*\(\s*["`]([^"`\s]{5,120})["`]',
        r'(?:url|path|endpoint)\s*:\s*["`]([^"`\s]{5,120})["`]',
        r'`(/(?:api|v1|v2)/[^`$\s]{3,100})`',
    ]
    for p in patterns:
        for m in re.finditer(p, content):
            r = m.group(1).strip().rstrip('?&').rstrip('/')
            if any(x in r for x in ['/api/', '/v1/', '/v2/']):
                routes.add(r)

    # Filter noise
    skip = ['node_modules','.css','.png','.jpg','.svg','.woff','.ttf','.ico',
            'webpack','localhost','127.0.0.1','undefined','null','__next',
            'javascript:','data:','mailto:','#','cdn-cgi','sentry']
    return sorted(r for r in routes if not any(s in r for s in skip))


async def main():
    print("\n" + "═"*70)
    print("  🔬 GODEL TERMINAL — Live Authenticated API Scanner")
    print(f"  Base: {BASE_URL}")
    print("═"*70)

    api_calls    = []        # ALL network calls with full request+response
    js_content   = {}        # url → content
    all_routes   = defaultdict(set)
    captured_auth_headers = {}

    # ── Launch CloakBrowser ────────────────────────────────────────────────
    log("Launching CloakBrowser…")
    browser = await launch_async(
        headless=False,
        humanize=True,
        args=["--fingerprint=42069", "--start-maximized"]
    )

    # Create context — try to load saved session
    ctx_opts = {
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone_id": "America/New_York",
    }
    if SESSION.exists():
        ctx_opts["storage_state"] = str(SESSION)
        log(f"📂 Loaded saved session from {SESSION}")

    context = await browser.new_context(**ctx_opts)
    page    = await context.new_page()

    # ── Network interception: capture EVERYTHING ───────────────────────────
    async def handle_route(route):
        req  = route.request
        url  = req.url
        meth = req.method

        # ── Capture auth tokens for later use ─────────────────────────────
        hdrs = dict(req.headers)
        if 'authorization' in hdrs:
            captured_auth_headers['Authorization'] = hdrs['authorization']
        if 'x-auth-token' in hdrs:
            captured_auth_headers['X-Auth-Token'] = hdrs['x-auth-token']

        # ── Download JS bundles on the fly ─────────────────────────────────
        ct = ''
        is_js = (
            'javascript' in url or
            url.endswith('.js') or
            '/_next/static/' in url or
            '/chunks/' in url
        )

        # Continue and intercept response
        resp = await route.fetch()
        resp_headers = dict(resp.headers)
        ct = resp_headers.get('content-type', '')
        status = resp.status
        body_bytes = await resp.body()

        # ── Save JS bundle ─────────────────────────────────────────────────
        if status == 200 and ('javascript' in ct or is_js) and 'godelterminal' in url:
            try:
                text = body_bytes.decode('utf-8', errors='ignore')
                fname = hashlib.md5(url.encode()).hexdigest()[:8] + "_" + Path(url.split('?')[0]).name
                if not fname.endswith('.js'): fname += '.js'
                dst = JS_DIR / fname
                if not dst.exists():
                    dst.write_text(text, encoding='utf-8')
                    log(f"  📦 JS bundle saved: {fname} ({len(text):,} bytes)")
                    routes = extract_routes(text)
                    for r in routes:
                        all_routes[r].add(fname)
                    if routes:
                        log(f"     → {len(routes)} routes found in {fname}")
            except:
                pass

        # ── Log API calls ──────────────────────────────────────────────────
        is_api = any(x in url for x in [
            '/api/', '/v1/', '/v2/', '/graphql',
            'api.godelterminal.com',
            'wojak.godelterminal.com',
        ]) and not any(skip in url for skip in [
            'sentry', 'google', 'analytics', 'adroll',
            'facebook', 'twitter', 'cloudflare', 'gtm',
        ])

        if is_api:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "method":    meth,
                "url":       url,
                "status":    status,
                "req_headers": {k: v for k, v in hdrs.items()
                                if k.lower() not in ('cookie',)},
            }

            # Request body
            try:
                pd = req.post_data
                if pd:
                    try:    entry["req_body"] = json.loads(pd)
                    except: entry["req_body"] = pd
            except: pass

            # Response body
            try:
                if 'json' in ct:
                    entry["resp_body"] = json.loads(body_bytes)
                elif 'text' in ct:
                    entry["resp_body"] = body_bytes.decode('utf-8', errors='ignore')[:2000]
            except: pass

            api_calls.append(entry)
            icon = "✅" if status < 400 else "❌"
            log(f"  {icon} {status} {meth:6s} {url[:80]}")
            if "resp_body" in entry:
                preview = json.dumps(entry["resp_body"])[:100] if isinstance(entry.get("resp_body"), (dict, list)) else str(entry.get("resp_body",""))[:100]
                log(f"         body: {preview}")

            # Also add URL to routes
            all_routes[url.replace('https://api.godelterminal.com','').replace('https://app.godelterminal.com','')].add("live_capture")

        await route.fulfill(response=resp, body=body_bytes)

    await page.route("**/*", handle_route)

    # ── Navigate to main app ───────────────────────────────────────────────
    log(f"Navigating to {BASE_URL}…")
    try:
        await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    except Exception as e:
        log(f"  nav: {e}")
    await asyncio.sleep(3)

    # ── Save session ───────────────────────────────────────────────────────
    await context.storage_state(path=str(SESSION))
    log(f"💾 Session saved")

    # ── Save auth headers for direct API calls later ───────────────────────
    if captured_auth_headers:
        auth_file = OUT_DIR / "auth_headers.json"
        auth_file.write_text(json.dumps(captured_auth_headers, indent=2))
        log(f"🔑 Auth headers saved → {auth_file.name}")
        log(f"   Headers: {list(captured_auth_headers.keys())}")

    def save_all():
        """Persist everything to disk."""
        # API calls log
        calls_file = ROUTES / f"live_api_calls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        calls_file.write_text(json.dumps(api_calls, indent=2, default=str))

        # Routes map
        godel = {r: sorted(s) for r, s in all_routes.items()
                 if 'godelterminal' in r or r.startswith('/api/') or r.startswith('/v1/')}
        
        by_cat = defaultdict(list)
        for r in sorted(godel.keys()):
            clean = r.replace('https://api.godelterminal.com','').replace('https://app.godelterminal.com','')
            parts = [p for p in clean.split('/') if p]
            idx = 0
            while idx < len(parts) and parts[idx] in ('api','v1','v2'):
                idx += 1
            cat = parts[idx] if idx < len(parts) else 'misc'
            by_cat[cat].append(clean)

        report = {
            "timestamp": datetime.now().isoformat(),
            "total_api_calls": len(api_calls),
            "unique_endpoints": len(godel),
            "auth_headers_captured": list(captured_auth_headers.keys()),
            "by_category": {cat: sorted(set(routes)) for cat, routes in sorted(by_cat.items())},
            "all_endpoints": sorted(set(
                r.replace('https://api.godelterminal.com','').replace('https://app.godelterminal.com','')
                for r in godel.keys()
            )),
        }

        map_file = ROUTES / "live_api_map.json"
        map_file.write_text(json.dumps(report, indent=2))

        flat_file = ROUTES / "live_routes.txt"
        flat_file.write_text('\n'.join(report["all_endpoints"]))

        log(f"\n💾 API calls ({len(api_calls)}) → {calls_file.name}")
        log(f"💾 Route map → live_api_map.json ({len(godel)} endpoints)")
        log(f"💾 Flat list → live_routes.txt")

        # Print summary
        print("\n" + "═"*70)
        print(f"  📊 CURRENT SUMMARY — {len(godel)} endpoints")
        print("═"*70)
        for cat, routes in sorted(by_cat.items()):
            print(f"\n  [{cat.upper()}]")
            for r in sorted(set(routes)):
                print(f"    {r}")

    # ── Interactive: keep alive, save every 30s ────────────────────────────
    print("\n" + "─"*70)
    print("  🌐 BROWSER IS LIVE — Explore the app!")
    print("  • Click every section, panel, page")
    print("  • Use the command bar")
    print("  • Open charts, news, options, portfolio")
    print("  • Everything is captured in real time")
    print("  • Ctrl+C to stop and save final report")
    print("─"*70)

    try:
        tick = 0
        while True:
            await asyncio.sleep(30)
            tick += 1
            log(f"⏱ Tick {tick} — {len(api_calls)} calls captured, {len(all_routes)} routes")
            save_all()
    except KeyboardInterrupt:
        log("Shutting down…")

    save_all()
    await context.close()
    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
