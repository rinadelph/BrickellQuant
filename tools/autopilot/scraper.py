"""
autopilot.scraper — Cloaked HTTP request layer

Strategy (in order of preference):
  1. curl_cffi  — TLS fingerprint impersonation (looks like real Chrome/Safari/Firefox)
  2. subprocess curl — system curl with full TLS stack, randomised flags
  3. httpx — fallback for simple cases

Why this matters for Autopilot:
  - marketplace.joinautopilot.com is on Vercel + Cloudflare
  - The RSC endpoint (RSC: 1 header) is public but could be rate-limited
  - curl_cffi spoofs JA3/JA4 TLS fingerprint → bot detection bypassed
  - Rotating browser targets + realistic headers = stealth

Impersonation targets available in curl_cffi 0.13:
  Chrome: chrome99, chrome100, chrome101, chrome104, chrome107, chrome110,
          chrome116, chrome119, chrome120, chrome123, chrome124, chrome131,
          chrome133a, chrome136, chrome99_android, chrome131_android
  Safari: safari153, safari155, safari170, safari172_ios, safari180,
          safari180_ios, safari184, safari184_ios, safari260, safari260_ios
  Firefox: firefox133, firefox135
  Edge:    edge99, edge101
  Tor:     tor145
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

# ── curl_cffi (primary — TLS fingerprint impersonation) ───────────────────────
try:
    from curl_cffi import requests as cffi_requests
    from curl_cffi.requests import BrowserType
    _CFFI_AVAILABLE = True
except ImportError:
    _CFFI_AVAILABLE = False

# ── httpx (fallback) ──────────────────────────────────────────────────────────
try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "https://marketplace.joinautopilot.com"
GCS_BASE = "https://storage.googleapis.com/iris-main-prod"

# Realistic browser pool — rotate to avoid fingerprinting
_CHROME_TARGETS = [
    "chrome124", "chrome131", "chrome133a", "chrome136",
    "chrome120", "chrome123", "chrome119",
]
_SAFARI_TARGETS = [
    "safari180", "safari184", "safari260",
    "safari170", "safari155",
]
_FIREFOX_TARGETS = [
    "firefox135", "firefox133",
]
_EDGE_TARGETS = [
    "edge101", "edge99",
]
_ALL_TARGETS = _CHROME_TARGETS + _SAFARI_TARGETS + _FIREFOX_TARGETS + _EDGE_TARGETS

# Matching User-Agent strings for each target family
_UA_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_UA_SAFARI = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4.1 Safari/605.1.15"
)
_UA_FIREFOX = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) "
    "Gecko/20100101 Firefox/135.0"
)
_UA_MOBILE_CHROME = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Mobile Safari/537.36"
)
_UA_MOBILE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.0 Mobile/15E148 Safari/604.1"
)

_USER_AGENTS = [
    _UA_CHROME, _UA_CHROME, _UA_CHROME,   # Weight Chrome heavier (most common)
    _UA_SAFARI, _UA_SAFARI,
    _UA_FIREFOX,
    _UA_MOBILE_CHROME,
    _UA_MOBILE_SAFARI,
]

# RSC endpoint headers — trigger Next.js server to return RSC payload JSON.
# IMPORTANT: Do NOT include Next-Router-State-Tree here.
# When that header is present with an empty/generic tree, Next.js returns only
# routing metadata (260 bytes). Omitting it forces a full page RSC render (237KB+).
_RSC_HEADERS_BASE = {
    "Accept":           "text/x-component",
    "RSC":              "1",
    "Accept-Language":  "en-US,en;q=0.9",
    "Accept-Encoding":  "gzip, deflate, br",
    "Cache-Control":    "no-cache",
    "Pragma":           "no-cache",
    "Sec-Fetch-Dest":   "empty",
    "Sec-Fetch-Mode":   "cors",
    "Sec-Fetch-Site":   "same-origin",
    "Connection":       "keep-alive",
}

# Regular browser headers for HTML fetches
_HTML_HEADERS_BASE = {
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control":   "no-cache",
    "Pragma":          "no-cache",
    "Sec-Fetch-Dest":  "document",
    "Sec-Fetch-Mode":  "navigate",
    "Sec-Fetch-Site":  "none",
    "Upgrade-Insecure-Requests": "1",
    "Connection":      "keep-alive",
}


# ── Scraper class ─────────────────────────────────────────────────────────────

class Scraper:
    """
    Cloaked HTTP client for Autopilot Marketplace.

    Tries methods in this order:
      1. curl_cffi with TLS impersonation (stealth mode, bypasses bot detection)
      2. subprocess curl (system curl with realistic flags)
      3. httpx (plain fallback — detected by advanced bot systems)

    Args:
        impersonate:    Force a specific browser target (e.g. "chrome131").
                        If None, rotates randomly from _ALL_TARGETS.
        rotate_targets: If True, pick a new impersonation target each request.
        delay:          Seconds to sleep between requests (default 0.3).
        timeout:        Request timeout in seconds (default 20).
        proxy:          Optional proxy URL, e.g. "http://user:pass@host:port"
                        or "socks5://user:pass@host:port"
        max_retries:    Number of times to retry on failure (default 2).
        prefer_curl:    If True and curl_cffi unavailable, use subprocess curl.
    """

    def __init__(
        self,
        impersonate: Optional[str] = None,
        rotate_targets: bool = True,
        delay: float = 0.3,
        timeout: int = 20,
        proxy: Optional[str] = None,
        max_retries: int = 2,
        prefer_curl: bool = True,
    ):
        self.impersonate     = impersonate
        self.rotate_targets  = rotate_targets
        self.delay           = delay
        self.timeout         = timeout
        self.proxy           = proxy
        self.max_retries     = max_retries
        self.prefer_curl     = prefer_curl
        self._session        = None     # curl_cffi session (reused)
        self._last_request   = 0.0     # timestamp of last request

    # ── Public interface ───────────────────────────────────────────────────────

    def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        rsc: bool = False,
    ) -> Tuple[int, str]:
        """
        Make a GET request.

        Args:
            url:     Full URL to fetch.
            headers: Additional headers to merge in.
            params:  Query string parameters.
            rsc:     If True, add RSC headers for Next.js server component payload.

        Returns:
            (status_code, response_text)
        """
        self._throttle()
        merged = self._build_headers(rsc=rsc, extra=headers)

        if params:
            qs  = urlencode(params)
            url = f"{url}?{qs}" if "?" not in url else f"{url}&{qs}"

        last_err = None
        for attempt in range(self.max_retries + 1):
            try:
                if _CFFI_AVAILABLE:
                    return self._cffi_get(url, merged)
                elif self.prefer_curl and self._curl_available():
                    return self._curl_get(url, merged)
                elif _HTTPX_AVAILABLE:
                    return self._httpx_get(url, merged)
                else:
                    raise RuntimeError("No HTTP backend available. Install curl_cffi: pip install curl-cffi")
            except Exception as exc:
                last_err = exc
                if attempt < self.max_retries:
                    wait = 1.5 ** attempt + random.uniform(0.5, 1.5)
                    time.sleep(wait)

        raise RuntimeError(f"All {self.max_retries + 1} attempts failed for {url}: {last_err}")

    def get_rsc(self, path: str, headers: Optional[Dict] = None) -> Tuple[int, str]:
        """Fetch a Next.js RSC payload for a marketplace path."""
        url = f"{BASE_URL}{path}"
        return self.get(url, headers=headers, rsc=True)

    def get_sitemap(self) -> Tuple[int, str]:
        return self.get(f"{BASE_URL}/sitemap.xml")

    def close(self):
        """Close the underlying curl_cffi session if open."""
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── Internals ──────────────────────────────────────────────────────────────

    def _throttle(self):
        """Enforce minimum delay between requests."""
        if self.delay > 0:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed + random.uniform(0, 0.15))
        self._last_request = time.monotonic()

    def _pick_target(self) -> str:
        """Pick browser impersonation target."""
        if self.impersonate:
            return self.impersonate
        if self.rotate_targets:
            # Weight Chrome higher (60% Chrome, 25% Safari, 10% Firefox, 5% Edge)
            return random.choices(
                _ALL_TARGETS,
                weights=[3] * len(_CHROME_TARGETS) + [2] * len(_SAFARI_TARGETS) +
                        [1] * len(_FIREFOX_TARGETS) + [0.5] * len(_EDGE_TARGETS),
                k=1,
            )[0]
        return _CHROME_TARGETS[0]

    def _pick_ua(self, target: str) -> str:
        """Pick a User-Agent string matching the impersonation target."""
        if "android" in target:
            return _UA_MOBILE_CHROME
        if "ios" in target:
            return _UA_MOBILE_SAFARI
        if "safari" in target:
            return _UA_SAFARI
        if "firefox" in target:
            return _UA_FIREFOX
        if "edge" in target:
            return _UA_CHROME.replace("Chrome", "Edge")
        return _UA_CHROME

    def _build_headers(
        self,
        rsc: bool = False,
        extra: Optional[Dict] = None,
        target: Optional[str] = None,
    ) -> Dict[str, str]:
        """Assemble final headers dict."""
        tgt  = target or self._pick_target()
        ua   = self._pick_ua(tgt)
        base = (_RSC_HEADERS_BASE if rsc else _HTML_HEADERS_BASE).copy()
        base["User-Agent"] = ua
        base["Referer"]    = BASE_URL + "/"
        base["Origin"]     = BASE_URL
        if extra:
            base.update(extra)
        return base

    # ── Method 1: curl_cffi ───────────────────────────────────────────────────

    def _ensure_session(self, target: str):
        """Lazily create or replace the curl_cffi session."""
        if self._session is None:
            opts: Dict[str, Any] = {
                "impersonate": target,
                "timeout":     self.timeout,
                "verify":      True,
            }
            if self.proxy:
                opts["proxies"] = {"https": self.proxy, "http": self.proxy}
            self._session = cffi_requests.Session(**opts)
        return self._session

    def _cffi_get(self, url: str, headers: Dict[str, str]) -> Tuple[int, str]:
        """GET via curl_cffi with TLS fingerprint impersonation."""
        target  = self._pick_target()
        session = self._ensure_session(target)

        resp = session.get(
            url,
            headers=headers,
            timeout=self.timeout,
            allow_redirects=True,
        )
        return resp.status_code, resp.text

    # ── Method 2: subprocess curl ─────────────────────────────────────────────

    def _curl_available(self) -> bool:
        try:
            subprocess.run(["curl", "--version"], capture_output=True, check=True, timeout=3)
            return True
        except Exception:
            return False

    def _curl_get(self, url: str, headers: Dict[str, str]) -> Tuple[int, str]:
        """GET via subprocess curl — uses system's native TLS stack."""
        cmd = ["curl", "-s", "-L", "--compressed", "--max-time", str(self.timeout)]

        # Write-out format to get status code on last line
        cmd += ["--write-out", "\n__STATUS__%{http_code}"]

        # Headers
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]

        # Proxy
        if self.proxy:
            cmd += ["--proxy", self.proxy]

        # Randomise TLS ciphers slightly to vary fingerprint
        ciphers = random.choice([
            "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256",
            "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256",
            "",  # Use curl default
        ])
        if ciphers:
            cmd += ["--ciphers", ciphers]

        cmd += [url]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout + 5)
        output = result.stdout

        # Extract status code from the write-out marker
        status = 0
        if "__STATUS__" in output:
            body, status_str = output.rsplit("__STATUS__", 1)
            try:
                status = int(status_str.strip())
            except ValueError:
                status = 0
        else:
            body = output

        return status, body.strip()

    # ── Method 3: httpx fallback ──────────────────────────────────────────────

    def _httpx_get(self, url: str, headers: Dict[str, str]) -> Tuple[int, str]:
        """GET via httpx — plain TLS, no impersonation."""
        kwargs: Dict[str, Any] = {
            "headers":         headers,
            "timeout":         self.timeout,
            "follow_redirects": True,
        }
        if self.proxy:
            kwargs["proxies"] = self.proxy
        with httpx.Client(**kwargs) as client:
            resp = client.get(url, **{k: v for k, v in kwargs.items() if k != "proxies"})
            return resp.status_code, resp.text


