"""
scraper_ps5_v2.py — dlpsgame.com PS5 scraper (fast edition)
============================================================

DROP-IN REPLACEMENT for scraper.py. Output schema is 100% identical —
games_cache.json produced here loads cleanly in any code that reads the old one.

WHERE THE SPEED COMES FROM
──────────────────────────
Old scraper bottlenecks and exactly how each is eliminated:

  1. _wait_for_secure_data() polled JS for up to 6 s per page.
     NEW: .secure-data divs contain data-payload="BASE64" in the *static*
     server-rendered HTML. driver.page_source has it before JS even runs.
     Python decodes base64 in ~1 ms. No JS wait at all.
     Fallback: if JS already cleared the attribute, read innerHTML via JS
     (same as old scraper, but only triggered ~20 % of the time).

  2. fetch_filehosts_from_intermediary() navigated the BROWSER to each
     downloadgameps3.net/archives/XXXXX page, waited CF (up to 40 s),
     then slept SLEEP_INTERMEDIARY=15 s. Sequential, in browser.
     NEW: downloadgameps3.net has no Cloudflare. A requests.Session with
     Chrome headers fetches each page in ~0.5–2 s. All intermediary pages
     for one game are fetched in parallel via ThreadPoolExecutor. Total: ~2–4 s.

  3. Image downloads were sequential via the browser. 5 screenshots × 4 s = 20 s.
     NEW: blogspot/blogger images downloaded in parallel via requests threads.
     wp-content images fetched in a single browser Promise.all() JS call (batch).
     Total: ~3–6 s regardless of count.

  4. SLEEP_BETWEEN_GAMES was 45 s. Code comments say "CF detects via fingerprints
     not session duration". undetected_chromedriver handles fingerprinting.
     NEW: 8 s. Enough for human-like pacing without dominating runtime.

  5. Intermediary fetching was synchronous — browser blocked until all resolved.
     NEW: Pipeline. After parsing page_source, all I/O work is submitted to
     thread pools and runs DURING the 8-s sleep. Collection is near-instant.

  Estimated per-game time:
    Old: ~80–150 s (45 s sleep + sequential intermediaries in browser)
    New: ~15–25 s  (8 s sleep + parallel I/O in background)
    Speedup: ~5–8×
    6 000 games: ~28–42 hours vs ~7–10 days

ARCHITECTURE
────────────
  Browser thread (main):
    ① driver.get(game_url)           ← only dlpsgame.com, CF handled by uc
    ② wait_for_dlpsgame()
    ③ jitter(2, 0.3)                 ← human pause (was 3 s)
    ④ page_src = driver.page_source
    ⑤ decode payloads (Python)       ← instant, replaces JS wait
    ⑥ extract_metadata(soup)         ← pure HTML parse
    ⑦ submit intermediary jobs → _inter_pool  (requests, parallel)
    ⑧ batch-download wp-content images via browser Promise.all()
    ⑨ submit blogspot image jobs → _img_pool  (requests, parallel)
    ⑩ jitter(8, 0.3)                 ← inter + images finish here
    ⑪ collect Future results
    ⑫ save cache

  _inter_pool (daemon threads):
    requests.get(downloadgameps3.net/...) → parse HTML → filehost links

  _img_pool (daemon threads):
    requests.get(blogspot_url) → write PNG/JPG to disk

USAGE
─────
  python scraper_ps5_v2.py

  Uses the same games.json / games_cache.json / screenshots/ as scraper.py.
"""

# ── IMPORTS ───────────────────────────────────────────────────────────────────
import json
import time
import base64
import re
import os
import traceback
import html as _html
from concurrent.futures import ThreadPoolExecutor, Future, as_completed, wait as fw_wait, ALL_COMPLETED
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
import requests
import undetected_chromedriver as uc

# ── CONFIG ────────────────────────────────────────────────────────────────────
INPUT_JSON      = "games_ps5.json"
OUTPUT_JSON     = "games_ps5_cache.json"
SCREENSHOTS_DIR = "screenshots_ps5"

# ── TIMING ────────────────────────────────────────────────────────────────────
# CF detects bots via request fingerprints (TLS, JS behaviour, UA), not timing.
# undetected_chromedriver handles fingerprinting. 8 s is enough human pacing.
SLEEP_BETWEEN_GAMES = 8     # ← was 45 s — the biggest single speedup
SLEEP_AFTER_LOAD    = 2     # brief pause after page loads (was 3 s)
SLEEP_REVEAL        = 2     # after clicking a reveal button (was 5 s)
CF_TIMEOUT          = 40    # max seconds to wait for CF challenge to clear

# ── THREAD POOLS ─────────────────────────────────────────────────────────────
# Both are long-lived module-level pools, created once and shared across all games.
# Intermediary fetches: 8 workers — one game has at most ~6–8 inter links
# Image downloads:      6 workers — cover + up to 5 screenshots in parallel
_INTER_WORKERS = 2      # ← was 8. downloadgameps3.net rate-limits hard; 2 is safe
_IMG_WORKERS   = 6

# ── HTTP CONFIG FOR REQUESTS (intermediary + images) ─────────────────────────
FETCH_TIMEOUT = 25   # seconds, per request via requests library
IMG_TIMEOUT   = 30

import random as _random

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]
SESSION_UA    = _random.choice(_USER_AGENTS)
FETCH_HEADERS = {"User-Agent": SESSION_UA}

# Shared requests.Session for intermediary + image fetches.
# Created once so connections are reused (HTTP keep-alive).
_req_session = requests.Session()
_req_session.headers.update({
    "User-Agent":      SESSION_UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
})

# ── CATEGORY DISCOVERY ────────────────────────────────────────────────────────
# ── INTERMEDIARY RATE LIMITER ─────────────────────────────────────────────────
# downloadgameps3.net enforces strict rate limits (CF Error 1015 = temp IP ban).
# This lock + timestamp ensures at least _INTER_MIN_GAP seconds between any two
# requests to that domain, regardless of how many threads are running.
# Combined with _INTER_WORKERS=2 this keeps us well within their limits.
import threading as _threading
_inter_lock      = _threading.Lock()
_inter_last_req  = [0.0]          # mutable container so threads share it
_INTER_MIN_GAP   = 2.5            # minimum seconds between intermediary fetches
_1015_BACKOFF    = 120            # seconds to sleep when Error 1015 is detected

def _inter_rate_limit():
    """Block until it's safe to make another intermediary request."""
    with _inter_lock:
        gap  = time.time() - _inter_last_req[0]
        wait = _INTER_MIN_GAP - gap
        if wait > 0:
            time.sleep(wait)
        _inter_last_req[0] = time.time()

def _is_1015(text: str) -> bool:
    """Return True if the response body/title contains a CF Error 1015 page."""
    t = text.lower()
    return ("error 1015" in t or
            "rate limited" in t and "cloudflare" in t or
            "you are being rate limited" in t)

CATEGORY_URLS       = ["https://dlpsgame.com/category/ps5/"]
MAX_DISCOVERY_PAGES = 50

# ── DOMAIN LISTS ──────────────────────────────────────────────────────────────
FILEHOST_DOMAINS = [
    "mediafire.com", "pixeldrain.com",
    "mega.nz", "mega.co.nz",
    "1fichier.com", "gofile.io", "uptobox.com",
    "krakenfiles.com", "letsupload.io", "anonfiles.com",
    "mixdrop.co", "rapidgator.net", "zippyshare.com",
    "bayfiles.com", "racaty.net",
    "vikingfile.com", "viki.gg",
    "akirabox.com", "akirabox.to",
    "send.cm", "drive.google.com", "sbfull.com",
    "katfile.com", "filecrypt.cc", "filecrypt.co",
    "usersdrive.com", "dropapk.to", "workupload.com",
    "filerio.in", "terabox.com", "fenixx.org",
    "rootz.so", "rootz.to", "dropbox.com",
    "ranoz.gg", "ranoz.to",
    "transfer.it",
    "1file.io", "1cloudfile.com",
    "buzzheavier.com",
]
INTERMEDIARY_DOMAINS = ["downloadgameps3.net/archives"]
SHORTENER_DOMAINS    = ["shrinkearn.com", "shrinkme.io", "ouo.io", "clk.sh",
                        "fc.lc", "short2win.com", "adfly"]
GUIDE_DOMAINS        = ["downloadgameps3.com"]

_URL_SCAN_RE = re.compile(r'https?://\S+')

# ── BASIC URL HELPERS ─────────────────────────────────────────────────────────
def is_filehost_url(href):   return any(d in href.lower() for d in FILEHOST_DOMAINS)
def is_intermediary_url(h):  return any(d in h.lower()    for d in INTERMEDIARY_DOMAINS)
def is_shortener_url(href):  return any(d in href.lower() for d in SHORTENER_DOMAINS)
def is_guide_url(href):      return any(d in href.lower() for d in GUIDE_DOMAINS)

def decode_shortener_url(href):
    try:
        params = parse_qs(urlparse(href).query)
        for key in ["url", "link", "target", "dest", "redirect"]:
            if key in params:
                b64 = params[key][0]
                b64 += "=" * (4 - len(b64) % 4)
                decoded = base64.b64decode(b64).decode("utf-8", errors="replace")
                if decoded.startswith("http"):
                    return decoded
    except Exception:
        pass
    return None

def resolve_href(href):
    if is_shortener_url(href):
        real = decode_shortener_url(href)
        if real:
            return real
    return href

# ── TIMING ────────────────────────────────────────────────────────────────────
def jitter(base, variance=0.4, minimum=1.0):
    lo = max(minimum, base * (1.0 - variance))
    hi = base * (1.0 + variance)
    time.sleep(_random.uniform(lo, hi))

# ── AD-TEXT SCRUBBING ─────────────────────────────────────────────────────────
_AD_RE = re.compile(
    r"uploaded\s+by\s+dlpsgame\.com[^\n]*"
    r"|for\s+the\s+latest\s+updates[^\n]*"
    r"|please\s+visit\s*:[^\n]*"
    r"|(?:www\.)?dlpsgame\.com"
    r"|have\s+fun\s*!?"
    r"|guide\s+download"         # strip Guide Download text
    r"|tool\s+download"          # strip Tool Download text
    r"|_{2,}"
    r"|-{3,}"
    r"|\*{3,}",
    re.I,
)

_AD_LINES = {
    'uploaded by dlpsgame.com',
    'for the latest updates, please visit',
    'have fun !', 'have fun!', 'have fun',
    'enjoy', 'enjoy!',
    'skip to content', 'link download free',
    'check all link befor download', 'check all links before download',
    'guide download', 'tool download',
}

