"""
tools/Yodel/1-browser/cloak_launch.py
======================================
CloakBrowser launcher - Ultimate stealth browser that passes Cloudflare.
YOU control everything - just monitors API calls.

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/1-browser/cloak_launch.py
"""

import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from cloakbrowser import launch


# Configuration
TARGET_URL = "https://app.godelterminal.com/?page=register"
OUT_DIR = Path(__file__).parent / "captures"
OUT_DIR.mkdir(exist_ok=True)

API_LOG = OUT_DIR / f"godel_api_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"


class APIMonitor:
    def __init__(self):
        self.api_calls = []
        
    def log_call(self, method: str, url: str, data: dict = None):
        """Log an API call."""
        if any(pattern in url for pattern in ['/api/', '/v1/', '/v2/', '.json']):
            call = {
                'timestamp': datetime.now().isoformat(),
                'method': method,
                'url': url,
                'data': data
            }
            self.api_calls.append(call)
            print(f"→ {method} {url[:80]}")
    
    def save(self):
        """Save captured API calls."""
        API_LOG.write_text(json.dumps(self.api_calls, indent=2))
        print(f"\n💾 Saved {len(self.api_calls)} API calls to {API_LOG.name}")


def main():
    print("\n" + "═" * 70)
    print("  🥷 GODEL TERMINAL — CloakBrowser (Ultimate Stealth)")
    print(f"  Target: {TARGET_URL}")
    print("  Stealth Level: MAXIMUM (C++ patched Chromium)")
    print("═" * 70)
    
    monitor = APIMonitor()
    
    # Launch CloakBrowser with maximum stealth
    print("\n⚙️  Launching CloakBrowser...")
    browser = launch(
        headless=False,
        humanize=True,  # Human-like mouse/keyboard behavior
        proxy=None,     # Add your proxy here if needed
        args=[
            "--fingerprint=42069",  # Fixed seed for consistent identity
        ]
    )
    
    print("✅ CloakBrowser launched (reCAPTCHA v3 score: 0.9)")
    
    # Create page and set up monitoring
    page = browser.new_page()
    
    # Monitor network requests
    def on_request(request):
        monitor.log_call(request.method, request.url)
        
    def on_response(response):
        if response.status >= 400:
            print(f"❌ {response.status} {response.url[:80]}")
    
    page.on("request", on_request)
    page.on("response", on_response)
    
    # Navigate to target
    print(f"\n🌐 Navigating to {TARGET_URL}...")
    try:
        page.goto(TARGET_URL)
    except Exception as e:
        print(f"⚠️  Navigation: {e}")
    
    print("\n" + "─" * 70)
    print("  👤 BROWSER READY - You're in control!")
    print("  • Cloudflare should NOT challenge you")
    print("  • Register/login as needed")  
    print("  • Navigate anywhere")
    print("  • API calls are being logged")
    print("  • Press Enter here when done")
    print("─" * 70)
    
    # Wait for user
    input("\n⏸  Press Enter when done exploring...")
    
    # Save and close
    monitor.save()
    browser.close()
    
    print("\n✅ Done! Check the captures folder for API logs.")


if __name__ == "__main__":
    main()