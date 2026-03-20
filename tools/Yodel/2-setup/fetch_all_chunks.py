"""
tools/Yodel/2-setup/fetch_all_chunks.py
========================================
Fetch the Next.js build manifest to get ALL chunks,
then download every single one and do deep API route extraction.

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/2-setup/fetch_all_chunks.py
"""

import re
import json
import requests
import hashlib
from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime
from collections import defaultdict

BASE_URL  = "https://app.godelterminal.com"
JS_DIR    = Path(__file__).parent / "js_bundles"
OUT_DIR   = Path(__file__).parent / "extracted_routes"
JS_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Referer': BASE_URL,
}

def log(msg): print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")

def download(url: str) -> str | None:
    """Download URL, save to disk, return content."""
    filename = hashlib.md5(url.encode()).hexdigest()[:8] + "_" + Path(url.split('?')[0]).name
    if not filename.endswith('.js'): filename += '.js'
    dst = JS_DIR / filename
    if dst.exists():
        return dst.read_text(errors='ignore')
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            dst.write_bytes(r.content)
            log(f"  ✅ {filename} ({len(r.content):,} bytes)")
            return r.text
        else:
            log(f"  ⚠  {r.status_code} {url[:60]}")
    except Exception as e:
        log(f"  ⚠  {e}")
    return None


def extract_all_routes(content: str) -> list[str]:
    """Aggressively extract every API path from minified JS."""
    routes = set()

    # Pattern 1: quoted string with /api/ or /v1/ or /v2/ path
    for m in re.finditer(r'["\`]((?:https?://(?:api|app|wojak)\.godelterminal\.com)?/(?:api|v1|v2)/[^\s"\'`\\,)}{<>]{2,120})["\`]', content):
        r = m.group(1).strip().rstrip('?&')
        if r: routes.add(r)

    # Pattern 2: template literals with dynamic segments
    for m in re.finditer(r'["\`](/(?:api|v1|v2)/[^"\`\s]{2,120})["\`]', content):
        r = m.group(1).strip()
        if r: routes.add(r)

    # Pattern 3: fetch/axios calls
    for m in re.finditer(r'(?:fetch|axios\.(?:get|post|put|delete|patch))\s*\(\s*["\`]([^"\`\s]{5,120})["\`]', content):
        r = m.group(1)
        if '/api/' in r or '/v1/' in r or '/v2/' in r:
            routes.add(r)

    # Pattern 4: url: "/api/..." object keys
    for m in re.finditer(r'(?:url|path|endpoint|route)\s*:\s*["\`]([^"\`\s,)}{]{5,120})["\`]', content):
        r = m.group(1)
        if '/api/' in r or '/v1/' in r or '/v2/' in r:
            routes.add(r)

    # Filter noise
    clean = set()
    for r in routes:
        if any(skip in r for skip in [
            'node_modules', '.css', '.png', '.jpg', '.svg', '.woff', '.ttf', '.ico',
            'webpack', 'localhost', '127.0.0.1', 'undefined', 'null',
            '__nextjs', '#', 'javascript:', 'data:', 'mailto:'
        ]):
            continue
        clean.add(r.rstrip('/'))

    return sorted(clean)


