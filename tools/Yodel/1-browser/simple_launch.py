"""
tools/Yodel/1-browser/simple_launch.py
=======================================
Simple Playwright browser launcher with stealth settings.
YOU control everything - just opens and monitors.

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/1-browser/simple_launch.py
"""

import json
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright


# Configuration
TARGET_URL = "https://app.godelterminal.com/?page=register"
OUT_DIR = Path(__file__).parent / "api_captures"
OUT_DIR.mkdir(exist_ok=True)


def main():
    print("\n" + "═" * 70)
    print("  🌐 GODEL TERMINAL — Simple Browser")
    print(f"  Opening: {TARGET_URL}")
    print("═" * 70)
    
    api_calls = []
    
    with sync_playwright() as p:
        # Launch with stealth arguments
        browser = p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-setuid-sandbox',
                '--start-maximized',
                '--window-size=1920,1080',
            ]
        )
        
        # Create context with stealth settings
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            permissions=['geolocation'],
            geolocation={'latitude': 40.7128, 'longitude': -74.0060},
        )
        
        # Add stealth scripts
        context.add_init_script("""
            // Basic stealth patches
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
            };
            
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({
                    query: () => Promise.resolve({ state: 'prompt' })
                })
            });
        """)
        
        page = context.new_page()
        
        # Monitor API calls
        def on_request(request):
            if any(x in request.url for x in ['/api/', '/v1/', '/v2/', '.json']):
                print(f"→ {request.method} {request.url[:80]}")
                api_calls.append({
                    'timestamp': datetime.now().isoformat(),
                    'method': request.method,
                    'url': request.url
                })
        
        page.on("request", on_request)
        
        # Navigate
        print("\n⏳ Opening page...")
        try:
            page.goto(TARGET_URL, timeout=30000)
        except Exception as e:
            print(f"⚠️  {e}")
            print("   (This is normal if Cloudflare is checking)")
        
        print("\n" + "─" * 70)
        print("  ✅ BROWSER IS OPEN!")
        print("  • Handle any Cloudflare challenge")
        print("  • Register/login as needed")
        print("  • Navigate anywhere")
        print("  • All API calls are logged")
        print("  • Press Enter here when done")
        print("─" * 70)
        
        # Wait for user
        input("\n⏸  Press Enter to close browser and save logs...")
        
        # Save API calls
        if api_calls:
            log_file = OUT_DIR / f"api_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            log_file.write_text(json.dumps(api_calls, indent=2))
            print(f"\n💾 Saved {len(api_calls)} API calls to {log_file.name}")
        
        browser.close()
        print("\n✅ Done!")


if __name__ == "__main__":
    main()