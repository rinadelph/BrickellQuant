"""
tools/Yodel/1-browser/ultra_stealth.py
=======================================
Ultimate stealth browser using playwright-stealth library.
This should bypass even the most aggressive anti-bot systems.

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/1-browser/ultra_stealth.py
"""

import json
import sys
import time
import random
import asyncio
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async


# ── Config ────────────────────────────────────────────────────────────────────
TARGET_URL = "https://app.godelterminal.com/?page=register"
OUT_DIR = Path(__file__).parent
API_LOG = OUT_DIR / "api_captures.json"

# ── State ─────────────────────────────────────────────────────────────────────
api_calls = []
logged_in = False


async def main():
    print("\n" + "═" * 70)
    print("  🥷 GODEL TERMINAL — Ultra Stealth Browser")
    print(f"  Target: {TARGET_URL}")
    print("═" * 70)
    
    async with async_playwright() as p:
        # Launch with minimal automation flags
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--start-maximized',
            ]
        )
        
        # Create context
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
        )
        
        page = await context.new_page()
        
        # Apply stealth patches
        await stealth_async(page)
        
        print("  ✅ Stealth patches applied")
        print("\n  ▶ Navigating to registration page…")
        
        await page.goto(TARGET_URL)
        
        print("\n" + "─" * 70)
        print("  👤 MANUAL STEPS:")
        print("  1. Handle any Cloudflare challenge")
        print("  2. Register a new account") 
        print("  3. Log in to the application")
        print("\n  ⚠️  The browser will stay open for exploration")
        print("  ⚠️  API calls will be logged automatically")
        print("─" * 70)
        
        # Set up network monitoring
        async def log_api_request(route, request):
            if '/api/' in request.url or '/v1/' in request.url:
                api_calls.append({
                    'timestamp': datetime.now().isoformat(),
                    'method': request.method,
                    'url': request.url,
                    'headers': dict(request.headers)
                })
                print(f"\n  📡 API: {request.method} {request.url}")
            await route.continue_()
        
        await page.route('**/*', log_api_request)
        
        # Keep alive and save periodically
        try:
            while True:
                await asyncio.sleep(30)
                if api_calls:
                    API_LOG.write_text(json.dumps(api_calls, indent=2))
                    print(f"\n  💾 Saved {len(api_calls)} API calls to {API_LOG.name}")
        except KeyboardInterrupt:
            print("\n  👋 Exiting…")
            if api_calls:
                API_LOG.write_text(json.dumps(api_calls, indent=2))


if __name__ == "__main__":
    asyncio.run(main())