# ── RSC payload parser ────────────────────────────────────────────────────────

def parse_rsc_payload(content: str) -> Dict[str, Any]:
    """
    Parse a Next.js RSC (React Server Component) payload into extracted data.

    The RSC format is line-delimited: "id:data\\n"
    Each line starts with a hex ID and a colon, followed by JSON or special tokens.
    Reference strings like "$L1c" point to other record IDs.

    Returns:
        Dict with keys:
            "portfolio"           — portfolio data dict (if on a portfolio page)
            "featured_portfolios" — list of featured portfolio dicts
            "popular_portfolios"  — list of popular portfolio dicts
            "leaderboard"         — dict keyed by span name
            "teams"               — list of team dicts
            "raw_records"         — all parsed RSC records
    """
    result: Dict[str, Any] = {
        "portfolio": None,
        "featured_portfolios": [],
        "popular_portfolios":  [],
        "leaderboard":         {},
        "teams":               [],
        "raw_records":         {},
    }

    # Split RSC stream into records
    records = _split_rsc_records(content)
    result["raw_records"] = records

    # Search each record for data patterns
    for rid, rdata in records.items():
        # ── Individual portfolio page data ─────────────────────────────────
        if '"portfolioKey"' in rdata and '"stats"' in rdata and '"subscriberOverview"' in rdata:
            portfolio = _extract_json_object(rdata, '{"hasReferrer"')
            if portfolio is None:
                portfolio = _extract_json_object(rdata, '{"portfolio"')
            if portfolio is not None:
                inner = portfolio.get("portfolio", portfolio)
                if inner.get("portfolioKey") or inner.get("autoPilotMasterPortfolio"):
                    result["portfolio"] = inner

        # ── Leaderboard data ───────────────────────────────────────────────
        if '"leaderboardPortfolios"' in rdata:
            lb_chunk = _extract_value_for_key(rdata, "leaderboardPortfolios")
            if lb_chunk:
                # Replace RSC prop references that aren't real JSON
                lb_clean = re.sub(
                    r'"(\$(?:L[0-9a-f]+|[0-9]+:[^"]+|undefined))"',
                    '"__ref__"',
                    lb_chunk,
                )
                try:
                    lb_data = json.loads(lb_clean)
                    if isinstance(lb_data, dict):
                        result["leaderboard"] = lb_data
                except json.JSONDecodeError:
                    pass

        # ── Featured portfolios ────────────────────────────────────────────
        if '"featuredPortfolios"' in rdata:
            featured = _extract_value_for_key(rdata, "featuredPortfolios")
            if featured:
                try:
                    result["featured_portfolios"] = json.loads(featured)
                except json.JSONDecodeError:
                    pass

        # ── Popular portfolios (with AUM) ──────────────────────────────────
        if '"popularPortfolios"' in rdata:
            popular = _extract_value_for_key(rdata, "popularPortfolios")
            if popular:
                try:
                    result["popular_portfolios"] = json.loads(popular)
                except json.JSONDecodeError:
                    pass

        # ── Teams list ─────────────────────────────────────────────────────
        if '"teams"' in rdata and '"teamKey"' in rdata and '"portfolioCount"' in rdata:
            teams_chunk = _extract_value_for_key(rdata, "teams")
            if teams_chunk:
                try:
                    result["teams"] = json.loads(teams_chunk)
                except json.JSONDecodeError:
                    pass

    return result