def _is_ad_line(line: str) -> bool:
    """True if the entire line is ad/promo/nav content — should be dropped."""
    low = line.lower().strip()
    if low in _AD_LINES:
        return True
    # Strip surrounding punctuation/parens for partial-match checks
    stripped = re.sub(r"^[\s(\-–—*_]+|[\s)\-–—*_]+$", "", low)
    if stripped in _AD_LINES:
        return True
    return (
        'dlpsgame.com' in low
        or 'for the latest updates' in low
        or 'please visit' in low
        or low.startswith('uploaded by')
        or low == 'have fun !'
        or re.match(r'^[_\-\*]{2,}$', low) is not None
    )

def _strip_ad_text(text: str):
    if not text:
        return text
    clean_lines = [ln for ln in text.splitlines() if not _is_ad_line(ln)]
    cleaned = _AD_RE.sub("", "\n".join(clean_lines))
    cleaned = re.sub(r"[\s]*\([\s]*\)", "", cleaned)   # remove empty parens left after sub
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned if cleaned else None

# ── BROWSER WAIT HELPERS ──────────────────────────────────────────────────────
def wait_for_cf(driver, timeout=CF_TIMEOUT, require_selector=None):
    """Wait for Cloudflare challenge to clear. Returns True if cleared."""
    for _ in range(timeout):
        t = driver.title.lower()
        if "just a moment" not in t and "cloudflare" not in t:
            if require_selector:
                if driver.find_elements("css selector", require_selector):
                    return True
            else:
                return True
        time.sleep(1)
    print("    [WARN] CF timeout")
    return False

def wait_for_dlpsgame(driver):
    # Specific content selectors only — never generic tags like 'article' or 'div'
    # which also appear on CF challenge pages and cause false-positive early exit.
    return wait_for_cf(
        driver,
        require_selector=(
            ".post-body.entry-content, .entry-content, .post-content, "
            "h1.post-title, h1.entry-title, .post"
        ),
    )

# ── ★ FAST PAYLOAD DECODER ────────────────────────────────────────────────────
def decode_payloads_from_page_source(page_src: str) -> list[str]:
    """
    Extract and decode all .secure-data payloads from the raw static HTML.

    The site JS does:
        div.innerHTML = decodeURIComponent(atob(data-payload))
    which is just base64 UTF-8. We replicate this in Python in ~1 ms,
    eliminating the old _wait_for_secure_data() JS polling loop (up to 6 s).

    The data-payload attribute lives in the server-rendered HTML. It's present
    in driver.page_source unless JS already ran and removed it. Fallback path
    (get_payload_htmls) handles that case.

    Also tries alternative attribute names the site may have switched to:
    data-encode, data-encrypted, data-content, data-encoded, data-b64.
    """
    results = []
    seen    = set()
    # Primary attribute name + common alternatives
    for attr in ("data-payload", "data-encode", "data-encrypted",
                 "data-content", "data-encoded", "data-b64"):
        for m in re.finditer(rf'{re.escape(attr)}="([^"]+)"', page_src):
            encoded = m.group(1)
            if encoded in seen:
                continue
            seen.add(encoded)
            pad = (4 - len(encoded) % 4) % 4
            try:
                decoded = base64.b64decode(encoded + "=" * pad).decode("utf-8", errors="replace")
                if len(decoded) > 10:
                    results.append(decoded)
            except Exception:
                pass
    return results

def get_payload_htmls(driver, page_src: str) -> list[str]:
    """
    Get decoded secure-data payload HTML strings.

    Strategy 1 (fast, ~1 ms): read data-payload (and alternatives) from static
                               page_source, decode Python.
    Strategy 2 (fallback, JS): read innerHTML via JS if data-payload already
                                removed by the client-side decode script.

    Returns a list of decoded HTML strings — same as old extract_intermediary_urls
    received from its JS call, so all downstream parsing is identical.
    """
    payloads = decode_payloads_from_page_source(page_src)
    if payloads:
        print(f"    secure-data: {len(payloads)} payload(s) decoded from static HTML (fast path)")
        return payloads

    # JS already ran and removed data-payload — read the decoded innerHTML instead.
    # Also try alternative class names the site may use on newer posts.
    try:
        htmls = driver.execute_script("""
            var seen = {}, out = [];
            var sels = [
                '.secure-data',
                '.secure_data',
                '.encoded-data',
                '.encrypted-data',
                '[data-payload]',
                '[data-encode]',
                '[data-encrypted]',
                '[data-encoded]',
                '[data-b64]',
            ];
            sels.forEach(function(sel) {
                try {
                    document.querySelectorAll(sel).forEach(function(d) {
                        var h = d.innerHTML || '';
                        if (h && h.length > 10 && !seen[h]) {
                            seen[h] = 1;
                            out.push(h);
                        }
                    });
                } catch(e) {}
            });
            return out;
        """) or []
        valid = [h for h in htmls if h and len(h) > 10]
        if valid:
            print(f"    secure-data: {len(valid)} div(s) read via JS (fallback)")
        else:
            print("    secure-data: 0 payloads found")
        return valid
    except Exception as e:
        print(f"    [WARN] secure-data JS exec: {e}")
        return []

# ── PARAGRAPH CLASSIFIER ──────────────────────────────────────────────────────
def classify_paragraph(text):
    """
    Classify a <p> tag's text into link roles: game / update / dlc / backport.
    Identical to scraper.py — no changes.
    """
    if ":" not in text:
        return []

    header     = text.split(":", 1)[0].strip()
    header_low = header.lower()
    roles      = []

    # Combo: "Game + Update 1.55 + DLC : links"
    if "+" in header and any(kw in header_low for kw in ("game", "update", "backport", "dlc")):
        tokens = [t.strip() for t in header.split("+")]
        for token in tokens:
            tlow = token.lower()
            if tlow.startswith("game"):
                roles.append({"role": "game", "version": "", "label": token})
            elif tlow.startswith("update"):
                vm = re.search(r'update\s+([\d\.]+)(.*)', token, re.I)
                if vm:
                    ver   = vm.group(1)
                    extra = vm.group(2).strip().strip("()")
                    label = f"v{ver}" + (f" {extra}" if extra else "")
                    roles.append({"role": "update", "version": ver, "label": label})
            elif "dlc" in tlow:
                roles.append({"role": "dlc", "version": "DLC", "label": token})
            elif tlow.startswith("backport"):
                vm = re.search(r'backport\s+([\d\.]+xx|[\d\.]+)', token, re.I)
                ver = vm.group(1) if vm else ""
                lbl = re.sub(r'\s*\(@[^)]+\)', '', token).strip()
                roles.append({"role": "backport", "version": ver, "label": lbl})
        if roles:
            return roles

    if header_low.startswith("update"):
        vm = re.search(r'update\s+([\d\.]+)(.*)', header, re.I)
        if vm:
            ver   = vm.group(1)
            extra = vm.group(2).strip().strip("()")
            label = f"v{ver}" + (f" {extra}" if extra else "")
            return [{"role": "update", "version": ver, "label": label}]
        return [{"role": "update", "version": "unknown", "label": header}]

    if "dlc" in header_low:
        vm = re.search(r'dlc\s+(v[\w\.]+)', header, re.I) or \
             re.search(r'dlc\s+([\w\.]+)', header_low)
        ver = ("DLC-" + vm.group(1)) if vm else "DLC"
        return [{"role": "dlc", "version": ver, "label": header}]

    if header_low.startswith("backport"):
        vm = re.search(r'backport\s+([\d\.]+xx|[\d\.]+)', header, re.I)
        ver = vm.group(1) if vm else ""
        lbl = re.sub(r'\s*\(@[^)]+\)', '', header).strip()
        return [{"role": "backport", "version": ver, "label": lbl}]

    if "game" in header_low:
        return [{"role": "game", "version": "", "label": header}]

    return []

