"""
tools/Yodel/1-browser/stealth_launch.py
========================================
Stealth browser launcher that bypasses Cloudflare and anti-bot detection.

Key techniques:
- Removes all automation indicators
- Uses realistic browser fingerprints
- Randomizes timings and behaviors
- Overrides navigator properties
- Uses real user data dir

Run:
    cd /home/rincon/BrickellQuant
    .venv/bin/python tools/Yodel/1-browser/stealth_launch.py
"""

import json
import sys
import time
import random
import asyncio
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from playwright.async_api import async_playwright, Page, Browser, BrowserContext


# ── Config ────────────────────────────────────────────────────────────────────
TARGET_URL   = "https://app.godelterminal.com/?page=register"
OUT_DIR      = Path(__file__).parent
SCREENSHOTS  = OUT_DIR / "screenshots"
API_MAP_FILE = OUT_DIR / "api_map.json"
DOM_MAP_FILE = OUT_DIR / "dom_map.json"

SCREENSHOTS.mkdir(exist_ok=True)

# ── State ─────────────────────────────────────────────────────────────────────
api_calls: list[dict] = []
capture_enabled = False


# ── Stealth patches ───────────────────────────────────────────────────────────

STEALTH_JS = """
// Remove webdriver property
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Mock plugins to look like a real browser
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        return [
            {
                0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format", enabledPlugin: Plugin},
                description: "Portable Document Format",
                filename: "internal-pdf-viewer",
                length: 1,
                name: "Chrome PDF Plugin"
            },
            {
                0: {type: "application/pdf", suffixes: "", description: "", enabledPlugin: Plugin},
                description: "",
                filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
                length: 1,
                name: "Chrome PDF Viewer"
            }
        ];
    }
});

// Languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

// Permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Chrome runtime
window.chrome = {
    runtime: {
        PlatformOs: {
            MAC: 'mac',
            WIN: 'win',
            ANDROID: 'android',
            CROS: 'cros',
            LINUX: 'linux',
            OPENBSD: 'openbsd',
        },
        PlatformArch: {
            ARM: 'arm',
            X86_32: 'x86-32',
            X86_64: 'x86-64',
        },
        PlatformNaclArch: {
            ARM: 'arm',
            X86_32: 'x86-32',
            X86_64: 'x86-64',
        },
        RequestUpdateCheckStatus: {
            THROTTLED: 'throttled',
            NO_UPDATE: 'no_update',
            UPDATE_AVAILABLE: 'update_available',
        },
        OnInstalledReason: {
            INSTALL: 'install',
            UPDATE: 'update',
            CHROME_UPDATE: 'chrome_update',
            SHARED_MODULE_UPDATE: 'shared_module_update',
        },
        OnRestartRequiredReason: {
            APP_UPDATE: 'app_update',
            OS_UPDATE: 'os_update',
            PERIODIC: 'periodic',
        },
    },
    app: {}
};

// Fix Notification API
const oldNotification = window.Notification;
window.Notification = function(title, options) {
    return new oldNotification(title, options);
};
window.Notification.permission = 'default';
window.Notification.requestPermission = () => Promise.resolve('default');

// Override toString methods to hide modifications
const overrides = [
    window.navigator.permissions.query,
    window.Notification,
    window.Notification.requestPermission
];
overrides.forEach((obj) => {
    if (obj) {
        obj.toString = function() {
            return 'function ' + (obj.name || '') + '() { [native code] }';
        };
    }
});
"""


async def random_delay(min_ms=100, max_ms=300):
    """Human-like random delay."""
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


async def human_type(page: Page, selector: str, text: str):
    """Type like a human with random delays between keystrokes."""
    await page.click(selector)
    for char in text:
        await page.type(selector, char)
        await random_delay(50, 150)


async def setup_stealth_browser():
    """Launch browser with maximum stealth settings."""
    playwright = await async_playwright().start()
    
    # Use real Chrome paths if available
    chrome_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/opt/google/chrome/google-chrome",
    ]
    
    executable_path = None
    for path in chrome_paths:
        if Path(path).exists():
            executable_path = path
            print(f"  🥷 Using real Chrome: {path}")
            break
    
    # Launch with stealth arguments
    browser = await playwright.chromium.launch(
        headless=False,
        executable_path=executable_path,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--disable-automation',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--start-maximized',
            '--window-size=1920,1080',
            # Remove automation indicators
            '--disable-infobars',
            '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process',
            # Fingerprinting resistance
            '--disable-features=UserAgentClientHint',
            '--disable-features=SecMetadata',
            # Performance
            '--disable-accelerated-2d-canvas',
            '--disable-gpu',
            # Privacy
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
            '--metrics-recording-only',
            '--no-first-run',
            # Additional stealth
            '--disable-plugins-discovery',
            '--disable-popup-blocking',
            '--disable-translate',
            '--disable-extensions',
            '--disable-default-apps',
            '--disable-dev-tools',
            '--no-default-browser-check',
            '--ignore-certificate-errors',
            '--allow-running-insecure-content',
        ],
    )
    
    # Create context with realistic settings
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        locale='en-US',
        timezone_id='America/New_York',
        geolocation={'latitude': 40.7128, 'longitude': -74.0060},
        permissions=['geolocation'],
        color_scheme='light',
        reduced_motion='no-preference',
        device_scale_factor=1,
        is_mobile=False,
        has_touch=False,
        java_script_enabled=True,
        bypass_csp=True,
        ignore_https_errors=True,
        # Realistic browser behavior
        accept_downloads=True,
        extra_http_headers={
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
    )
    
    # Inject stealth JavaScript on every page
    await context.add_init_script(STEALTH_JS)
    
    # Additional navigator overrides
    await context.add_init_script("""
        // Override hardware concurrency to common value
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8
        });
        
        // Override memory to common value
        if (navigator.deviceMemory) {
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8
            });
        }
        
        // Fix permissions API
        if (!window.Notification) {
            window.Notification = {
                permission: 'default',
                requestPermission: () => Promise.resolve('default')
            };
        }
        
        // Add convincing window properties
        window.outerWidth = 1920;
        window.outerHeight = 1080;
        
        // Mock screen properties
        Object.defineProperty(screen, 'width', {get: () => 1920});
        Object.defineProperty(screen, 'height', {get: () => 1080});
        Object.defineProperty(screen, 'availWidth', {get: () => 1920});
        Object.defineProperty(screen, 'availHeight', {get: () => 1040});
        
        // WebGL vendor
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) {
                return 'Intel Inc.';
            }
            if (parameter === 37446) {
                return 'Intel Iris OpenGL Engine';
            }
            return getParameter.apply(this, arguments);
        };
        
        const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) {
                return 'Intel Inc.';
            }
            if (parameter === 37446) {
                return 'Intel Iris OpenGL Engine';
            }
            return getParameter2.apply(this, arguments);
        };
    """)
    
    return browser, context