def _split_rsc_records(content: str) -> Dict[str, str]:
    """Split RSC stream into {id: data} dict."""
    records: Dict[str, str] = {}
    lines = content.split("\n")
    for line in lines:
        colon = line.find(":")
        if colon <= 0:
            continue
        rid = line[:colon]
        if not re.match(r'^[0-9a-f]+$', rid):
            continue
        records[rid] = line[colon + 1:]
    return records


def _extract_json_object(text: str, start_key: str) -> Optional[Dict]:
    """Extract the first complete JSON object starting with start_key."""
    pos = text.find(start_key)
    if pos == -1:
        return None
    depth = 0
    end   = pos
    started = False
    for i, c in enumerate(text[pos:]):
        if c == "{":
            depth  += 1
            started = True
        elif c == "}" and started:
            depth -= 1
            if depth == 0:
                end = pos + i + 1
                break
    try:
        return json.loads(text[pos:end])
    except json.JSONDecodeError:
        return None


def _extract_value_for_key(text: str, key: str) -> Optional[str]:
    """
    Extract the JSON value (array or object) for a given key in the RSC text.
    Handles both array and object values.
    """
    needle = f'"{key}":'
    pos    = text.find(needle)
    if pos == -1:
        return None
    pos += len(needle)

    # Skip whitespace
    while pos < len(text) and text[pos] in " \t\n\r":
        pos += 1

    if pos >= len(text):
        return None

    open_char  = text[pos]
    close_char = "]" if open_char == "[" else "}"
    if open_char not in "[{":
        return None

    depth   = 0
    started = False
    for i, c in enumerate(text[pos:]):
        if c == open_char:
            depth   += 1
            started  = True
        elif c in "]}" and started:
            if c == close_char:
                depth -= 1
            if depth == 0:
                return text[pos: pos + i + 1]

    return None


def parse_sitemap(xml_text: str) -> List[Dict[str, Any]]:
    """Parse the sitemap XML and extract portfolio landing page entries."""
    entries = []
    urls    = re.findall(r"<url>(.*?)</url>", xml_text, re.DOTALL)
    for block in urls:
        loc     = re.search(r"<loc>(.*?)</loc>", block)
        lastmod = re.search(r"<lastmod>(.*?)</lastmod>", block)
        if not loc:
            continue
        url = loc.group(1).strip()
        m   = re.match(r".*/landing/(\d+)/(\d+)$", url)
        if not m:
            continue
        entries.append({
            "url":           url,
            "team_key":      int(m.group(1)),
            "portfolio_key": int(m.group(2)),
            "last_mod":      lastmod.group(1).strip() if lastmod else None,
        })
    return entries