# ── ★ RELEASE EXTRACTOR (HTML-ONLY, NO DRIVER) ───────────────────────────────
def extract_releases_from_htmls(payload_htmls: list[str],
                                 page_src: str) -> tuple[list, dict]:
    """
    Parse decoded payload HTML strings → structured releases + global metadata.
    Replaces extract_intermediary_urls(driver) — takes already-decoded HTML.
    Logic is identical; the only change is the input (pre-decoded HTML vs live DOM).
    """
    releases     = []
    seen_urls    = set()
    global_extra = {"ppsa_ids": []}

    _PPSA_RE = re.compile(
        r"(PPSA\d{5})\s*[\u2013\-]\s*(USA|EUR|JPN|JAP|ASIA|UK)")
    _LEGACY_PS_ID_RE = re.compile(
        r"\b(S[CLPI][CEUA][JKSA]-?\d{4,5})\b", re.I)

    def _apply_ppsa(text):
        clean = _html.unescape(re.sub(r'<[^>]+>', '', text))
        for cm in _PPSA_RE.finditer(clean):
            gentry = {"ppsa": cm.group(1), "region": cm.group(2)}
            if gentry not in global_extra["ppsa_ids"]:
                global_extra["ppsa_ids"].append(gentry)
            if "ppsa_id" not in global_extra:
                global_extra["ppsa_id"] = cm.group(1)
                global_extra["region"]  = cm.group(2)

    def _check_legacy(text):
        clean = _html.unescape(re.sub(r'<[^>]+>', '', text))
        ids = list(dict.fromkeys(
            m.group(1).upper() for m in _LEGACY_PS_ID_RE.finditer(clean)))
        if ids and "ppsa_id" not in global_extra:
            global_extra["_no_ppsa"]      = True
            global_extra["_ps_legacy_id"] = ids[0]
            print(f"    [legacy-ps-id] {ids} — marking _no_ppsa=True")

    # Primary PPSA scan: decoded payload HTML (has real text)
    _apply_ppsa(" ".join(payload_htmls))
    # Secondary: raw page source (catches PPSAs outside encrypted divs)
    if not global_extra["ppsa_ids"]:
        _apply_ppsa(page_src)
    # Legacy PS ID check
    if not global_extra.get("ppsa_id"):
        _check_legacy(" ".join(payload_htmls))
        if not global_extra.get("_no_ppsa"):
            _check_legacy(page_src)

    if global_extra["ppsa_ids"]:
        print(f"    [ppsa] {[c['ppsa']+'-'+c['region'] for c in global_extra['ppsa_ids']]}")

    _STRUCTURED_STARTS = (
        "thank", "password", "voice", "audio",
        "subtitle", "screen lang", "screen language", "language", "languages",
        "game size", "base size",
        "developer", "publisher", "player", "players", "format", "disc format",
        "firmware", "required firmware", "min firmware",
        "backport", "game", "update", "dlc",
    )

    for html in payload_htmls:
        if not html or len(html) < 10:
            continue

        sub = BeautifulSoup(html, "html.parser")
        contributor = ""; ppsa = ""; region = ""; password = ""
        release_notes = []

        for p in sub.find_all("p"):
            text = p.get_text(" ", strip=True)
            low  = text.lower()

            if low.startswith("thank") and not contributor:
                contributor = re.sub(r"(?i)^thank\s+", "", text).strip()

            for cm in re.finditer(
                    r"(PPSA\d{5})\s*[\u2013\-]\s*(USA|EUR|JPN|JAP|ASIA|UK)", text):
                if not ppsa:
                    ppsa, region = cm.group(1), cm.group(2)
                gentry = {"ppsa": cm.group(1), "region": cm.group(2)}
                if gentry not in global_extra["ppsa_ids"]:
                    global_extra["ppsa_ids"].append(gentry)
                if "ppsa_id" not in global_extra:
                    global_extra["ppsa_id"] = cm.group(1)
                    global_extra["region"]  = cm.group(2)

            if "password" in low and len(text) < 80 and not password:
                password = re.split(r"password\s*:?\s*", text, flags=re.I, maxsplit=1)[-1].strip()

            # ── Global shared metadata — first seen wins ────────────────────
            # Voice / audio language
            if (low.startswith("voice") or low.startswith("audio")) \
                    and "voice" not in global_extra:
                global_extra["voice"] = text.split(":", 1)[-1].strip()
            # Screen / subtitle languages (payload field)
            if (low.startswith("subtitle") or low.startswith("screen lang")
                    or low.startswith("screen language")) \
                    and "screen_languages" not in global_extra:
                global_extra["screen_languages"] = text.split(":", 1)[-1].strip()
            # Generic language line (audio or display)
            if (low.startswith("language") or low.startswith("languages")) \
                    and len(text) < 200 and "language" not in global_extra:
                global_extra["language"] = text.split(":", 1)[-1].strip()
            # Note / install instruction
            if (low.startswith("note") or low.startswith("notes")) \
                    and "note" not in global_extra and len(text) < 300:
                body = _strip_ad_text(text.split(":", 1)[-1].strip())
                if body and body.lower() not in ("here", ""):
                    global_extra["note"] = body
            # Game / base size  ("Game Size" and "Base Size" both appear on the site)
            if (low.startswith("game size") or low.startswith("base size")) \
                    and "game_size" not in global_extra:
                gm = re.search(r'[\u2013\u2014\-:]+\s*(.+)$', text)
                if gm:
                    global_extra["game_size"] = gm.group(1).strip()
                else:
                    # "Base Size: ~1.04gb compressed, ~8.91gb extracted"
                    after = text.split(":", 1)
                    if len(after) > 1:
                        global_extra["game_size"] = after[1].strip()
            # DLC note (free-standing sentence mentioning DLC)
            if ("dlc" in low or "addon" in low or "add-on" in low) \
                    and ":" not in text and len(text) > 15 \
                    and not text.startswith("Thank") \
                    and "dlc_note" not in global_extra:
                global_extra["dlc_note"] = text.strip()
            # Password
            if "password" in low and len(text) < 80 and "password" not in global_extra:
                pw = re.split(r"password\s*:?\s*", text, flags=re.I, maxsplit=1)[-1].strip()
                if pw:
                    global_extra["password"] = pw
            # Developer / publisher / players / format — not always present
            if low.startswith("developer") and "developer" not in global_extra:
                global_extra["developer"] = text.split(":", 1)[-1].strip()
            if low.startswith("publisher") and "publisher" not in global_extra:
                global_extra["publisher"] = text.split(":", 1)[-1].strip()
            if (low.startswith("player") or low.startswith("players")) \
                    and "players" not in global_extra:
                global_extra["players"] = text.split(":", 1)[-1].strip()
            if (low.startswith("format") or low.startswith("disc format")) \
                    and "format" not in global_extra:
                global_extra["format"] = text.split(":", 1)[-1].strip()
            if (low.startswith("firmware") or low.startswith("required firmware")
                    or low.startswith("min firmware") or low.startswith("minimum firmware")) \
                    and "firmware" not in global_extra:
                global_extra["firmware"] = text.split(":", 1)[-1].strip()

            # Per-release notes — skip any paragraph that is purely guide/tool/ad content
            _is_guide_para = ("guide download" in low or "tool download" in low
                              or "guide-download" in low)
            if len(release_notes) < 5 and not _is_guide_para:
                if (low.startswith("note") or low.startswith("notes")) and len(text) < 400:
                    body = _strip_ad_text(text.split(":", 1)[-1].strip())
                    if body and body.lower() not in ("here", ""):
                        release_notes.append(body)
                elif (
                    15 < len(text) < 400
                    and not any(low.startswith(p) for p in _STRUCTURED_STARTS)
                    and not text.startswith("(")
                    and not _URL_SCAN_RE.search(text)
                    and ":" not in text[:40]
                    and "guide" not in low
                    and not re.match(r'(PPSA|PPSA)\d{5}', text, re.I)
                ):
                    cleaned = _strip_ad_text(text)
                    if cleaned:
                        release_notes.append(cleaned)

        # ── Per-payload links ─────────────────────────────────────────────────
        game_inter    = []
        game_direct   = []
        update_inter  = []
        update_direct = {}

        for a in sub.find_all("a", href=True):
            raw   = a["href"].strip()
            label = a.get_text(strip=True)
            real  = resolve_href(raw)

            if is_guide_url(real) or not real or real in seen_urls:
                continue

            parent_p    = a.find_parent("p")
            parent_text = parent_p.get_text(" ", strip=True) if parent_p else ""
            roles       = classify_paragraph(parent_text)
            if not roles:
                roles = [{"role": "game", "version": "", "label": label}]
            r = roles[0]

            if is_intermediary_url(real):
                seen_urls.add(real)
                if r["role"] == "game":
                    game_inter.append(real)
                    print(f"    ✓ Game inter [{label}]: {real}")
                else:
                    update_inter.append({
                        "version": r["version"],
                        "type":    r["role"],
                        "label":   r["label"],
                        "url":     real,
                    })
                    print(f"    ✓ {r['role'].upper()} {r['label']} inter: {real}")

            elif is_filehost_url(real):
                seen_urls.add(real)
                if r["role"] == "game":
                    game_direct.append({"label": label, "url": real})
                    print(f"    ✓ Game direct [{label}]: {real}")
                else:
                    vk = r["version"]
                    if vk not in update_direct:
                        update_direct[vk] = {
                            "version":   r["version"],
                            "type":      r["role"],
                            "label":     r["label"],
                            "filehosts": [],
                        }
                    update_direct[vk]["filehosts"].append({"label": label, "url": real})
                    print(f"    ✓ {r['role'].upper()} {r['label']} direct [{label}]")

        if game_inter or game_direct or update_inter or update_direct:
            releases.append({
                "ppsa":          ppsa,
                "region":        region,
                "contributor":   contributor,
                "password":      password,
                "note":          "\n".join(release_notes) if release_notes else "",
                "game_inter":    game_inter,
                "game_direct":   game_direct,
                "update_inter":  update_inter,
                "update_direct": list(update_direct.values()),
            })
            n_game = len(game_inter) + len(game_direct)
            n_upd  = len(update_inter) + len(update_direct)
            print(f"    Release: {ppsa or '?'} {region} "
                  f"[{contributor[:30] or 'unknown'}] "
                  f"— {n_game} game, {n_upd} update/dlc")

    if not global_extra.get("ppsa_id") and releases:
        for rel in releases:
            if rel["ppsa"]:
                global_extra["ppsa_id"] = rel["ppsa"]
                global_extra["region"]  = rel["region"]
                break

    print(f"    → {len(releases)} release(s) | "
          f"PPSAs: {[c['ppsa'] for c in global_extra['ppsa_ids']]}")
    return releases, global_extra

# ── ★ INTERMEDIARY FETCHER (requests, not browser) ────────────────────────────
def fetch_filehosts_via_requests(url: str) -> tuple[list, str, bool]:
    """
    Fetch a downloadgameps3.net intermediary page via requests (no browser).

    Returns (links, notes, cf_blocked) where cf_blocked=True means the server
    returned a 403/CF challenge and the caller should retry via the browser.
    On plain network errors or timeouts, cf_blocked=False (no point retrying).
    """
    print(f"      → [req] {url}")
    _inter_rate_limit()   # enforce minimum gap between inter requests
    try:
        hdrs = {
            **FETCH_HEADERS,
            "Referer": "https://dlpsgame.com/",
            "Accept":  "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        r = _req_session.get(url, headers=hdrs, timeout=FETCH_TIMEOUT,
                              allow_redirects=True)
        r.raise_for_status()

        # CF Error 1015 can arrive as a 200 with HTML body
        if _is_1015(r.text):
            print(f"        [1015] rate limit page in response body — backing off {_1015_BACKOFF}s")
            time.sleep(_1015_BACKOFF)
            return [], "", True   # flag for browser retry after backoff

        # If the final URL after redirects is itself a filehost, return it
        if is_filehost_url(r.url) and r.url != url:
            label = urlparse(r.url).netloc.replace("www.", "").split(".")[0].capitalize()
            print(f"        → redirect to filehost: {r.url[:60]}")
            return [{"label": label, "url": r.url}], "", False

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        body   = e.response.text if e.response is not None else ""
        # 403/503 = Cloudflare blocking us
        # 429     = Too Many Requests (rate limit)
        # Any of these with a 1015 body = hard rate-limit ban → long backoff
        if _is_1015(body):
            print(f"        [1015] rate limit ban — backing off {_1015_BACKOFF}s")
            time.sleep(_1015_BACKOFF)
            return [], "", True
        if status in (403, 429, 503):
            print(f"        [CF-block] {status} — will retry via browser")
            return [], "", True
        print(f"        [WARN] requests fetch failed: {e}")
        return [], "", False
    except Exception as e:
        print(f"        [WARN] requests fetch failed: {e}")
        return [], "", False

    soup      = BeautifulSoup(r.text, "html.parser")
    links     = []
    seen      = set()

    # ── Step 1: all <a href> anchors ──────────────────────────────────────────
    for a in soup.find_all("a", href=True):
        href = resolve_href(a["href"].strip())
        if is_guide_url(href) or not href or href in seen:
            continue
        if is_filehost_url(href):
            domain_lbl = urlparse(href).netloc.replace("www.", "").split(".")[0].capitalize()
            links.append({"label": domain_lbl, "url": href})
            seen.add(href)

    # ── Step 2: data-href / data-url / data-link attributes ──────────────────
    for el in soup.find_all(attrs={"data-href": True}):
        href = resolve_href(el["data-href"].strip())
        if is_filehost_url(href) and href not in seen:
            domain_lbl = urlparse(href).netloc.replace("www.", "").split(".")[0].capitalize()
            links.append({"label": domain_lbl, "url": href})
            seen.add(href)

    # ── Step 3: plain-text URLs in page body ─────────────────────────────────
    body_text = r.text
    for raw_url in _URL_SCAN_RE.findall(body_text):
        raw_url = raw_url.rstrip('/.,;)"\'')
        raw_url = resolve_href(raw_url)
        if is_filehost_url(raw_url) and raw_url not in seen:
            lbl = urlparse(raw_url).netloc.replace("www.", "").split(".")[0].capitalize()
            links.append({"label": lbl, "url": raw_url})
            seen.add(raw_url)

    # ── Step 4: redirect target became a filehost ─────────────────────────────
    cur = r.url
    if not links and is_filehost_url(cur) and cur not in seen:
        label = urlparse(cur).netloc.split(".")[-2].capitalize()
        links.append({"label": label, "url": cur})

    # ── Step 5: extract notes text ────────────────────────────────────────────
    text_content = soup.get_text("\n", strip=True)
    note_lines = []
    for ln in text_content.splitlines():
        ln = ln.strip()
        if not ln or _is_ad_line(ln):
            continue
        if _URL_SCAN_RE.search(ln):
            continue
        if re.match(r'^[A-Za-z0-9]{1,12}$', ln):
            continue
        note_lines.append(ln)
    notes = _strip_ad_text("\n".join(note_lines)) or ""

    print(f"        → {len(links)} link(s)")
    return links, notes, False

