"""
tools/Yodel/2-setup/extract_js_bundles.py
==========================================
Step 1: Download all JS bundles from the app and extract every API route,
endpoint, method, and payload shape from the source code.

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/2-setup/extract_js_bundles.py
"""

import re
import json
import time
import hashlib
import asyncio
from pathlib import Path
from urllib.parse import urljoin, urlparse
from datetime import datetime
from collections import defaultdict

from playwright.sync_api import sync_playwright


# ── Config ─────────────────────────────────────────────────────────────────────
BASE_URL   = "https://app.godelterminal.com"
OUT_DIR    = Path(__file__).parent
JS_DIR     = OUT_DIR / "js_bundles"
ROUTES_DIR = OUT_DIR / "extracted_routes"

JS_DIR.mkdir(exist_ok=True)
ROUTES_DIR.mkdir(exist_ok=True)

# ── Patterns to find API routes inside JS ──────────────────────────────────────
API_PATTERNS = [
    # fetch("...", {method: "POST"})
    r'fetch\s*\(\s*["`\'](\/[^"`\']+)["`\']',
    # axios.get("/api/...")
    r'axios\s*\.\s*(?:get|post|put|delete|patch)\s*\(\s*["`\'](\/[^"`\']+)["`\']',
    # "/api/something"
    r'["`\'](\/api\/[^"`\'\s,)}{]+)["`\']',
    # "/v1/something"
    r'["`\'](\/v1\/[^"`\'\s,)}{]+)["`\']',
    # "/v2/something"
    r'["`\'](\/v2\/[^"`\'\s,)}{]+)["`\']',
    # template literals: `/api/${ticker}/data`
    r'`(\/api\/[^`\$\s]+)',
    r'`(\/v1\/[^`\$\s]+)',
    # "https://api.godelterminal.com/..."
    r'["`\'](https?://api\.godelterminal\.com/[^"`\'\s)]+)["`\']',
    r'["`\'](https?://app\.godelterminal\.com/api/[^"`\'\s)]+)["`\']',
    r'["`\'](https?://wojak\.godelterminal\.com/[^"`\'\s)]+)["`\']',
    # method: "POST", url: "/api/..."
    r'url\s*:\s*["`\'](\/[^"`\']+)["`\']',
    # endpoint: "/api/..."
    r'endpoint\s*:\s*["`\'](\/[^"`\']+)["`\']',
    # path: "/api/..."
    r'path\s*:\s*["`\'](\/[^"`\']+)["`\']',
    # baseURL patterns
    r'baseURL\s*:\s*["`\'](https?://[^"`\']+)["`\']',
    r'baseUrl\s*:\s*["`\'](https?://[^"`\']+)["`\']',
]

# Patterns for HTTP methods associated with routes
METHOD_CONTEXT_PATTERN = re.compile(
    r'method\s*:\s*["`\'](GET|POST|PUT|DELETE|PATCH|HEAD)["`\'].*?'
    r'(?:url|path|endpoint)\s*:\s*["`\'](\/[^"`\']+)["`\']',
    re.IGNORECASE | re.DOTALL
)

# WebSocket patterns
WS_PATTERNS = [
    r'new\s+WebSocket\s*\(\s*["`\'](wss?://[^"`\']+)["`\']',
    r'["`\'](wss?://[^"`\']+)["`\']',
]

# Payload/body shape patterns
PAYLOAD_PATTERN = re.compile(
    r'(?:body|data|payload)\s*:\s*(?:JSON\.stringify\s*\()?\{([^{}]{0,500})\}',
    re.DOTALL
)

def log(msg):
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")