def main():
    print("\n" + "═" * 70)
    print("  📦 GODEL TERMINAL — Full Chunk Downloader + Route Extractor")
    print("═" * 70)

    session = requests.Session()
    session.headers.update(HEADERS)

    # ── Step 1: Get the build manifest (lists ALL chunks) ──────────────────
    log("Fetching _buildManifest.js …")
    manifest_urls = [
        f"{BASE_URL}/_next/static/chunks/pages/_buildManifest.js",
        f"{BASE_URL}/_next/static/aaea2bcf143d3b0dc8132bc4/_buildManifest.js",  # versioned
    ]

    # First get the HTML to extract the actual build ID
    log("Fetching main page HTML to extract build ID…")
    html = session.get(BASE_URL, timeout=15).text
    
    # Extract build ID from Next.js HTML
    build_id_match = re.search(r'"buildId"\s*:\s*"([a-zA-Z0-9_-]+)"', html)
    if not build_id_match:
        # Try __NEXT_DATA__
        next_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.DOTALL)
        if next_data:
            try:
                data = json.loads(next_data.group(1))
                build_id = data.get('buildId', '')
                log(f"  Build ID from __NEXT_DATA__: {build_id}")
                manifest_urls.insert(0, f"{BASE_URL}/_next/static/{build_id}/_buildManifest.js")
                manifest_urls.insert(0, f"{BASE_URL}/_next/static/{build_id}/_ssgManifest.js")
            except:
                pass

    # Extract all script src tags from HTML
    script_srcs = re.findall(r'<script[^>]+src="([^"]+\.js[^"]*)"', html)
    log(f"  Found {len(script_srcs)} script tags in HTML")

    # ── Step 2: Collect ALL chunk URLs ─────────────────────────────────────
    chunk_urls = set()

    # From script tags
    for src in script_srcs:
        if src.startswith('http'):
            chunk_urls.add(src)
        elif src.startswith('/'):
            chunk_urls.add(BASE_URL + src)

    # Try to get the build manifest
    for mu in manifest_urls:
        content = download(mu)
        if content:
            # Extract chunk paths from manifest
            chunks = re.findall(r'"(/[^"]+\.js)"', content)
            for c in chunks:
                chunk_urls.add(BASE_URL + c)

    # Also look for _next/static chunks in the HTML source
    for m in re.finditer(r'"(/[^"]*/_next/static/chunks/[^"]+\.js)"', html):
        chunk_urls.add(BASE_URL + m.group(1))

    log(f"Total chunk URLs to download: {len(chunk_urls)}")

    # ── Step 3: Download every chunk ──────────────────────────────────────
    all_routes = defaultdict(set)
    
    for url in sorted(chunk_urls):
        log(f"⬇  {url[:80]}")
        content = download(url)
        if content:
            routes = extract_all_routes(content)
            for r in routes:
                all_routes[r].add(url.split('/')[-1])

    # ── Step 4: Also mine the already-downloaded bundles ──────────────────
    log("\nMining all bundles on disk…")
    for js_file in sorted(JS_DIR.glob("*.js")):
        content = js_file.read_text(errors='ignore')
        routes = extract_all_routes(content)
        for r in routes:
            all_routes[r].add(js_file.name)

    # ── Step 5: Categorize and print ───────────────────────────────────────
    # Split into godelterminal vs other
    godel_routes = {r: s for r, s in all_routes.items() if 'godelterminal' in r or r.startswith('/api/') or r.startswith('/v1/') or r.startswith('/v2/')}
    
    # Normalize — strip host
    normalized = {}
    for r, sources in godel_routes.items():
        clean = r.replace('https://api.godelterminal.com', '').replace('https://app.godelterminal.com', '')
        normalized[clean] = sources

    # Group by top-level category
    by_cat = defaultdict(list)
    for r in sorted(normalized.keys()):
        parts = [p for p in r.split('/') if p]
        # skip "api", "v1", "v2" prefixes
        idx = 0
        while idx < len(parts) and parts[idx] in ('api', 'v1', 'v2'):
            idx += 1
        cat = parts[idx] if idx < len(parts) else 'misc'
        by_cat[cat].append(r)

    print("\n" + "═" * 70)
    print(f"  📊 RESULTS — {len(normalized)} unique API routes found")
    print("═" * 70)

    for cat, routes in sorted(by_cat.items()):
        print(f"\n  ┌─ [{cat.upper()}] ({len(routes)} endpoints)")
        for r in sorted(routes):
            print(f"  │   {r}")

    # ── Step 6: Save ───────────────────────────────────────────────────────
    report = {
        "extracted_at": datetime.now().isoformat(),
        "total_routes": len(normalized),
        "by_category": {cat: sorted(routes) for cat, routes in sorted(by_cat.items())},
        "all_routes": {r: sorted(s) for r, s in sorted(normalized.items())},
        "raw_all": {r: sorted(s) for r, s in sorted(all_routes.items())},
    }

    out = OUT_DIR / f"full_api_map_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2))
    log(f"\n💾 Full map → {out}")

    flat = OUT_DIR / "all_routes.txt"
    flat.write_text('\n'.join(sorted(normalized.keys())))
    log(f"💾 Flat list → {flat} ({len(normalized)} routes)")

    return report


if __name__ == "__main__":
    main()