# ── ★ INTERMEDIARY FETCHER (browser fallback for CF-blocked pages) ────────────
def fetch_filehosts_via_browser(url: str, driver) -> tuple[list, str]:
    """
    Navigate to an intermediary page using the real browser (already has CF
    clearance from the main dlpsgame.com session). Used only when
    fetch_filehosts_via_requests gets a 403/429/503 CF block.

    KEY FIX vs previous version:
    - wait_for_cf return value is checked — if False (timed out) we don't try
      to parse a CF challenge page (which always yields 0 links).
    - Uses a longer CF timeout (90 s) because downloadgameps3.net is a separate
      CF domain the browser hasn't pre-solved; it needs its own clearance time.
    - One retry: if CF clears but we get 0 links, waits 3 s and tries once more
      (handles pages where links are injected slightly after CF clears).
    """
    _CF_BROWSER_TIMEOUT = 90   # longer than main-site timeout — fresh CF domain

    print(f"      → [browser-fallback] {url}")
    _inter_rate_limit()   # same gate as requests path — prevents 1015 on sequential browser retries
    origin_host = urlparse(url).netloc

    try:
        driver.set_page_load_timeout(120)
        try:
            driver.get(url)
        except Exception as _pg_e:
            print(f"        [WARN] page load timed out: {_pg_e}")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
    except Exception as e:
        print(f"        [ERROR loading] {e}")
        return [], ""
    finally:
        try:
            driver.set_page_load_timeout(300)
        except Exception:
            pass

    # Wait for CF to clear — check return value, don't parse a challenge page
    cf_ok = wait_for_cf(driver, timeout=_CF_BROWSER_TIMEOUT)
    if not cf_ok:
        # One more attempt: wait 15 s and check if the title has cleared
        print(f"        [CF] still challenged — waiting 15 s more...")
        time.sleep(15)
        cf_ok = wait_for_cf(driver, timeout=15)
        if not cf_ok:
            print(f"        [WARN] CF did not clear — skipping link extraction")
            return [], ""

    # Check for Error 1015 (rate limit ban) — back off hard and return empty
    try:
        page_text = driver.execute_script(
            "return document.title + ' ' + (document.body ? document.body.innerText : '')"
        ) or ""
        if _is_1015(page_text):
            print(f"        [1015] rate limit ban in browser — backing off {_1015_BACKOFF}s")
            time.sleep(_1015_BACKOFF)
            return [], ""
    except Exception:
        pass

    jitter(SLEEP_REVEAL, 0.3)

    # Try clicking a reveal/download button
    REVEAL_TEXTS     = ["get links", "show links", "click here to download",
                        "download links", "show download", "get download links",
                        "reveal links", "unlock links"]
    REVEAL_BTN_ONLY  = ["download"]
    try:
        clicked = driver.execute_script("""
            var exact = arguments[0], btnOnly = arguments[1];
            function inNav(el) {
                var p = el.parentElement;
                while (p) {
                    var tag = (p.tagName||'').toLowerCase();
                    var cls = (p.className||'').toLowerCase();
                    var id  = (p.id||'').toLowerCase();
                    if (tag==='nav'||tag==='header'||tag==='footer') return true;
                    if (cls.indexOf('nav')!==-1||cls.indexOf('menu')!==-1) return true;
                    if (id.indexOf('nav')!==-1||id.indexOf('menu')!==-1)  return true;
                    p = p.parentElement;
                }
                return false;
            }
            var els = document.querySelectorAll(
                'button, input[type=button], input[type=submit], a[href="#"], a:not([href])');
            for (var i=0; i<els.length; i++) {
                var el = els[i];
                if (inNav(el)) continue;
                var t = (el.innerText||el.value||el.textContent||'').toLowerCase().trim();
                if (!t || t.length>60) continue;
                for (var j=0; j<exact.length; j++) {
                    if (t===exact[j]||t.indexOf(exact[j])!==-1) { el.click(); return t; }
                }
                var tag = el.tagName.toLowerCase();
                if (tag==='button'||tag==='input') {
                    for (var j=0; j<btnOnly.length; j++) {
                        if (t.indexOf(btnOnly[j])!==-1) { el.click(); return t; }
                    }
                }
            }
            return null;
        """, REVEAL_TEXTS, REVEAL_BTN_ONLY)
        if clicked:
            print(f"        Clicked reveal: '{clicked}'")
            jitter(SLEEP_REVEAL, 0.3)
            if origin_host not in driver.current_url:
                driver.back()
                wait_for_cf(driver, timeout=_CF_BROWSER_TIMEOUT)
    except Exception:
        pass

    def _collect_links():
        """Extract all filehost links from the current page DOM."""
        # Direct redirect to a filehost?
        if is_filehost_url(driver.current_url):
            lbl = urlparse(driver.current_url).netloc.split(".")[-2].capitalize()
            return [{"label": lbl, "url": driver.current_url}]

        all_hrefs = driver.execute_script("""
            var results=[], seen={};
            document.querySelectorAll('a[href]').forEach(function(a){
                var h=a.href||'', t=(a.innerText||a.textContent||'').trim();
                if(h&&!seen[h]){seen[h]=1;results.push([h,t]);}
            });
            document.querySelectorAll('[data-href],[data-url],[data-link]').forEach(function(el){
                var h=el.getAttribute('data-href')||el.getAttribute('data-url')||
                      el.getAttribute('data-link')||'';
                var t=(el.innerText||el.textContent||'').trim();
                if(h&&!seen[h]){seen[h]=1;results.push([h,t]);}
            });
            document.querySelectorAll('[onclick]').forEach(function(el){
                var oc=el.getAttribute('onclick')||'';
                var m=oc.match(/https?:[/][/][^'" ]+/g);
                if(m) m.forEach(function(u){
                    if(!seen[u]){seen[u]=1;results.push([u,(el.innerText||'').trim()]);}
                });
            });
            return results;
        """) or []

        found = []
        seen_links = set()
        for href, _label in all_hrefs:
            href = resolve_href(href.strip())
            if not href or href in seen_links or is_guide_url(href):
                continue
            if is_filehost_url(href):
                domain_lbl = urlparse(href).netloc.replace("www.", "").split(".")[0].capitalize()
                found.append({"label": domain_lbl, "url": href})
                seen_links.add(href)

        # Plain-text URL scan as last resort
        try:
            body = driver.execute_script(
                "return document.body ? document.body.innerText : ''") or ""
            for raw_url in _URL_SCAN_RE.findall(body):
                raw_url = raw_url.rstrip('/.,;)"\'')
                raw_url = resolve_href(raw_url)
                if is_filehost_url(raw_url) and raw_url not in seen_links:
                    lbl = urlparse(raw_url).netloc.replace("www.", "").split(".")[0].capitalize()
                    found.append({"label": lbl, "url": raw_url})
                    seen_links.add(raw_url)
        except Exception:
            pass

        return found

    links = _collect_links()

    # Retry once if 0 links — page may need a moment after CF clears
    if not links:
        print(f"        [retry] 0 links — waiting 3 s and trying once more")
        time.sleep(3)
        links = _collect_links()

    # Notes extraction
    notes = ""
    try:
        body_text = driver.execute_script(
            "return document.body ? document.body.innerText : ''") or ""
        note_lines = []
        for ln in body_text.splitlines():
            ln = ln.strip()
            if not ln or _is_ad_line(ln): continue
            if _URL_SCAN_RE.search(ln): continue
            if re.match(r'^[A-Za-z0-9]{1,12}$', ln): continue
            note_lines.append(ln)
        notes = _strip_ad_text("\n".join(note_lines)) or ""
    except Exception:
        pass

    print(f"        → [browser] {len(links)} link(s)")
    return links, notes

