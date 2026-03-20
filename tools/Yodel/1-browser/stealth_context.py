"""
tools/Yodel/1-browser/stealth_context.py
========================================
Production-ready stealth browser using proper context isolation.
Bypasses Cloudflare and other anti-bot systems.

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/1-browser/stealth_context.py
"""

import json
import sys
import asyncio
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright, Page, BrowserContext
from playwright_stealth import Stealth


# ── Configuration ─────────────────────────────────────────────────────────────
TARGET_URL = "https://app.godelterminal.com/?page=register"
OUT_DIR = Path(__file__).parent
CAPTURES_DIR = OUT_DIR / "captures"
CAPTURES_DIR.mkdir(exist_ok=True)

API_LOG = CAPTURES_DIR / f"api_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
SESSION_FILE = CAPTURES_DIR / "session_state.json"


class StealthBrowser:
    """Manages a stealth browser session with API monitoring."""
    
    def __init__(self):
        self.api_calls: List[Dict] = []
        self.page: Optional[Page] = None
        self.context: Optional[BrowserContext] = None
        self.capture_active = False
        
    async def setup(self):
        """Initialize stealth browser with proper context."""
        self.playwright = await async_playwright().start()
        
        # Browser launch args focusing on stealth
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
            "--disable-features=BlockInsecurePrivateNetworkRequests",
            "--disable-features=ImprovedCookieControls",
            "--flag-switches-begin",
            "--disable-site-isolation-trials",
            "--flag-switches-end",
            "--disable-features=CrossSiteDocumentBlockingIfIsolating",
            "--disable-features=CrossSiteDocumentBlockingAlways",
            "--disable-web-security",
            "--disable-features=IsolateOrigins",
            "--disable-site-isolation-for-policy",
            "--disable-features=site-per-process",
            "--enable-features=NetworkService",
            "--no-sandbox",
            "--start-maximized",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--no-first-run",
            "--no-zygote",
            "--single-process",
            "--disable-gpu"
        ]
        
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=launch_args,
            chromium_sandbox=False,
        )
        
        # Context with realistic configuration
        context_options = {
            "viewport": {"width": 1920, "height": 1080},
            "screen": {"width": 1920, "height": 1080},
            "user_agent": self._get_random_user_agent(),
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "permissions": ["geolocation", "notifications"],
            "geolocation": {"latitude": 40.7128, "longitude": -74.0060},
            "color_scheme": "light",
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
            "bypass_csp": True,
            "java_script_enabled": True,
            "accept_downloads": True,
            "ignore_https_errors": True,
            "offline": False,
            "http_credentials": None,
            "extra_http_headers": {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
        }
        
        # Check for existing session
        if SESSION_FILE.exists():
            try:
                context_options["storage_state"] = str(SESSION_FILE)
                print("  📂 Loading previous session state...")
            except:
                pass
        
        self.context = await self.browser.new_context(**context_options)
        
        # Add initialization script for extra stealth
        await self.context.add_init_script("""
            // Timezone spoofing
            Object.defineProperty(Intl.DateTimeFormat.prototype, 'resolvedOptions', {
                value: function() {
                    return {
                        calendar: "gregory",
                        day: "numeric", 
                        locale: "en-US",
                        month: "numeric",
                        numberingSystem: "latn",
                        timeZone: "America/New_York",
                        year: "numeric"
                    };
                }
            });
            
            // WebRTC spoofing
            const originalGetUserMedia = navigator.mediaDevices.getUserMedia;
            navigator.mediaDevices.getUserMedia = function(constraints) {
                if (constraints && constraints.audio) {
                    return Promise.reject(new Error('Permission denied'));
                }
                return originalGetUserMedia.apply(this, arguments);
            };
            
            // Battery API spoofing
            if ('getBattery' in navigator) {
                navigator.getBattery = async () => {
                    return {
                        charging: true,
                        chargingTime: 0,
                        dischargingTime: Infinity,
                        level: 0.99,
                        addEventListener: () => {},
                        removeEventListener: () => {},
                    };
                };
            }
            
            // Hardware concurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 8
            });
            
            // Device memory  
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8
            });
            
            // Connection info
            Object.defineProperty(navigator, 'connection', {
                get: () => ({
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false
                })
            });
        """)
        
        # Create page
        self.page = await self.context.new_page()
        
        # Apply stealth to the page
        stealth = Stealth()
        await stealth.apply_stealth_async(self.page)
        
        # Set up network interception
        await self._setup_network_monitoring()
        
        print("  ✅ Stealth browser initialized")
        
    def _get_random_user_agent(self) -> str:
        """Get a random realistic user agent."""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ]
        return random.choice(user_agents)
    
    async def _setup_network_monitoring(self):
        """Set up network request/response monitoring."""
        
        async def handle_route(route):
            request = route.request
            
            # Log API calls when capture is active
            if self.capture_active and self._is_api_call(request.url):
                timestamp = datetime.now().isoformat()
                
                # Log request
                req_data = {
                    "timestamp": timestamp,
                    "type": "request",
                    "method": request.method,
                    "url": request.url,
                    "headers": dict(request.headers),
                }
                
                # Get post data if available
                try:
                    post_data = request.post_data
                    if post_data:
                        try:
                            req_data["body"] = json.loads(post_data)
                        except:
                            req_data["body"] = post_data
                except:
                    pass
                
                self.api_calls.append(req_data)
                print(f"\n  → {request.method} {request.url[:80]}")
            
            # Continue the request
            response = await route.fetch()
            
            # Log response
            if self.capture_active and self._is_api_call(request.url):
                resp_data = {
                    "timestamp": datetime.now().isoformat(),
                    "type": "response",
                    "url": request.url,
                    "status": response.status,
                    "headers": dict(response.headers),
                }
                
                # Try to get response body
                try:
                    body = await response.body()
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type:
                        resp_data["body"] = json.loads(body)
                    elif "text" in content_type:
                        resp_data["body"] = body.decode('utf-8')
                except:
                    pass
                
                self.api_calls.append(resp_data)
                status_emoji = "✅" if response.status < 400 else "❌"
                print(f"  ← {status_emoji} {response.status} {request.url[:80]}")
            
            # Fulfill the route
            await route.fulfill(
                response=response,
                body=await response.body(),
                headers=response.headers,
                status=response.status
            )
        
        # Route all requests
        await self.page.route("**/*", handle_route)
    
    def _is_api_call(self, url: str) -> bool:
        """Check if URL is an API call."""
        api_indicators = [
            "/api/", "/v1/", "/v2/", "/graphql",
            ".json", "ajax", "xhr", "fetch"
        ]
        return any(indicator in url.lower() for indicator in api_indicators)
    
    async def navigate(self, url: str):
        """Navigate to URL with human-like behavior."""
        print(f"\n  🌐 Navigating to: {url}")
        
        # Random pre-navigation delay
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        # Navigate
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Random mouse movements
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, 1700)
                y = random.randint(100, 900)
                await self.page.mouse.move(x, y, steps=random.randint(5, 15))
                await asyncio.sleep(random.uniform(0.2, 0.5))
            
            # Scroll randomly
            await self.page.evaluate(f"window.scrollBy(0, {random.randint(100, 300)})")
            
        except Exception as e:
            print(f"  ⚠️  Navigation issue: {e}")
    
    async def wait_for_manual_action(self):
        """Wait for user to complete manual steps."""
        print("\n" + "─" * 70)
        print("  👤 MANUAL INTERACTION REQUIRED:")
        print("  1. Complete any Cloudflare challenge")
        print("  2. Create an account or log in")
        print("  3. The browser will detect when you're logged in")
        print("─" * 70)
        
        # Check for login status
        logged_in = False
        while not logged_in:
            await asyncio.sleep(2)
            
            # Check for common logged-in indicators
            try:
                current_url = self.page.url
                
                # Check URL patterns
                if any(path in current_url for path in ["dashboard", "home", "app"]) and "login" not in current_url and "register" not in current_url:
                    logged_in = True
                    break
                
                # Check for elements
                selectors = [
                    '[href*="logout"]',
                    'button:has-text("Logout")',
                    'button:has-text("Sign Out")',
                    '[href*="dashboard"]',
                    '[href*="portfolio"]',
                    '.user-menu',
                    '#user-dropdown',
                    '[data-testid="user-menu"]'
                ]
                
                for selector in selectors:
                    element = await self.page.query_selector(selector)
                    if element:
                        logged_in = True
                        break
                        
            except:
                pass
        
        print("\n  ✅ Login detected! Starting API capture...")
        self.capture_active = True
        
        # Save session state
        await self.save_session()
    
    async def save_session(self):
        """Save browser session state."""
        try:
            storage = await self.context.storage_state()
            SESSION_FILE.write_text(json.dumps(storage, indent=2))
            print("  💾 Session state saved")
        except Exception as e:
            print(f"  ⚠️  Could not save session: {e}")
    
    async def save_captures(self):
        """Save captured API calls."""
        if self.api_calls:
            API_LOG.write_text(json.dumps(self.api_calls, indent=2))
            print(f"  💾 Saved {len(self.api_calls)} API calls to {API_LOG.name}")
    
    async def explore_app(self):
        """Explore the application after login."""
        print("\n  🔍 Exploring application routes...")
        
        # Common routes to try
        routes = [
            ("Dashboard", ["dashboard", "home", "overview"]),
            ("Portfolio", ["portfolio", "positions", "holdings"]),
            ("Watchlist", ["watchlist", "favorites", "watch"]),
            ("Screener", ["screener", "screen", "scanner", "filter"]),
            ("News", ["news", "feed", "updates"]),
            ("Research", ["research", "analysis", "reports"]),
            ("Options", ["options", "derivatives"]),
            ("Settings", ["settings", "preferences", "account", "profile"]),
        ]
        
        base_url = self.page.url.split('?')[0].rstrip('/')
        
        for name, paths in routes:
            for path in paths:
                # Try different URL patterns
                urls = [
                    f"{base_url}?page={path}",
                    f"{base_url}/{path}",
                    f"{base_url}#{path}",
                ]
                
                for url in urls:
                    try:
                        print(f"\n  📍 Trying {name}: {url}")
                        await self.page.goto(url, wait_until="networkidle", timeout=10000)
                        await asyncio.sleep(2)
                        
                        # Check if we actually navigated somewhere new
                        if self.page.url != base_url:
                            print(f"  ✅ Found route: {self.page.url}")
                            await self.save_captures()
                            break
                    except Exception as e:
                        print(f"  ⏭  Skipping: {e}")
                        continue
                else:
                    continue
                break
    
    async def run_interactive(self):
        """Run in interactive mode."""
        print("\n  🎮 INTERACTIVE MODE")
        print("  - Navigate anywhere in the browser")
        print("  - All API calls are being captured")
        print("  - Press Ctrl+C to exit")
        print("─" * 70)
        
        try:
            while True:
                await asyncio.sleep(10)
                await self.save_captures()
        except KeyboardInterrupt:
            print("\n  👋 Shutting down...")
            await self.save_captures()
            await self.save_session()
    
    async def cleanup(self):
        """Clean up resources."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


async def main():
    print("\n" + "═" * 70)
    print("  🥷 GODEL TERMINAL — Stealth Context Browser")
    print(f"  Target: {TARGET_URL}")
    print("═" * 70)
    
    browser = StealthBrowser()
    
    try:
        # Initialize
        await browser.setup()
        
        # Navigate to target
        await browser.navigate(TARGET_URL)
        
        # Wait for manual login
        await browser.wait_for_manual_action()
        
        # Explore the app
        await browser.explore_app()
        
        # Run interactive mode
        await browser.run_interactive()
        
    finally:
        await browser.cleanup()


if __name__ == "__main__":
    asyncio.run(main())