def extract_routes_from_js(content: str, source_file: str) -> dict:
    """Extract all API routes and patterns from a JS file."""
    results = {
        "source": source_file,
        "routes": [],
        "websockets": [],
        "base_urls": [],
        "method_url_pairs": [],
    }

    seen_routes = set()

    # Extract all route patterns
    for pattern in API_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            route = match.strip().rstrip('/',)
            if route and route not in seen_routes and len(route) > 3:
                # Filter out noise
                if any(skip in route.lower() for skip in [
                    'node_modules', '.css', '.png', '.jpg', '.svg',
                    '.woff', '.ttf', '.ico', 'webpack', 'chunk',
                    'localhost', '127.0.0.1'
                ]):
                    continue
                seen_routes.add(route)
                results["routes"].append(route)

    # Extract WebSocket endpoints
    for pattern in WS_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            if 'godelterminal' in match.lower() or match.startswith('wss://') or match.startswith('ws://'):
                results["websockets"].append(match)

    # Extract base URLs
    base_urls = re.findall(r'(?:baseURL|baseUrl|BASE_URL|API_URL|API_BASE)\s*[=:]\s*["`\'](https?://[^"`\']+)["`\']', content)
    results["base_urls"] = list(set(base_urls))

    # Extract method+URL pairs
    # Look for patterns like: method: "POST", url: "/api/..."
    for m in METHOD_CONTEXT_PATTERN.finditer(content):
        results["method_url_pairs"].append({
            "method": m.group(1).upper(),
            "url": m.group(2),
        })

    return results


def download_and_extract(url: str, session, js_content_map: dict):
    """Download a JS file and extract routes."""
    try:
        log(f"⬇  Downloading {url[:80]}")
        # Use requests via playwright response
        resp = session.get(url)
        if resp.status == 200:
            content = resp.text()
            filename = hashlib.md5(url.encode()).hexdigest()[:8] + "_" + Path(urlparse(url).path).name
            if not filename.endswith('.js'):
                filename += '.js'
            
            # Save the JS file
            js_path = JS_DIR / filename
            js_path.write_text(content, encoding='utf-8')
            log(f"   ✅ Saved {filename} ({len(content):,} bytes)")
            
            js_content_map[url] = {
                "filename": filename,
                "size": len(content),
                "content": content
            }
            return content
    except Exception as e:
        log(f"   ⚠  {e}")
    return None