# ── METADATA EXTRACTOR ────────────────────────────────────────────────────────
def extract_metadata(soup):
    """
    Extract title, description, cover URL, screenshot URLs, info table, youtube_id.
    Identical to scraper.py — no changes.
    """
    def full_size(url):
        return re.sub(r'/s\d{2,4}(-c)?/', '/s1600/', url)

    def is_blogspot(url):
        return ("blogger.googleusercontent.com" in url
                or "bp.blogspot.com" in url)

    def is_junk(url):
        return any(x in url for x in [
            "emoji", ".svg", "wp-includes", "/icon", "/logo",
            "avatar", "bar-bg2.png", "youtube.png", "wpfront",
            "wpdiscuz", "jetpack", "sharing",
        ])

    # ── Title ─────────────────────────────────────────────────────────────────
    title    = ""
    title_el = soup.select_one(
        "h1.post-title.entry-title, h1.entry-title, h1.post-title, "
        "h1.page-title, h1.title, .post-title h1, header h1, article h1, h1"
    )
    if title_el:
        title = title_el.get_text(strip=True)
    if not title:
        og_t = soup.find("meta", property="og:title")
        if og_t:
            title = og_t.get("content", "").strip()
    if not title:
        pt = soup.find("title")
        if pt:
            title = re.split(r'\s*[-|]\s*Download', pt.get_text(strip=True))[0].strip()

    # ── Description ───────────────────────────────────────────────────────────
    desc    = ""
    content = (soup.select_one(".post-body.entry-content")
               or soup.select_one(".entry-content")
               or soup.select_one(".post-content")
               or soup.select_one("article .content")
               or soup.select_one("article")
               or soup)
    bq      = content.select_one("blockquote")
    if bq:
        desc = _strip_ad_text(bq.get_text("\n", strip=True)) or ""
    if not desc:
        dd = content.select_one(".game_desc .desc, .desc")
        if dd:
            desc = dd.get_text("\n", strip=True)
    if not desc:
        og_d = soup.find("meta", property="og:description")
        if og_d:
            desc = _strip_ad_text(og_d.get("content", "").strip()) or ""
    if not desc:
        for p in content.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 80 and not re.search(r'PPSA\d{5}', t):
                desc = t; break

    # ── Cover + Screenshots ───────────────────────────────────────────────────
    cover = None
    shots = []

    def head_cover():
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"].strip()
        for script in soup.find_all("script", type="application/ld+json"):
            m = re.search(r'"thumbnailUrl"\s*:\s*"([^"]+)"', script.string or "")
            if m:
                return m.group(1).strip()
        return None

    for img in content.find_all("img"):
        src = (img.get("data-lazy-src")
               or img.get("data-src")
               or img.get("data-original")
               or img.get("src")
               or "").strip()
        if not src or is_junk(src):
            continue

        wrap_a     = img.find_parent("a")
        in_sep     = img.find_parent("div", class_="separator") is not None
        in_td      = img.find_parent("td") is not None
        in_rowspan = False
        if in_td:
            td = img.find_parent("td")
            in_rowspan = td.has_attr("rowspan")

        is_wp   = "dlpsgame.com/wp-content" in src
        is_blog = is_blogspot(src)

        if wrap_a and is_wp:
            href = wrap_a.get("href", "")
            if "dlpsgame.com/" in href and "/wp-content/" not in href:
                continue

        if is_blog and in_sep and len(shots) < 5:
            fa = img.find_parent("a", class_="ari-fancybox")
            shot_url = (fa["href"].strip() if fa and fa.get("href") else src)
            shots.append(full_size(shot_url))
            continue

        if cover is None:
            if   is_wp   and in_rowspan:   cover = src
            elif is_wp   and in_td:        cover = src
            elif is_wp   and not in_sep:   cover = src
            elif is_blog and in_rowspan:   cover = full_size(src)
            elif is_blog and in_td:        cover = full_size(src)
            elif is_blog and not in_sep:   cover = full_size(src)

    if not cover:
        hc = head_cover()
        if hc:
            cover = re.sub(r'/s\d{2,4}(-c)?/', '/s1600/', hc)
            print(f"    cover: og:image fallback → {cover[:60]}")

    seen_s = set()
    if cover:
        seen_s.add(re.sub(r'/s\d{2,4}(-c)?/', '/s1600/', cover))
    shots = [s for s in shots if not (s in seen_s or seen_s.add(s))]

    # ── Info table ────────────────────────────────────────────────────────────
    info_table = {}
    for table in content.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                nc = [c for c in cells if not c.find("img")]
                if len(nc) >= 2:
                    key = nc[0].get_text(strip=True).upper()
                    val = nc[1].get_text(strip=True)
                    if key and val and len(key) < 30:
                        info_table[key] = val

    # ── YouTube embed ─────────────────────────────────────────────────────────
    youtube_id = None
    for iframe in content.find_all("iframe"):
        isrc = iframe.get("src", "") or iframe.get("data-lazy-src", "")
        ym = re.search(r"youtube\.com/embed/([\w\-]+)", isrc)
        if ym:
            youtube_id = ym.group(1); break
    if not youtube_id:
        for div in content.find_all("div", class_="rll-youtube-player"):
            did = div.get("data-id", "") or ""
            if did:
                youtube_id = did; break
            ym = re.search(r"youtube\.com/embed/([\w\-]+)",
                           div.get("data-src", "") or "")
            if ym:
                youtube_id = ym.group(1); break

    print(f"    metadata: title={bool(title)} cover={bool(cover)} "
          f"shots={len(shots)} desc={len(desc)}ch")
    return title, desc, cover, shots, info_table, youtube_id

# ── ★ SLUG + IMAGE DOWNLOADER ─────────────────────────────────────────────────
def game_slug(title: str, url: str, ppsa_id: str = "") -> str:
    path = urlparse(url).path.strip("/")
    slug = path.split("/")[-1] if path else ""
    if not slug:
        slug = re.sub(r"[^\w\-]", "-", title.lower())[:60]
    if ppsa_id:
        slug = f"{ppsa_id}-{slug}"
    return slug