async def main():
    global capture_enabled
    
    print("\n" + "═" * 70)
    print("  🥷 GODEL TERMINAL — Stealth Mode Explorer")
    print(f"  Target: {TARGET_URL}")
    print("  Mode: Maximum stealth + user interaction")
    print("═" * 70)
    
    browser, context = await setup_stealth_browser()
    
    # Create page with additional stealth
    page = await context.new_page()
    
    # Set realistic mouse position
    await page.mouse.move(random.randint(100, 800), random.randint(100, 600))
    
    print("\n  ▶ Opening registration page (stealth mode)…")
    
    # Navigate with realistic timing
    await random_delay(500, 1500)
    
    try:
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60_000)
    except Exception as e:
        print(f"  ⚠ Navigation: {e}")
    
    # Random mouse movements to appear human
    for _ in range(3):
        await page.mouse.move(
            random.randint(100, 1000),
            random.randint(100, 700),
            steps=random.randint(10, 30)
        )
        await random_delay(200, 500)
    
    print("\n" + "─" * 70)
    print("  ⏸  MANUAL INTERACTION REQUIRED:")
    print("  1. Browser is open in STEALTH MODE")
    print("  2. Complete any Cloudflare challenge")
    print("  3. Register a new account")
    print("  4. Log in when ready")
    print("\n  ⚠️  DO NOT close the browser!")
    print("  ⚠️  Keep this script running!")
    print("\n  When logged in, we'll start capturing the API")
    print("─" * 70)
    
    # Keep browser alive
    try:
        while True:
            await asyncio.sleep(10)
            # Check if we're logged in by looking for certain elements
            try:
                # Check for common logged-in indicators
                dashboard = await page.query_selector('[data-testid*="dashboard"], #dashboard, .dashboard, [href*="dashboard"]')
                portfolio = await page.query_selector('[href*="portfolio"], .portfolio, #portfolio')
                logout = await page.query_selector('[href*="logout"], button:has-text("Logout"), button:has-text("Sign Out")')
                
                if dashboard or portfolio or logout:
                    if not capture_enabled:
                        capture_enabled = True
                        print("\n  🚀 DETECTED LOGIN! Starting API capture…")
                        print(f"  Current URL: {page.url}")
                        
                        # Start logging API calls
                        await start_api_capture(context, page)
            except:
                pass
                
    except KeyboardInterrupt:
        print("\n  👋 Shutting down…")
        await browser.close()


async def start_api_capture(context, page):
    """Start capturing API calls after login detected."""
    print("\n  📡 Monitoring API calls…")
    
    def handle_request(request):
        if not capture_enabled:
            return
        url = request.url
        if any(x in url for x in ['/api/', '/v1/', '/v2/', '.json', 'graphql']):
            print(f"  ➤ {request.method} {url[:100]}")
            api_calls.append({
                'method': request.method,
                'url': url,
                'headers': dict(request.headers),
                'time': datetime.now().isoformat(),
            })
    
    def handle_response(response):
        if not capture_enabled:
            return
        url = response.url
        if any(x in url for x in ['/api/', '/v1/', '/v2/', '.json', 'graphql']):
            status_icon = "✅" if response.status < 400 else "❌"
            print(f"  {status_icon} {response.status} ← {url[:100]}")
            # Update the matching request
            for call in reversed(api_calls):
                if call['url'] == url and 'status' not in call:
                    call['status'] = response.status
                    break
    
    page.on("request", handle_request)
    page.on("response", handle_response)
    
    # Save periodically
    while True:
        await asyncio.sleep(30)
        if api_calls:
            API_MAP_FILE.write_text(json.dumps(api_calls, indent=2))
            print(f"  💾 Saved {len(api_calls)} API calls")


if __name__ == "__main__":
    asyncio.run(main())