def main():
    print("\n" + "═" * 70)
    print("  🕵️  GODEL TERMINAL — JS Bundle Extractor")
    print(f"  Target: {BASE_URL}")
    print("═" * 70)

    all_routes       = defaultdict(set)  # route -> set of source files
    all_websockets   = set()
    all_base_urls    = set()
    all_method_pairs = []
    js_files_found   = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        # ── Intercept all JS files loaded by the app ───────────────────────
        js_urls = set()
        js_content_map = {}

        def capture_js(response):
            url = response.url
            ct  = response.headers.get('content-type', '')
            if (
                response.status == 200
                and ('javascript' in ct or url.endswith('.js') or '/chunks/' in url or '/_next/' in url or '/static/' in url)
                and 'godelterminal' not in url.lower()
                and any(x in url for x in ['godelterminal', 'chunk', 'bundle', 'main', 'app', 'vendor', 'index'])
            ):
                js_urls.add(url)

        page.on('response', capture_js)

        # ── Visit the app to trigger JS loading ────────────────────────────
        log("Opening app to collect JS bundle URLs…")
        try:
            page.goto(BASE_URL, wait_until='networkidle', timeout=30000)
        except:
            pass
        time.sleep(3)

        # ── Also collect ALL script src tags ──────────────────────────────
        script_tags = page.evaluate("""() =>
            [...document.querySelectorAll('script[src]')]
            .map(s => s.src)
            .filter(s => s && s.startsWith('http'))
        """)

        for src in script_tags:
            js_urls.add(src)

        log(f"Found {len(js_urls)} JS files to analyze")

        # ── Download each JS file ──────────────────────────────────────────
        for url in sorted(js_urls):
            try:
                log(f"⬇  {url[:90]}")
                resp = page.request.get(url)
                if resp.status == 200:
                    content = resp.text()
                    filename = hashlib.md5(url.encode()).hexdigest()[:8] + "_" + Path(urlparse(url).path).name.split('?')[0]
                    if not filename.endswith('.js'):
                        filename += '.js'
                    
                    js_path = JS_DIR / filename
                    js_path.write_text(content, encoding='utf-8')
                    log(f"   ✅ {filename} ({len(content):,} bytes)")
                    js_files_found.append(str(js_path))
                    js_content_map[url] = content

                    # Extract routes immediately
                    extracted = extract_routes_from_js(content, url)
                    for r in extracted["routes"]:
                        all_routes[r].add(url)
                    all_websockets.update(extracted["websockets"])
                    all_base_urls.update(extracted["base_urls"])
                    all_method_pairs.extend(extracted["method_url_pairs"])

            except Exception as e:
                log(f"   ⚠  {e}")

        browser.close()

    # ── Also scan any JS already on disk ──────────────────────────────────
    log("\nScanning all JS files on disk…")
    for js_file in JS_DIR.glob("*.js"):
        content = js_file.read_text(encoding='utf-8', errors='ignore')
        extracted = extract_routes_from_js(content, js_file.name)
        for r in extracted["routes"]:
            all_routes[r].add(js_file.name)
        all_websockets.update(extracted["websockets"])
        all_base_urls.update(extracted["base_urls"])
        all_method_pairs.extend(extracted["method_url_pairs"])

    # ── Categorize routes ──────────────────────────────────────────────────
    api_routes    = {r for r in all_routes if '/api/' in r or '/v1/' in r or '/v2/' in r}
    ws_routes     = all_websockets
    base_urls     = all_base_urls

    # Group by category
    categories = defaultdict(list)
    for route in sorted(api_routes):
        parts = route.replace('https://api.godelterminal.com', '').replace('https://app.godelterminal.com', '').split('/')
        category = parts[2] if len(parts) > 2 else 'misc'
        categories[category].append(route)

    # ── Print summary ──────────────────────────────────────────────────────
    print("\n" + "═" * 70)
    print(f"  📊 EXTRACTION RESULTS")
    print("═" * 70)
    print(f"\n  JS files downloaded : {len(list(JS_DIR.glob('*.js')))}")
    print(f"  API routes found    : {len(api_routes)}")
    print(f"  WebSocket endpoints : {len(ws_routes)}")
    print(f"  Base URLs found     : {len(base_urls)}")

    print(f"\n  Base URLs:")
    for u in sorted(base_urls):
        print(f"    → {u}")

    print(f"\n  WebSocket endpoints:")
    for w in sorted(ws_routes):
        print(f"    → {w}")

    print(f"\n  API Routes by category:")
    for cat, routes in sorted(categories.items()):
        print(f"\n  [{cat.upper()}] ({len(routes)} routes)")
        for r in sorted(routes):
            clean = r.replace('https://api.godelterminal.com', '').replace('https://app.godelterminal.com', '')
            print(f"    {clean}")

    # ── Save full report ───────────────────────────────────────────────────
    report = {
        "extracted_at": datetime.now().isoformat(),
        "js_files": js_files_found,
        "base_urls": sorted(base_urls),
        "websockets": sorted(ws_routes),
        "api_routes": {
            route: sorted(sources)
            for route, sources in sorted(all_routes.items())
            if '/api/' in route or '/v1/' in route or '/v2/' in route
        },
        "method_url_pairs": all_method_pairs,
        "by_category": {
            cat: sorted(routes)
            for cat, routes in sorted(categories.items())
        }
    }

    out_file = ROUTES_DIR / f"api_routes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_file.write_text(json.dumps(report, indent=2))
    print(f"\n  💾 Full report → {out_file}")

    # ── Also write a clean flat list ──────────────────────────────────────
    flat_file = ROUTES_DIR / "routes_flat.txt"
    with flat_file.open('w') as f:
        for route in sorted(api_routes):
            clean = route.replace('https://api.godelterminal.com', '').replace('https://app.godelterminal.com', '')
            f.write(clean + '\n')
    print(f"  💾 Flat route list → {flat_file}")

    return report


if __name__ == "__main__":
    main()
