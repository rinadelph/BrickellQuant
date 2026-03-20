"""
tools/Yodel/1-browser/manual_stealth.py
========================================
Manual stealth browser - YOU control everything.
Just opens the browser and logs API calls.

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/1-browser/manual_stealth.py
"""

import json
import sys
import asyncio
from datetime import datetime
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright, Page, BrowserContext, Request, Response
from playwright_stealth import Stealth


# Configuration
TARGET_URL = "https://app.godelterminal.com/?page=register"
OUT_DIR = Path(__file__).parent / "captures"
OUT_DIR.mkdir(exist_ok=True)

# Output files
API_LOG = OUT_DIR / f"api_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
HAR_FILE = OUT_DIR / f"network_{datetime.now().strftime('%Y%m%d_%H%M%S')}.har"


class APIMonitor:
    def __init__(self):
        self.requests = []
        self.responses = defaultdict(dict)
        self.api_patterns = [
            '/api/', '/v1/', '/v2/', '/graphql',
            '.json', 'ajax', 'xhr', '/rest/'
        ]
    
    def is_api_call(self, url: str) -> bool:
        """Check if URL looks like an API call."""
        return any(pattern in url.lower() for pattern in self.api_patterns)
    
    def log_request(self, request: Request):
        """Log outgoing request."""
        if not self.is_api_call(request.url):
            return
        
        req_data = {
            'id': len(self.requests),
            'timestamp': datetime.now().isoformat(),
            'method': request.method,
            'url': request.url,
            'headers': dict(request.headers),
        }
        
        # Get post data if available
        try:
            post_data = request.post_data
            if post_data:
                try:
                    req_data['body'] = json.loads(post_data)
                except:
                    req_data['body'] = post_data
        except:
            pass
        
        self.requests.append(req_data)
        print(f"\n→ {request.method} {request.url[:100]}")
    
    def log_response(self, response: Response):
        """Log incoming response."""
        if not self.is_api_call(response.url):
            return
        
        status_emoji = "✅" if response.status < 400 else "❌"
        print(f"← {status_emoji} {response.status} {response.url[:100]}")
        
        # Store response info
        self.responses[response.url] = {
            'status': response.status,
            'headers': dict(response.headers),
            'timestamp': datetime.now().isoformat()
        }
    
    def save(self):
        """Save captured data."""
        data = {
            'capture_time': datetime.now().isoformat(),
            'requests': self.requests,
            'responses': dict(self.responses),
        }
        API_LOG.write_text(json.dumps(data, indent=2))
        print(f"\n💾 Saved {len(self.requests)} API calls to {API_LOG.name}")


async def main():
    print("\n" + "═" * 70)
    print("  🥷 GODEL TERMINAL — Manual Stealth Browser")
    print(f"  Initial URL: {TARGET_URL}")
    print("  Mode: YOU control everything!")
    print("═" * 70)
    
    monitor = APIMonitor()
    
    async with async_playwright() as p:
        # Launch browser with stealth settings
        print("\n⚙️  Launching stealth browser...")
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--start-maximized',
            ]
        )
        
        # Create context with stealth settings
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            record_har_path=str(HAR_FILE),
            record_har_omit_content=False,
        )
        
        # Add stealth JavaScript
        await context.add_init_script("""
            // Override the navigator.webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Mock plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Mock languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            
            // Chrome runtime
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
            };
            
            // Permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            
            // WebGL Vendor
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) {
                    return 'Intel Inc.';
                }
                if (parameter === 37446) {
                    return 'Intel Iris OpenGL Engine';
                }
                return getParameter(parameter);
            };
        """)
        
        # Set up monitoring
        context.on('request', monitor.log_request)
        context.on('response', monitor.log_response)
        
        # Create page
        page = await context.new_page()
        
        # Apply additional stealth
        stealth = Stealth()
        await stealth.apply_stealth_async(page)
        
        print("✅ Stealth patches applied")
        
        # Navigate to initial URL
        print(f"\n🌐 Opening {TARGET_URL}...")
        try:
            await page.goto(TARGET_URL, wait_until='domcontentloaded', timeout=30000)
        except Exception as e:
            print(f"⚠️  Navigation: {e}")
        
        print("\n" + "─" * 70)
        print("  👤 BROWSER IS READY!")
        print("  • Complete any Cloudflare challenge")
        print("  • Register/login as needed")
        print("  • Navigate anywhere you want")
        print("  • All API calls are being logged")
        print("  • Press Ctrl+C when done")
        print("─" * 70)
        
        # Keep running and save periodically
        try:
            while True:
                await asyncio.sleep(30)
                monitor.save()
        except KeyboardInterrupt:
            print("\n👋 Shutting down...")
            monitor.save()
            
            # Save final HAR file info
            print(f"📁 Network HAR saved to: {HAR_FILE.name}")
            print(f"📁 API log saved to: {API_LOG.name}")
            
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())