def _download_one_via_requests(url: str, local_path: Path,
                                role: str, referer: str) -> bool:
    """Download a single image via requests. Returns True on success."""
    if local_path.exists() and local_path.stat().st_size > 500:
        return True  # already on disk
    try:
        hdrs = {
            **FETCH_HEADERS,
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        r = _req_session.get(url, headers=hdrs, timeout=IMG_TIMEOUT, stream=True)
        r.raise_for_status()
        data = b"".join(r.iter_content(8192))
        if len(data) > 500:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(data)
            return True
        return False
    except Exception:
        return False

def download_screenshots(urls: list, labels: list, slug: str,
                          ppsa_id: str = "", driver=None,
                          page_url: str = "",
                          img_pool: ThreadPoolExecutor = None) -> list:
    """
    Download cover + screenshots.

    FAST VERSION vs old scraper:
    • All blogspot/blogger images downloaded in parallel via img_pool threads.
    • All wp-content images batched into ONE browser Promise.all() JS call,
      so N wp-content images take the same time as 1 (was N × 4 s sequential).
    • On any failure, falls back to requests (same as before).

    Returns the same [{"role", "url", "local"}, ...] structure.
    """
    if not urls:
        return []

    out_dir     = Path(SCREENSHOTS_DIR) / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    ppsa_suffix = f"_{ppsa_id}" if ppsa_id else ""
    results     = {}   # role → result dict

    # Split into groups
    wp_jobs     = []   # (url, role, local_path, relative)
    blog_jobs   = []   # (url, role, local_path, relative)

    for url, role in zip(urls, labels):
        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".jpg"
        local_name = f"{role}{ppsa_suffix}{ext}"
        local_path = out_dir / local_name
        relative   = f"{SCREENSHOTS_DIR}/{slug}/{local_name}"

        if local_path.exists() and local_path.stat().st_size > 500:
            results[role] = {"role": role, "url": url, "local": relative}
            print(f"      {role}: cached on disk")
            continue

        if "dlpsgame.com" in url:
            wp_jobs.append((url, role, local_path, relative))
        else:
            blog_jobs.append((url, role, local_path, relative))

    # ── Blogspot images: parallel via requests threads ────────────────────────
    blog_futures = {}
    for url, role, local_path, relative in blog_jobs:
        referer = urlparse(url).scheme + "://" + urlparse(url).netloc + "/"
        if img_pool:
            fut = img_pool.submit(_download_one_via_requests,
                                  url, local_path, role, referer)
        else:
            # No pool provided — run inline
            ok = _download_one_via_requests(url, local_path, role, referer)
            saved = {"role": role, "url": url, "local": relative if ok else None}
            results[role] = saved
            print(f"      {role}: {'saved (requests)' if ok else 'FAILED'} → {relative}")
            continue
        blog_futures[fut] = (role, url, relative)

    # ── wp-content images: batch browser fetch (Promise.all) ─────────────────
    if wp_jobs and driver:
        target_referer = page_url or "https://dlpsgame.com/"
        # Ensure browser is on dlpsgame.com for the right cookie context
        cur = driver.current_url or ""
        if "dlpsgame.com" not in cur:
            try:
                driver.get(target_referer)
                wait_for_dlpsgame(driver)
                jitter(2, 0.3)
            except Exception:
                pass

        wp_url_list = [j[0] for j in wp_jobs]
        try:
            # Single async JS call downloading all wp-content images in parallel
            b64_results = driver.execute_async_script("""
                var urls    = arguments[0];
                var referer = arguments[1];
                var done    = arguments[2];
                Promise.all(urls.map(function(url) {
                    return fetch(url, {
                        method: 'GET',
                        credentials: 'include',
                        headers: {
                            'Accept':  'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
                            'Referer': referer
                        }
                    })
                    .then(function(r) { return r.ok ? r.blob() : null; })
                    .then(function(blob) {
                        if (!blob) return {ok:false};
                        return new Promise(function(resolve) {
                            var reader = new FileReader();
                            reader.onloadend = function() {
                                resolve({ok: true,
                                         b64: reader.result ? reader.result.split(',')[1] : null});
                            };
                            reader.readAsDataURL(blob);
                        });
                    })
                    .catch(function() { return {ok:false}; });
                })).then(done).catch(function() { done([]); });
            """, wp_url_list, target_referer)

            if not b64_results:
                b64_results = [{"ok": False}] * len(wp_jobs)

            for (url, role, local_path, relative), res in zip(wp_jobs, b64_results):
                saved = False
                if res and res.get("ok") and res.get("b64"):
                    try:
                        data = base64.b64decode(res["b64"])
                        if len(data) > 500:
                            out_dir.mkdir(parents=True, exist_ok=True)
                            with open(local_path, "wb") as f:
                                f.write(data)
                            results[role] = {"role": role, "url": url, "local": relative}
                            print(f"      {role}: saved (browser-batch) → {relative}")
                            saved = True
                    except Exception:
                        pass

                if not saved:
                    # Browser fetch failed — try requests as fallback
                    ok = _download_one_via_requests(url, local_path, role,
                                                    "https://dlpsgame.com/")
                    status = "saved (req-fallback)" if ok else "FAILED"
                    results[role] = {"role": role, "url": url,
                                     "local": relative if ok else None}
                    print(f"      {role}: {status}")

        except Exception as e:
            print(f"      [WARN] batch browser fetch error: {e!r}")
            # Fall back to sequential requests for wp-content
            for url, role, local_path, relative in wp_jobs:
                ok = _download_one_via_requests(url, local_path, role,
                                                "https://dlpsgame.com/")
                results[role] = {"role": role, "url": url,
                                 "local": relative if ok else None}
                print(f"      {role}: {'saved (req-fallback)' if ok else 'FAILED'}")

    elif wp_jobs:
        # No driver — try requests only
        for url, role, local_path, relative in wp_jobs:
            ok = _download_one_via_requests(url, local_path, role,
                                            "https://dlpsgame.com/")
            results[role] = {"role": role, "url": url,
                             "local": relative if ok else None}
            print(f"      {role}: {'saved (requests)' if ok else 'FAILED'}")

    # ── Collect blogspot future results ───────────────────────────────────────
    for fut, (role, url, relative) in blog_futures.items():
        try:
            ok = fut.result(timeout=60)
            results[role] = {"role": role, "url": url,
                             "local": relative if ok else None}
            print(f"      {role}: {'saved (req-parallel)' if ok else 'FAILED'} → {relative}")
        except Exception as e:
            print(f"      {role}: thread error ({e!r})")
            results[role] = {"role": role, "url": url, "local": None}

    # Preserve order: cover first, then screenshots in label order
    ordered = []
    for lbl in labels:
        if lbl in results:
            ordered.append(results.pop(lbl))
    ordered.extend(results.values())   # any remaining (shouldn't happen)
    return ordered

# ── ENTRY COMPLETENESS ────────────────────────────────────────────────────────
def entry_missing(entry):
    """Identical to scraper.py — returns set of missing field names."""
    missing = set()
    if entry.get("error"):
        missing.add("error")

    releases   = entry.get("releases") or []
    has_game   = any(r.get("game") for r in releases)
    has_legacy = bool(entry.get("filehosts"))
    if not has_game and not has_legacy:
        missing.add("releases")

    shots = entry.get("screenshots", [])

    def file_ok(local):
        if not local or local == "dead":
            return False
        p = Path(local)
        if not p.exists():
            p = Path(__file__).parent / local
        return p.exists() and p.stat().st_size > 500

    def img_settled(s):
        return s.get("local") is not None

    cover_e = next((s for s in shots if s.get("role") == "cover"), None)
    if not cover_e or not img_settled(cover_e):
        missing.add("cover")

    screen_shots  = [s for s in shots if s.get("role", "").startswith("screenshot_")]
    _no_shots_flg = entry.get("extra", {}).get("_no_screenshots", False)
    if not screen_shots:
        if not _no_shots_flg:
            missing.add("screenshots")
    else:
        any_file_ok   = any(file_ok(s.get("local")) for s in screen_shots)
        any_unsettled = any(not img_settled(s) for s in screen_shots)
        if any_unsettled and not any_file_ok:
            missing.add("screenshots")

    extra       = entry.get("extra", {})
    has_any_ppsa = (extra.get("ppsa_id") or
                    any(r.get("ppsa") for r in entry.get("releases", [])))
    if not has_any_ppsa and entry.get("releases") and not extra.get("_no_ppsa"):
        missing.add("ppsa_id")

    return missing

# ── ★ RESOLVE INTERMEDIARIES (parallel requests → browser fallback for CF) ────
def _resolve_releases(releases: list,
                      inter_pool: ThreadPoolExecutor,
                      driver,
                      soup: BeautifulSoup) -> list:
    """
    Resolve all intermediary URLs → real filehost links.

    Strategy:
      1. Submit all inter URLs to thread pool (requests, all in parallel).
      2. Collect results. Any URL that got CF-blocked (403/503) is queued.
      3. Browser-fallback CF-blocked URLs sequentially on the main thread —
         the browser already has CF clearance from the main dlpsgame.com visit.

    This keeps the fast path fast (most URLs work via requests) while
    correctly handling pages where CF decides to challenge the plain request.
    """
    for rel in releases:
        # ── Game intermediaries ───────────────────────────────────────────────
        game_inter_futures: dict[Future, str] = {}
        for _i, iurl in enumerate(rel.get("game_inter", [])):
            if _i > 0:
                time.sleep(_random.uniform(0.3, 0.7))  # stagger submissions; real throttle is _inter_rate_limit()
            fut = inter_pool.submit(fetch_filehosts_via_requests, iurl)
            game_inter_futures[fut] = iurl

        # Always retry via browser when requests gets 0 links — inter pages require JS.
        # Notes are saved regardless of whether links are found.
        browser_retry_game = []
        for fut, iurl in game_inter_futures.items():
            try:
                fh, _inotes, cf_blocked = fut.result(timeout=60)
                if _inotes and not rel.get("inter_notes"):
                    rel["inter_notes"] = _inotes
                if fh:
                    rel["game_direct"].extend(fh)
                    print(f"    ✓ game inter → {len(fh)} link(s)")
                else:
                    print(f"    [retry-browser] {'CF-block' if cf_blocked else '0 links (JS-rendered?)'}: {iurl[:60]}")
                    browser_retry_game.append(iurl)
            except Exception as e:
                print(f"    [WARN] intermediary future error: {e}")
                browser_retry_game.append(iurl)

        for iurl in browser_retry_game:
            fh, _inotes = fetch_filehosts_via_browser(iurl, driver)
            if _inotes and not rel.get("inter_notes"):
                rel["inter_notes"] = _inotes
            if fh:
                rel["game_direct"].extend(fh)
                print(f"    ✓ game inter browser → {len(fh)} link(s)")
            else:
                print(f"    [WARN] browser fallback also got 0 links: {iurl[:50]}")
        rel.pop("game_inter", None)

        # ── Update/DLC/backport intermediaries ───────────────────────────────
        new_upd = list(rel.get("update_direct", []))
        upd_inter_futures: dict[Future, dict] = {}
        for _i, ui in enumerate(rel.get("update_inter", [])):
            if _i > 0:
                time.sleep(_random.uniform(0.3, 0.7))
            fut = inter_pool.submit(fetch_filehosts_via_requests, ui["url"])
            upd_inter_futures[fut] = ui

        browser_retry_upd = []
        for fut, ui in upd_inter_futures.items():
            try:
                fh, _inotes, cf_blocked = fut.result(timeout=60)
                if fh:
                    new_upd.append({
                        "version":     ui["version"],
                        "type":        ui["type"],
                        "label":       ui["label"],
                        "filehosts":   fh,
                        "inter_notes": _inotes or "",
                    })
                    print(f"    ✓ {ui['type']} {ui['label']} → {len(fh)} link(s)")
                else:
                    print(f"    [retry-browser] {'CF-block' if cf_blocked else '0 links'}: {ui['label']} {ui['url'][:50]}")
                    ui["_req_notes"] = _inotes or ""
                    browser_retry_upd.append(ui)
            except Exception as e:
                print(f"    [WARN] update inter error: {e}")
                ui["_req_notes"] = ""; browser_retry_upd.append(ui)

        for ui in browser_retry_upd:
            fh, _inotes = fetch_filehosts_via_browser(ui["url"], driver)
            combined = " ".join(filter(None, [ui.get("_req_notes", ""), _inotes])).strip()
            new_upd.append({
                "version":     ui["version"],
                "type":        ui["type"],
                "label":       ui["label"],
                "filehosts":   fh or [],
                "inter_notes": combined,
            })
            if fh: print(f"    ✓ {ui['type']} {ui['label']} browser → {len(fh)} link(s)")
            else:  print(f"    [WARN] 0 links for {ui['label']} — notes saved: {bool(combined)}")
        rel.pop("update_inter", None)
        rel["update_direct"] = new_upd

    return releases

# ── ★ SCRAPE PAGE (main per-game function) ────────────────────────────────────
def scrape_page(url: str, title_hint: str, driver,
                inter_pool: ThreadPoolExecutor,
                img_pool: ThreadPoolExecutor) -> dict:
    """
    Full scrape of one game page. Fastest possible path:
      1. Browser loads page (CF handled by uc)
      2. Python decodes payloads from static HTML (no JS wait)
      3. Intermediary fetches submitted to thread pool (parallel, requests)
      4. Images downloaded: blogspot parallel via thread pool, wp-content batch JS
      5. Sleep while background I/O finishes
    """
    # ── Load page ─────────────────────────────────────────────────────────────
    for _attempt in range(2):
        try:
            driver.get(url)
            break
        except Exception as _e:
            print(f"  [WARN] page load error (attempt {_attempt+1}): {_e}")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            if _attempt == 0:
                jitter(2, 0.3)
            else:
                break

    wait_for_dlpsgame(driver)
    jitter(SLEEP_AFTER_LOAD, 0.3)   # brief human-like pause

    # ── Read page source + decode payloads (instant) ──────────────────────────
    page_src = driver.page_source
    soup     = BeautifulSoup(page_src, "html.parser")

    # get_payload_htmls tries Python-decode first (no JS wait), JS fallback
    payload_htmls = get_payload_htmls(driver, page_src)

    title, desc, cover_url, screenshot_urls, info_table, youtube_id = \
        extract_metadata(soup)
    print(f"  Title: {title or '(not found)'}")

    releases, global_extra = extract_releases_from_htmls(payload_htmls, page_src)

    # ── Submit intermediary fetches to thread pool (all in parallel) ──────────
    # Pre-collect all inter URLs so we can submit and then move on
    releases = _resolve_releases(releases, inter_pool, driver, soup)

    # ── Fallback: if no releases, scan page HTML directly ─────────────────────
    if not releases:
        print("  No payload links — scanning page directly for filehost links")
        content = (soup.select_one(".post-body.entry-content")
                   or soup.select_one(".entry-content")
                   or soup.select_one(".post-content")
                   or soup.select_one("article"))
        fallback_fh = []
        if content:
            seen_fb = set()
            for a in content.find_all("a", href=True):
                href  = resolve_href(a["href"].strip())
                label = a.get_text(strip=True)
                if is_filehost_url(href) and not is_guide_url(href) and href not in seen_fb:
                    fallback_fh.append({"label": label, "url": href})
                    seen_fb.add(href)
        if fallback_fh:
            releases.append({
                "ppsa":          global_extra.get("ppsa_id", ""),
                "region":        global_extra.get("region", ""),
                "contributor":   "",
                "password":      global_extra.get("password", ""),
                "game_direct":   fallback_fh,
                "update_direct": [],
            })

    # ── PPSA fallback scans ───────────────────────────────────────────────────
    if not global_extra.get("ppsa_id"):
        page_ppsas = re.findall(
            r"(PPSA\d{5})\s*[\u2013\-]\s*(USA|EUR|JPN|JAP|ASIA|UK)", page_src)
        if page_ppsas:
            seen_pc = list(dict.fromkeys(page_ppsas))
            for ppsa_pg, region_pg in seen_pc:
                entry_c = {"ppsa": ppsa_pg, "region": region_pg}
                if entry_c not in global_extra["ppsa_ids"]:
                    global_extra["ppsa_ids"].append(entry_c)
                if "ppsa_id" not in global_extra:
                    global_extra["ppsa_id"] = ppsa_pg
                    global_extra["region"]  = region_pg
            print(f"    [page-scan] PPSAs: {[c[0] for c in seen_pc]}")
            unset = [r for r in releases if not r.get("ppsa")]
            for i, rel in enumerate(unset):
                if i < len(seen_pc):
                    rel["ppsa"]   = seen_pc[i][0]
                    rel["region"] = seen_pc[i][1]
                elif len(seen_pc) == 1:
                    rel["ppsa"]   = seen_pc[0][0]
                    rel["region"] = seen_pc[0][1]
    if not global_extra.get("ppsa_id"):
        m = re.search(r"(PPSA\d{5})", page_src)
        if m:
            global_extra["ppsa_id"] = m.group(1)

    ppsa_id = global_extra.get("ppsa_id", "")

    # ── Rename keys for output ────────────────────────────────────────────────
    for rel in releases:
        rel["game"]    = rel.pop("game_direct",   [])
        rel["updates"] = rel.pop("update_direct", [])

    # ── Images (parallel) ─────────────────────────────────────────────────────
    slug     = game_slug(title or title_hint, url, ppsa_id)
    all_imgs = ([cover_url] if cover_url else []) + screenshot_urls
    img_lbls = (["cover"]   if cover_url else []) + \
               [f"screenshot_{i+1}" for i in range(len(screenshot_urls))]

    print(f"  Downloading {len(all_imgs)} image(s){f' [{ppsa_id}]' if ppsa_id else ''}...")
    screenshots = download_screenshots(all_imgs, img_lbls, slug, ppsa_id,
                                       driver=driver, page_url=url,
                                       img_pool=img_pool)

    # ── Build extra ───────────────────────────────────────────────────────────
    extra_out = {k: v for k, v in global_extra.items()
                 if k in ("ppsa_id", "ppsa_ids",
                           "voice", "screen_languages", "subtitles", "language",
                           "note", "password",
                           "game_size", "dlc_note",
                           "developer", "publisher", "players", "format", "firmware",
                           "_no_ppsa", "_ps_legacy_id", "_no_screenshots")}

    if info_table:
        # Map every known info-table key to a clean extra_out field
        _TABLE_MAP = {
            "GENRE":       "genre",
            "GENRES":      "genre",
            "RELEASE":     "release_year",
            "RELEASE YEAR":"release_year",
            "YEAR":        "release_year",
            "LANGUAGE":    "audio_language",
            "LANGUAGES":   "audio_language",
            "LANG":        "audio_language",
            "AUDIO":       "audio_language",
            "DEVELOPER":   "developer",
            "PUBLISHER":   "publisher",
            "PLAYERS":     "players",
            "PLAYER":      "players",
            "FORMAT":      "format",
            "DISC FORMAT": "format",
            "FIRMWARE":    "firmware",
            "SIZE":        "game_size",
            "GAME SIZE":   "game_size",
            "BASE SIZE":   "game_size",
        }
        for tkey, ekey in _TABLE_MAP.items():
            if tkey in info_table and ekey not in extra_out:
                extra_out[ekey] = info_table[tkey]
        extra_out["info_table"] = info_table
    if youtube_id:
        extra_out["youtube_id"] = youtube_id

    if not extra_out.get("ppsa_id") and releases and not extra_out.get("_no_ppsa"):
        print("  [no-ppsa] full scrape found no PPSA — marking _no_ppsa=True")
        extra_out["_no_ppsa"] = True

    shot_results = [s for s in screenshots if s.get("role", "").startswith("screenshot_")]
    if not shot_results and not extra_out.get("_no_screenshots"):
        print("  [no-screenshots] full scrape found no screenshots")
        extra_out["_no_screenshots"] = True

    n_game   = sum(len(r["game"])    for r in releases)
    n_upd    = sum(len(r["updates"]) for r in releases)
    print(f"  ✓ {len(releases)} release(s), {n_game} game link(s), "
          f"{n_upd} update/dlc group(s), {len(screenshots)} screenshot(s)")

    return {
        "url":         url,
        "title":       title or title_hint,
        "description": desc,
        "screenshots": screenshots,
        "releases":    releases,
        "extra":       extra_out,
        "scraped_at":  __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

# ── ★ PATCH ENTRY ─────────────────────────────────────────────────────────────
def patch_entry(entry: dict, driver,
                inter_pool: ThreadPoolExecutor,
                img_pool: ThreadPoolExecutor) -> dict:
    """
    Re-visit a cached entry and fill in only what is missing.
    Fast path: if only images are missing and URLs are already stored, download
    without reloading the page. Full path: re-scrape as needed.
    """
    url        = entry["url"]
    title_hint = entry.get("title", url)
    missing    = entry_missing(entry)
    print(f"  Patching: {', '.join(sorted(missing))}")

    existing_extra = entry.get("extra") or {}
    ppsa_id        = existing_extra.get("ppsa_id", "")
    slug           = game_slug(entry.get("title") or title_hint, url, ppsa_id)

    # ── Fast path: image URLs already stored, just download ──────────────────
    image_only_missing = missing - {"cover", "screenshots"}
    if not image_only_missing:
        shots      = entry.get("screenshots") or []
        cached_urls = {s["role"]: s["url"] for s in shots
                       if isinstance(s, dict) and s.get("url")}
        fast_urls, fast_labels = [], []
        if "cover" in missing:
            cu = cached_urls.get("cover")
            if cu:
                fast_urls.append(cu); fast_labels.append("cover")
        if "screenshots" in missing:
            for s in shots:
                if isinstance(s, dict) and s.get("role", "").startswith("screenshot_"):
                    if s.get("url"):
                        fast_urls.append(s["url"]); fast_labels.append(s["role"])

        if fast_urls:
            print(f"  Fast path: downloading {len(fast_urls)} image(s) from cached URLs")
            fresh    = download_screenshots(fast_urls, fast_labels, slug, ppsa_id,
                                            driver=driver, page_url=url,
                                            img_pool=img_pool)
            role_map = {s["role"]: s for s in shots}
            for s in fresh:
                if s.get("local"):
                    role_map[s["role"]] = s
            entry["screenshots"] = list(role_map.values())
            entry.pop("error", None)
            driver._last_was_page_load = False
            return entry

    # ── Full path: reload the page ────────────────────────────────────────────
    for _attempt in range(2):
        try:
            driver.get(url)
            break
        except Exception as _e:
            print(f"  [WARN] page load error (attempt {_attempt+1}): {_e}")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            if _attempt == 0:
                jitter(2, 0.3)
            else:
                break

    wait_for_dlpsgame(driver)
    jitter(SLEEP_AFTER_LOAD, 0.3)

    page_src      = driver.page_source
    soup          = BeautifulSoup(page_src, "html.parser")
    payload_htmls = get_payload_htmls(driver, page_src)

    title, desc, cover_url, screenshot_urls, info_table, youtube_id = \
        extract_metadata(soup)
    releases, global_extra = extract_releases_from_htmls(payload_htmls, page_src)

    # ── Merge info_table + youtube_id into existing_extra ────────────────────
    if info_table:
        if "GENRE" in info_table and "genre" not in existing_extra:
            existing_extra["genre"] = info_table["GENRE"]
        if "RELEASE" in info_table and "release_year" not in existing_extra:
            existing_extra["release_year"] = info_table["RELEASE"]
        lv = (info_table.get("LANGUAGE") or info_table.get("LANGUAGES")
              or info_table.get("LANG"))
        if lv and "table_language" not in existing_extra:
            existing_extra["table_language"] = lv
        if "info_table" not in existing_extra:
            existing_extra["info_table"] = info_table
    if youtube_id and "youtube_id" not in existing_extra:
        existing_extra["youtube_id"] = youtube_id

    # ── PPSA ─────────────────────────────────────────────────────────────────
    ppsa_id = global_extra.get("ppsa_id", "")
    if not ppsa_id:
        m = re.search(r"(PPSA\d{5})", page_src)
        if m:
            ppsa_id = m.group(1)
            global_extra["ppsa_id"] = ppsa_id

    for k, v in global_extra.items():
        if k in ("region", "password"):
            continue
        if not existing_extra.get(k):
            existing_extra[k] = v
    entry["extra"] = existing_extra

    ppsa_found = existing_extra.get("ppsa_id") or any(
        r.get("ppsa") for r in entry.get("releases", []))
    if not ppsa_found and entry.get("releases") and not existing_extra.get("_no_ppsa"):
        print("  [no-ppsa] patch re-scrape found no PPSA — marking _no_ppsa=True")
        existing_extra["_no_ppsa"] = True

    new_shots = [s for s in entry.get("screenshots", [])
                 if s.get("role", "").startswith("screenshot_")]
    if not new_shots and not existing_extra.get("_no_screenshots"):
        print("  [no-screenshots] patch re-scrape found no screenshots")
        existing_extra["_no_screenshots"] = True

    ppsa_id = existing_extra.get("ppsa_id", ppsa_id)

    if not entry.get("title") or entry["title"] == url:
        entry["title"] = title or title_hint
    if not entry.get("description") and desc:
        entry["description"] = desc

    slug = game_slug(entry.get("title") or title_hint, url, ppsa_id)

    # ── Rename screenshot folder if PPSA was just discovered ─────────────────
    if ppsa_id and not existing_extra.get("_had_ppsa_before"):
        old_slug = game_slug(entry.get("title") or title_hint, url, "")
        if old_slug != slug:
            old_dir = Path(SCREENSHOTS_DIR) / old_slug
            new_dir = Path(SCREENSHOTS_DIR) / slug
            if old_dir.exists() and not new_dir.exists():
                old_dir.rename(new_dir)
                existing_extra["_had_ppsa_before"] = True
                print(f"  Renamed screenshots folder: {old_slug} → {slug}")
                updated = []
                for s in entry.get("screenshots", []):
                    if isinstance(s, dict) and s.get("local"):
                        new_local = s["local"].replace(
                            f"{SCREENSHOTS_DIR}/{old_slug}/",
                            f"{SCREENSHOTS_DIR}/{slug}/", 1)
                        updated.append({**s, "local": new_local})
                    else:
                        updated.append(s)
                entry["screenshots"] = updated

    # ── Cover + screenshots ───────────────────────────────────────────────────
    need_cover = "cover" in missing
    need_shots = "screenshots" in missing
    new_urls, new_labels = [], []
    if need_cover and cover_url:
        new_urls.append(cover_url); new_labels.append("cover")
    if need_shots:
        for i, su in enumerate(screenshot_urls):
            new_urls.append(su); new_labels.append(f"screenshot_{i+1}")

    if new_urls:
        fresh    = download_screenshots(new_urls, new_labels, slug, ppsa_id,
                                        driver=driver, page_url=url,
                                        img_pool=img_pool)
        role_map = {s["role"]: s for s in entry.get("screenshots", [])}
        for s in fresh:
            if s.get("local"):
                role_map[s["role"]] = s
        entry["screenshots"] = list(role_map.values())

    # ── Releases ─────────────────────────────────────────────────────────────
    has_stubs = any(not r.get("game") for r in entry.get("releases", []))
    if "releases" not in entry or not entry.get("releases") or has_stubs:
        releases = _resolve_releases(releases, inter_pool, driver, soup)
        for rel in releases:
            rel["game"]    = rel.pop("game_direct",   [])
            rel["updates"] = rel.pop("update_direct", [])
        entry["releases"] = releases
        entry.pop("filehosts", None)
        entry.pop("updates",   None)

    entry.pop("error", None)
    entry["scraped_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return entry

# ── NEW-GAME DISCOVERY ────────────────────────────────────────────────────────
_GAME_URL_RE = re.compile(
    r'^https?://dlpsgame\.com/'
    # Block WP infrastructure and all known non-game slug prefixes.
    # These are sidebar/footer links present on every page of the site.
    r'(?!category/|tag/|page/|author/|wp-|feed|#|\?'
    r'|dmca[-/]?$'           # /dmca/
    r'|warning-'             # /warning-about-website-content-theft/
    r'|guide[-/]'            # /guide-jdownloader-2/, /guide-to-download-at-highest-speed/
    r'|all-guide[-/]'        # /all-guide-install-ps2/, /all-guide-install-ps4-2024/
    r'|daily-update[-/]'     # /daily-update-on-changes-to-game/
    r'|list-game[-/]'        # /list-game-ps5/
    r'|list-all-game[-/]'    # /list-all-game-ps4/, /list-all-game-ps3/, /list-all-game-ps2/
    r'|update-list[-/]'      # future /update-list-all-game-*/
    r')'
    r'[a-zA-Z0-9][a-zA-Z0-9\-]+/?$'
)
_SKIP_TITLE_LABELS = {
    # Generic UI labels
    "download", "read more", "continue reading", "more", "here",
    # Guide pages
    "guide", "tool download", "guide download",
    "guide troubleshooting jdownloader",
    "guide download max speed mediafire",
    "all guide install ps2", "all guide install ps4", "all guide install ps5",
    # Update / list pages
    "daily update game", "daily update on changes to game",
    "list game ps5", "list game ps4", "list game ps3", "list game ps2",
    "update list all game ps5", "update list all game ps4",
    "update list all game ps3", "update list all game ps2",
    "update list all game switch", "update list all game wii",
    "update list all game wii u", "update list all game 3ds",
    "update list all game pc (windows/mac)",
    "update list all game xbox - jtag/rgh", "update list all game xbox - iso",
    "update list game psp, ppsspp",
    # Policy / meta pages
    "dmca",
    "we only publish on the website: dlpsgame.com",
    # Console names used as bare anchor text
    "ps5", "ps4", "ps3", "ps2", "pc", "switch",
}

def _extract_game_links_from_page(driver) -> list:
    seen: set = set(); results: list = []
    def add(href: str, title: str) -> None:
        href = href.strip().rstrip("/") + "/"
        if href in seen or not _GAME_URL_RE.match(href): return
        seen.add(href)
        title = (title or "").strip() or href.rstrip("/").split("/")[-1].replace("-", " ").title()
        results.append((href, title))
    try:
        pairs = driver.execute_script("""
            var out = [];
            document.querySelectorAll('.post, .hentry, article').forEach(function(post) {
                var titleEl = post.querySelector('.post-title, .entry-title, h1, h2, h3');
                var titleText = titleEl ? (titleEl.innerText || titleEl.textContent || '').trim() : '';
                post.querySelectorAll('a[href]').forEach(function(a) {
                    var h = (a.href || '').trim();
                    var t = titleText || (a.innerText || a.textContent || '').trim();
                    if (h) out.push([h, t]);
                });
            });
            return out;
        """) or []
        for href, title in pairs: add(href, title)
    except Exception: pass
    try:
        all_anchors = driver.execute_script("""
            var out = [];
            document.querySelectorAll('a[href]').forEach(function(a) {
                var h = (a.href || '').trim(); var t = (a.innerText || a.textContent || '').trim();
                if (h && t) out.push([h, t]);
            });
            return out;
        """) or []
        for href, title in all_anchors:
            if title.lower().strip() not in _SKIP_TITLE_LABELS and len(title) > 2: add(href, title)
    except Exception: pass
    try:
        for m in re.finditer(r'href=["\'\']?(https?://dlpsgame\.com/[^"\'\'>\s]+)', driver.page_source):
            add(m.group(1), "")
    except Exception: pass
    return results


def discover_new_games(driver, known_urls: set) -> list:
    new_games = []; bootstrap = len(known_urls) == 0
    print("\n── New-game discovery (PS5) ──────────────────────────────────────────")
    if bootstrap: print("  [bootstrap] No existing list — scraping ALL pages.")
    for cat_url in CATEGORY_URLS:
        print(f"  Scanning: {cat_url}")
        for page_num in range(1, MAX_DISCOVERY_PAGES + 1):
            page_url = cat_url if page_num == 1 else f"{cat_url}page/{page_num}/"
            try:
                driver.get(page_url); wait_for_cf(driver); jitter(2, 0.5)
                raw_links = _extract_game_links_from_page(driver)
                if not raw_links: print(f"    Page {page_num}: no game links — stopping"); break
                page_new = 0; page_all_known = True
                for href, title in raw_links:
                    if href in known_urls: continue
                    new_games.append({"title": title, "url": href}); known_urls.add(href)
                    page_new += 1; page_all_known = False; print(f"    + {title}")
                print(f"    Page {page_num}: {page_new} new game(s)")
                if page_all_known:
                    print(f"    Page {page_num}: {'no new games — end of site' if bootstrap else 'all known — stopping'}"); break
            except Exception as e: print(f"    [ERROR] page {page_num}: {e}"); break
    print(f"  Total new: {len(new_games)}")
    print("─────────────────────────────────────────────────────────────────────\n")
    return new_games

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    # ── Load inputs ───────────────────────────────────────────────────────────
    if not Path(INPUT_JSON).is_file():
        print(f"[bootstrap] '{INPUT_JSON}' not found — will discover ALL games from site.")
        games      = []
        known_urls = set()
    else:
        with open(INPUT_JSON, "r", encoding="utf-8") as f:
            games = json.load(f)
        known_urls = set((g.get("url") or "").strip().rstrip("/") + "/"
                         for g in games if g.get("url"))

    # ── Load cache ────────────────────────────────────────────────────────────
    cache      = {}
    cache_file = Path(OUTPUT_JSON)
    if cache_file.is_file():
        cache_size = cache_file.stat().st_size
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            cache = {e["url"]: e for e in loaded if e.get("url")}
        except Exception as e:
            print(f"FATAL: '{OUTPUT_JSON}' exists ({cache_size:,} bytes) but failed to parse: {e}")
            return

        if cache_size > 10_000 and len(cache) == 0:
            print(f"FATAL: '{OUTPUT_JSON}' is {cache_size:,} bytes but 0 valid entries.")
            return

        if len(cache) == 0 and cache_size > 100:
            print(f"WARNING: '{OUTPUT_JSON}' loaded 0 entries ({cache_size:,} bytes).")
            confirm = input("         Continue (re-scrape everything)? [y/N] ").strip().lower()
            if confirm != "y":
                print("Aborted."); return

    statuses   = {url: entry_missing(e) for url, e in cache.items()}
    fully_done = sum(1 for m in statuses.values() if not m)
    need_patch = sum(1 for m in statuses.values() if m)
    print(f"Loaded {len(games)} games — {len(cache)} cached "
          f"({fully_done} complete, {need_patch} need patching).")

    # ── Browser setup ─────────────────────────────────────────────────────────
    _WIN_SIZES = [
        (1920, 1080), (1920, 1080), (1920, 1080),
        (1440, 900),  (1536, 864),  (1366, 768),
        (2560, 1440), (1280, 800),  (1600, 900),
    ]
    win_w, win_h = _random.choice(_WIN_SIZES)

    options = uc.ChromeOptions()
    options.headless = False
    options.add_argument(f"--window-size={win_w},{win_h}")
    print(f"[browser] Window: {win_w}×{win_h} | Between-game sleep: {SLEEP_BETWEEN_GAMES}s")

    driver = uc.Chrome(options=options)
    driver.set_page_load_timeout(300)
    driver.set_script_timeout(120)   # 120 s for batch image Promise.all()
    try:
        driver.command_executor._client_config.timeout = 300
    except Exception:
        try:
            driver.command_executor.set_timeout(300)
        except Exception:
            pass

    # ── Shared thread pools ───────────────────────────────────────────────────
    inter_pool = ThreadPoolExecutor(max_workers=_INTER_WORKERS,
                                    thread_name_prefix="inter")
    img_pool   = ThreadPoolExecutor(max_workers=_IMG_WORKERS,
                                    thread_name_prefix="img")

    def atomic_write(path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def save_games():
        # Deduplicate by URL before writing — prevents duplicate game cards in UI
        seen_g: set = set()
        deduped_g = []
        for g in games:
            url = (g.get("url") or "").strip().rstrip("/") + "/"
            if url and url in seen_g:
                continue
            if url:
                seen_g.add(url)
            deduped_g.append(g)
        if len(deduped_g) < len(games):
            print(f"  [dedup] games list: removed {len(games) - len(deduped_g)} duplicate(s)")
        atomic_write(INPUT_JSON, deduped_g)

    def save_cache():
        # Write in games[] order so newest games (prepended by discovery) appear first.
        # dict insertion order would put newly-scraped entries at the end, which is wrong.
        seen = set()
        ordered = []
        for g in games:
            url = (g.get("url") or "").strip()
            if url and url in cache and url not in seen:
                ordered.append(cache[url])
                seen.add(url)
        # Safety: include any cache entries not in the games list (shouldn't happen)
        for url, entry in cache.items():
            if url not in seen:
                ordered.append(entry)
        atomic_write(OUTPUT_JSON, ordered)

    try:
        # ── Discovery ─────────────────────────────────────────────────────────
        new_games = discover_new_games(driver, known_urls)
        if new_games:
            games = new_games + games
            # Deduplicate immediately after merging (safety net)
            seen_merge: set = set()
            games_deduped = []
            for g in games:
                u = (g.get("url") or "").strip().rstrip("/") + "/"
                if u and u in seen_merge:
                    continue
                if u:
                    seen_merge.add(u)
                games_deduped.append(g)
            if len(games_deduped) < len(games):
                print(f"  [dedup] merged games list: removed {len(games) - len(games_deduped)} duplicate(s)")
            games = games_deduped
            save_games()
            print(f"Added {len(new_games)} new game(s) to {INPUT_JSON}")

        # ── Main loop ─────────────────────────────────────────────────────────
        for idx, game in enumerate(games):
            url        = (game.get("url") or "").strip().rstrip("/") + "/"
            title_hint = game.get("title") or f"Game #{idx+1}"
            if not url or url == "/":
                continue

            cached = cache.get(url)

            if cached and not statuses.get(url):
                print(f"[{idx+1}/{len(games)}] SKIP: {title_hint}")
                continue

            print(f"\n[{idx+1}/{len(games)}] {title_hint}")
            print(f"  URL: {url}")

            try:
                if cached:
                    cache[url] = patch_entry(cached, driver, inter_pool, img_pool)
                else:
                    cache[url] = scrape_page(url, title_hint, driver,
                                             inter_pool, img_pool)

            except Exception as e:
                print(f"  [ERROR] {e}")
                traceback.print_exc()
                if not cached:
                    cache[url] = {
                        "url": url, "title": title_hint,
                        "description": "", "screenshots": [],
                        "releases": [], "extra": {},
                        "error": str(e),
                    }
                else:
                    cached["error"] = str(e)
                try:
                    driver.execute_script("window.stop();")
                    driver.get("about:blank")
                except Exception:
                    pass

            save_cache()

            # Only sleep after a real page load — image-only fast-path skips it
            did_page_load = getattr(driver, '_last_was_page_load', True)
            if did_page_load:
                jitter(SLEEP_BETWEEN_GAMES, 0.3)   # 8 s ± 30 % (was 45 s)
            driver._last_was_page_load = True

    finally:
        save_cache()
        inter_pool.shutdown(wait=False)
        img_pool.shutdown(wait=False)
        driver.quit()

    print(f"\nDone! {len(cache)} entries in '{OUTPUT_JSON}'")


if __name__ == "__main__":
    main()
