from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium_stealth import stealth

import random
import pytz
import time
import os
import threading
import zipfile
import json
import tempfile
from pathlib import Path
from pystyle import Center, Colors, Colorate

os.system("title SoundCloud Streaming Bot")

# ── Constants ─────────────────────────────────────────────────────────────────

SKIP_CHANCE      = 0.40   # 40 % of tracks get skipped
SKIP_AFTER_MIN   = 40     # seconds — earliest skip
SKIP_AFTER_MAX   = 60     # seconds — latest skip
TRACK_WAIT_MAX   = 360    # seconds — max wait for track change before giving up

SESSION_MIN_SECS = 30 * 60        # 30 minutes
SESSION_MAX_SECS = 4  * 60 * 60   # 4 hours

WANDER_EVERY_MIN = 4
WANDER_EVERY_MAX = 9

# Priority artist — modern_monster on SoundCloud
# URL format: https://soundcloud.com/<username>
PRIORITY_ARTIST_URL    = "https://soundcloud.com/modernmonsterband"
PRIORITY_ARTIST_WEIGHT = 0.70

# Metal / rock / alt-rock artists to wander into (fallback list)
GENRE_URLS = [
    PRIORITY_ARTIST_URL,                              # modern_monster  ← priority
    "https://soundcloud.com/metallica",
    "https://soundcloud.com/nirvana",
    "https://soundcloud.com/thearcticmonkeys",
    "https://soundcloud.com/radiohead",
    "https://soundcloud.com/foofighters",
    "https://soundcloud.com/slipknot",
    "https://soundcloud.com/disturbed",
    "https://soundcloud.com/avengedsevenfold",
    "https://soundcloud.com/deftones",
    "https://soundcloud.com/systemofadown",
    "https://soundcloud.com/aliceinchains",
    "https://soundcloud.com/soundgarden",
    "https://soundcloud.com/rageagainstthemachine",
    "https://soundcloud.com/theblackkeys",
    "https://soundcloud.com/twentyonepilots",
    "https://soundcloud.com/imaginedragons",
    "https://soundcloud.com/paparoach",
]

supported_timezones = pytz.all_timezones

user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
]

supported_languages = [
    "en-US", "en-GB", "fr-FR", "de-DE", "es-ES", "it-IT", "tr-TR", "ru-RU"
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts():
    """HH:MM:SS timestamp for log lines."""
    return time.strftime('%H:%M:%S')


def set_random_timezone(driver):
    tz = random.choice(supported_timezones)
    driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": tz})


def set_fake_geolocation(driver):
    driver.execute_cdp_cmd("Emulation.setGeolocationOverride", {
        "latitude":  random.uniform(-90,  90),
        "longitude": random.uniform(-180, 180),
        "accuracy":  100,
    })


def _weighted_pick(candidates):
    """Pick a URL; give PRIORITY_ARTIST_URL a PRIORITY_ARTIST_WEIGHT pull when present."""
    priority = [u for u in candidates if PRIORITY_ARTIST_URL in u]
    others   = [u for u in candidates if PRIORITY_ARTIST_URL not in u]
    if priority and random.random() < PRIORITY_ARTIST_WEIGHT:
        return random.choice(priority)
    return random.choice(others) if others else random.choice(priority)


# ── SoundCloud DOM helpers ────────────────────────────────────────────────────

def dismiss_overlays(driver):
    """
    Close SoundCloud cookie banners, "Get the app" prompts, and login nudges.
    """
    selectors = [
        # Cookie consent
        "#onetrust-accept-btn-handler",
        "button[id*='accept']",
        # "Get the app" banner close
        ".appBanner__close",
        "button.sc-button-close",
        # Generic modal/overlay close
        ".modal__closeButton",
        "[aria-label='Close']",
        "[aria-label='close']",
    ]
    for sel in selectors:
        try:
            btn = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            btn.click()
            time.sleep(0.3)
        except Exception:
            pass
    try:
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
        time.sleep(0.2)
    except Exception:
        pass


def click_play_sc(driver):
    """
    Click the play button on a SoundCloud track, playlist, or artist page.
    Tries in order:
      1. The big play button on a track/album hero
      2. The first track in a playlist/artist tracklist
      3. The player-bar play button (already loaded context)
      4. Space bar toggle
    """
    selectors = [
        # Track / playlist / artist hero play button
        (By.CSS_SELECTOR, "button.playButton"),
        (By.CSS_SELECTOR, "button.sc-button-play"),
        (By.CSS_SELECTOR, ".playableTile__playButton button"),
        (By.CSS_SELECTOR, ".sound__coverArt .playButton"),
        # First item in a tracklist
        (By.CSS_SELECTOR, "li.trackList__item:first-child .playButton"),
        (By.CSS_SELECTOR, "li.trackList__item:first-child button.sc-button-play"),
        # Player bar
        (By.CSS_SELECTOR, "button.playControls__play"),
        (By.CSS_SELECTOR, ".playControls__soundBadge button.playButton"),
        # aria-label fallbacks
        (By.XPATH, "//button[@aria-label='Play']"),
        (By.XPATH, "//button[contains(@aria-label,'Play')]"),
    ]
    for by, sel in selectors:
        try:
            btn = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((by, sel)))
            btn.click()
            return
        except Exception:
            pass
    # Space bar last resort
    try:
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.SPACE)
        return
    except Exception:
        pass
    # Save page for debugging
    try:
        debug_file = Path(tempfile.gettempdir()) / "sc_play_fail.html"
        debug_file.write_text(driver.page_source, encoding='utf-8')
    except Exception:
        pass
    raise NoSuchElementException(
        "Could not find a SoundCloud play button — page saved to sc_play_fail.html"
    )


def click_next_sc(driver):
    """Click the skip-forward button in the SoundCloud player bar."""
    selectors = [
        (By.CSS_SELECTOR, "button.skipControl__next"),
        (By.CSS_SELECTOR, ".playControls__elements button[title='Next']"),
        (By.XPATH,        "//button[@aria-label='Next']"),
        (By.XPATH,        "//button[contains(@aria-label,'Next')]"),
        (By.XPATH,        "//button[@title='Next']"),
    ]
    for by, sel in selectors:
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((by, sel)))
            btn.click()
            return True
        except Exception:
            pass
    return False


def get_current_track_sc(driver):
    """
    Return (track_title, artist_name) from the SoundCloud player bar.
    Falls back to (None, None).
    """
    title = None
    artist = None

    title_selectors = [
        ".playbackSoundBadge__titleLink span",
        ".playbackSoundBadge__title a",
        "a.playbackSoundBadge__titleLink",
        ".playbackSoundBadge__title",
    ]
    for sel in title_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip() or el.get_attribute('title', '').strip()
            if text:
                title = text
                break
        except Exception:
            pass

    artist_selectors = [
        ".playbackSoundBadge__lightLink",
        ".playbackSoundBadge__avatar ~ * a",
        "a.playbackSoundBadge__artistLink",
        ".playbackSoundBadge__subtitle a",
    ]
    for sel in artist_selectors:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text:
                artist = text
                break
        except Exception:
            pass

    return title, artist


def detect_sc_url_type(url):
    """Return 'track', 'playlist', 'album', or 'artist' for a SoundCloud URL."""
    url = url.lower()
    if '/sets/' in url:
        return 'playlist'
    # SoundCloud track URLs: soundcloud.com/artist/trackname (exactly 2 path segments after host)
    path = url.replace('https://soundcloud.com/', '').replace('http://soundcloud.com/', '').strip('/')
    parts = [p for p in path.split('/') if p]
    if len(parts) == 1:
        return 'artist'
    if len(parts) >= 2:
        return 'track'
    return 'artist'


def enable_sc_repeat(driver):
    """
    Enable repeat on the SoundCloud player (click until active).
    The repeat button cycles: off → repeat-all → repeat-one → off
    """
    for _ in range(3):
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR,
                    "button.repeatControl, button[title*='Repeat'], button[aria-label*='Repeat']"))
            )
            classes = btn.get_attribute('class') or ''
            title   = (btn.get_attribute('title') or btn.get_attribute('aria-label') or '').lower()
            # If already active (sc-button-active class or title says "Disable"), stop
            if 'active' in classes or 'disable' in title:
                break
            btn.click()
            time.sleep(0.4)
        except Exception:
            break


def navigate_to_recommended_sc(driver, origin_url):
    """
    Wander to a related or genre artist on SoundCloud.

    Strategy:
      1. Scrape all /username (artist) hrefs from the current page sidebar / related section.
      2. Inject PRIORITY_ARTIST_URL if not already found.
      3. Pick via _weighted_pick and navigate.
      4. Fallback: pick from GENRE_URLS via _weighted_pick.
    """
    try:
        current_host = driver.current_url.split('?')[0]

        # Collect all soundcloud.com/<artist> links (1 path segment) on the page
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='soundcloud.com/']")
        seen, candidates = set(), []
        for a in links:
            href = (a.get_attribute('href') or '').split('?')[0].rstrip('/')
            if not href.startswith('http'):
                continue
            # Must be soundcloud.com/<artist> — exactly one path segment after host
            path = href.replace('https://soundcloud.com/', '').replace('http://soundcloud.com/', '').strip('/')
            parts = [p for p in path.split('/') if p]
            if len(parts) == 1 and href not in seen and href != current_host:
                seen.add(href)
                candidates.append(href)

        # Always give modern_monster a slot
        if PRIORITY_ARTIST_URL not in seen:
            candidates.append(PRIORITY_ARTIST_URL)

        if candidates:
            chosen = _weighted_pick(candidates)
            driver.get(chosen)
            time.sleep(4)
            dismiss_overlays(driver)
            click_play_sc(driver)
            return chosen
    except Exception:
        pass

    # Fallback
    try:
        pool = [u for u in GENRE_URLS if u != origin_url]
        chosen = _weighted_pick(pool if pool else GENRE_URLS)
        driver.get(chosen)
        time.sleep(4)
        dismiss_overlays(driver)
        click_play_sc(driver)
        return chosen
    except Exception:
        pass

    return None


# ── Playback loop ─────────────────────────────────────────────────────────────

def playback_loop_sc(driver, username, origin_url, session_end_time):
    """
    Background thread per account.
    • Session expires randomly between 30 min and 4 hours.
    • 40 % chance of skip at 40-60 s.
    • Every 4-9 songs: wander to a related/genre artist.
    • Full logging with timestamps, track name, artist, fate.
    """
    acct = username.split('@')[0]
    song_number        = 0
    songs_since_wander = 0
    next_wander_at     = random.randint(WANDER_EVERY_MIN, WANDER_EVERY_MAX)

    while True:
        try:
            # ── Session timeout ────────────────────────────────────────────
            if time.time() >= session_end_time:
                print(Colors.cyan,
                      f"[{_ts()}] [{acct}] Session time reached — closing browser.")
                try:
                    driver.quit()
                except Exception:
                    pass
                return

            song_number        += 1
            songs_since_wander += 1

            track, artist = get_current_track_sc(driver)
            will_skip  = random.random() < SKIP_CHANCE
            wait_time  = random.randint(SKIP_AFTER_MIN, SKIP_AFTER_MAX)

            track_label  = f'"{track}"'    if track  else '(unknown track)'
            artist_label = f' by {artist}' if artist else ''
            fate_label   = f'SKIP at {wait_time}s' if will_skip else f'playing ~{wait_time}s+'

            print(Colors.green,
                  f"[{_ts()}] [{acct}] #{song_number:>3} ▶ {track_label}{artist_label}  [{fate_label}]")

            time.sleep(wait_time)

            if will_skip:
                if click_next_sc(driver):
                    print(Colors.yellow,
                          f"[{_ts()}] [{acct}] #{song_number:>3} ✂ Skipped at {wait_time}s")
                else:
                    print(Colors.yellow,
                          f"[{_ts()}] [{acct}] #{song_number:>3} ✂ Skip failed — letting SC advance")

            # ── Wait for track to change ───────────────────────────────────
            waited = 0
            while waited < TRACK_WAIT_MAX:
                if time.time() >= session_end_time:
                    break
                time.sleep(2)
                waited += 2
                new_track, new_artist = get_current_track_sc(driver)
                if new_track and new_track != track:
                    new_label  = f'"{new_track}"'
                    new_art    = f' by {new_artist}' if new_artist else ''
                    print(Colors.green,
                          f"[{_ts()}] [{acct}] #{song_number:>3} ↪ Now playing: {new_label}{new_art}")
                    break

            # ── Genre / recommended wander ─────────────────────────────────
            if songs_since_wander >= next_wander_at:
                songs_since_wander = 0
                next_wander_at     = random.randint(WANDER_EVERY_MIN, WANDER_EVERY_MAX)
                print(Colors.cyan,
                      f"[{_ts()}] [{acct}] 🔀 Wandering to related/genre content "
                      f"(next in {next_wander_at} songs)…")
                new_ctx = navigate_to_recommended_sc(driver, origin_url)
                if new_ctx:
                    time.sleep(3)
                    _, ctx_artist = get_current_track_sc(driver)
                    ctx_label = ctx_artist if ctx_artist else new_ctx
                    print(Colors.cyan,
                          f"[{_ts()}] [{acct}] 🔀 Now browsing: {ctx_label}")
                else:
                    print(Colors.yellow,
                          f"[{_ts()}] [{acct}] 🔀 Wander failed — returning to origin.")
                    driver.get(origin_url)
                    time.sleep(4)
                    dismiss_overlays(driver)
                    click_play_sc(driver)

        except Exception as e:
            err = str(e).lower()
            if 'invalid session' in err or 'no such window' in err or 'target window already closed' in err:
                print(Colors.red,
                      f"[{_ts()}] [{acct}] Browser session ended — loop stopped.")
                break
            print(Colors.red,
                  f"[{_ts()}] [{acct}] Transient error (retrying): {str(e)[:120]}")
            time.sleep(5)


# ── Proxy extension builder (shared with Spotify bot) ────────────────────────

def create_proxy_auth_extension(proxy_host, proxy_port, proxy_user, proxy_pass, plugin_path):
    manifest = {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy", "tabs", "unlimitedStorage", "storage",
            "<all_urls>", "webRequest", "webRequestBlocking"
        ],
        "background": {"scripts": ["background.js"]},
        "minimum_chrome_version": "22.0.0"
    }
    bg = f"""
var config = {{
  mode: "fixed_servers",
  rules: {{
    singleProxy: {{ scheme: "http", host: "{proxy_host}", port: parseInt({proxy_port}) }},
    bypassList: ["localhost"]
  }}
}};
chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});
function callbackFn(details) {{
  return {{authCredentials: {{username: "{proxy_user}", password: "{proxy_pass}"}}}};
}}
chrome.webRequest.onAuthRequired.addListener(callbackFn, {{urls: ["<all_urls>"]}}, ['blocking']);
"""
    with zipfile.ZipFile(plugin_path, 'w') as zp:
        zp.writestr('manifest.json', json.dumps(manifest))
        zp.writestr('background.js', bg)


# ── Login ─────────────────────────────────────────────────────────────────────

def login_soundcloud(driver, username, password, acct_idx):
    """
    Log in to SoundCloud.
    Flow:
      1. Navigate to soundcloud.com/signin
      2. Accept cookies if prompted
      3. Fill email + password and submit
      4. Detect captcha / 2FA and prompt user if needed
    """
    driver.get("https://soundcloud.com/signin")

    # Cookie consent
    try:
        WebDriverWait(driver, 6).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#onetrust-accept-btn-handler"))
        ).click()
        time.sleep(0.5)
    except Exception:
        pass

    # Wait for the sign-in form
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[autocomplete='username'], input[type='email']"))
        )
    except Exception:
        debug_file = Path(tempfile.gettempdir()) / f"sc_login_{acct_idx}.html"
        try:
            debug_file.write_text(driver.page_source, encoding='utf-8')
        except Exception:
            pass
        raise NoSuchElementException(
            f"SoundCloud login form not found. Page saved to {debug_file}"
        )

    # Fill email
    for sel in ["input[autocomplete='username']", "input[type='email']", "input[name='username']"]:
        try:
            field = driver.find_element(By.CSS_SELECTOR, sel)
            field.click()
            field.clear()
            field.send_keys(username)
            break
        except Exception:
            pass

    # Fill password — SoundCloud may show password on same page or a next step
    pw_field = None
    for sel in ["input[type='password']", "input[autocomplete='current-password']"]:
        try:
            pw_field = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            break
        except Exception:
            pass

    if pw_field is None:
        # Password is on a second page — submit email first
        try:
            driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            time.sleep(2)
        except Exception:
            pass
        for sel in ["input[type='password']", "input[autocomplete='current-password']"]:
            try:
                pw_field = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                break
            except Exception:
                pass

    if pw_field:
        pw_field.click()
        pw_field.clear()
        pw_field.send_keys(password)
        try:
            driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        except Exception:
            pw_field.send_keys(Keys.RETURN)
    else:
        raise NoSuchElementException("Could not find SoundCloud password field")

    # Wait for redirect away from signin
    for _ in range(20):
        time.sleep(1)
        cur = driver.current_url.lower()
        if 'signin' not in cur and 'soundcloud.com' in cur:
            break

    # Check for captcha / challenge page
    cur = driver.current_url.lower()
    if 'signin' in cur or 'challenge' in cur or 'verify' in cur:
        print(Colors.yellow,
              f"\n[SC LOGIN] {username} — verification required.")
        print(Colors.yellow,
              "  Complete the challenge in the browser window, then press ENTER here.")
        input(f"  Press ENTER once {username} is logged in: ")

    print(Colors.green, f"  [SC] Logged in: {username}")
    time.sleep(2)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(Colorate.Vertical(Colors.white_to_blue, Center.XCenter("""

              ███████╗ ██████╗ ██╗   ██╗███╗   ██╗██████╗  ██████╗██╗      ██████╗ ██╗   ██╗██████╗
              ██╔════╝██╔═══██╗██║   ██║████╗  ██║██╔══██╗██╔════╝██║     ██╔═══██╗██║   ██║██╔══██╗
              ███████╗██║   ██║██║   ██║██╔██╗ ██║██║  ██║██║     ██║     ██║   ██║██║   ██║██║  ██║
              ╚════██║██║   ██║██║   ██║██║╚██╗██║██║  ██║██║     ██║     ██║   ██║██║   ██║██║  ██║
              ███████║╚██████╔╝╚██████╔╝██║ ╚████║██████╔╝╚██████╗███████╗╚██████╔╝╚██████╔╝██████╔╝
              ╚══════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝╚═════╝  ╚═════╝╚══════╝ ╚═════╝  ╚═════╝ ╚═════╝
                                    Streaming Bot — stealth edition
""")))
    print("")

    # ── Load accounts ──────────────────────────────────────────────────────
    accounts = []
    with open('accounts_soundcloud.txt', 'r') as f:
        for i, ln in enumerate(f, start=1):
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            if ':' in ln:
                u, p = ln.split(':', 1)
                accounts.append((u.strip(), p.strip()))
            else:
                print(Colors.red, Center.XCenter(f"Skipping invalid account line {i}: {ln}"))

    if not accounts:
        print(Colors.red, "No valid accounts found in accounts.txt")
        return

    # ── Load proxies ───────────────────────────────────────────────────────
    use_proxy = input(Colorate.Vertical(Colors.green_to_blue, "Do you want to use proxies? (y/n): ")).strip().lower()
    proxies = None
    if use_proxy == 'y':
        proxy_file = Path('proxy.txt')
        proxies = []
        if proxy_file.exists():
            for line in proxy_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(':')
                if len(parts) == 4:
                    h, p, u, pw = parts
                    proxies.append({'host': h, 'port': p, 'user': u, 'pass': pw})
                elif len(parts) == 2:
                    h, p = parts
                    proxies.append({'host': h, 'port': p, 'user': None, 'pass': None})
        if not proxies:
            print(Colors.red, Center.XCenter("No valid proxies in proxy.txt — continuing without proxy"))
            proxies = None

    # ── Target URL ─────────────────────────────────────────────────────────
    sc_url  = input(Colorate.Vertical(Colors.green_to_blue,
                    "Enter a SoundCloud URL (track, playlist, or artist): ")).strip()
    url_type = detect_sc_url_type(sc_url)
    type_labels = {
        'track':    'Single track  — repeat & loop',
        'playlist': 'Playlist      — play through, loop',
        'artist':   'Artist        — shuffle all tracks',
        'album':    'Album         — play through, loop',
    }
    print(Colors.yellow, Center.XCenter(f"Mode: {type_labels.get(url_type, url_type)}"))
    print("")

    debug_mode = input(Colorate.Vertical(Colors.green_to_blue,
                       "Enable headed/debug mode? Shows browser windows (y/n): ")
                       ).strip().lower() == 'y'
    if debug_mode:
        print(Colors.yellow, Center.XCenter("Debug mode ON — browser windows will be visible"))
    else:
        print(Colors.green,  Center.XCenter("Headless mode — browsers will run in background"))

    # ── Launch one browser per account ────────────────────────────────────
    drivers = []

    for acct_idx, (username, password) in enumerate(accounts):
        random_ua   = random.choice(user_agents)
        random_lang = random.choice(supported_languages)

        opts = webdriver.ChromeOptions()
        opts.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
        opts.add_experimental_option('useAutomationExtension', False)
        opts.add_argument('--disable-blink-features=AutomationControlled')
        opts.add_argument('--disable-logging')
        opts.add_argument('--log-level=3')
        opts.add_argument('--disable-infobars')
        opts.add_argument('--window-size=1366,768')
        opts.add_argument(f'--user-agent={random_ua}')
        opts.add_argument(f'--lang={random_lang}')
        opts.add_argument('--mute-audio')
        opts.add_argument('--disable-dev-shm-usage')
        if not debug_mode:
            opts.add_argument('--headless=new')

        # Proxy
        if proxies:
            proxy = proxies[acct_idx % len(proxies)]
            if proxy.get('user') and proxy.get('pass'):
                plugin_file = Path(tempfile.gettempdir()) / f"sc_proxy_{acct_idx}.zip"
                try:
                    create_proxy_auth_extension(
                        proxy['host'], proxy['port'], proxy['user'], proxy['pass'], str(plugin_file)
                    )
                    opts.add_extension(str(plugin_file))
                    print(Colors.yellow, f"Using authenticated proxy {proxy['host']}:{proxy['port']}")
                except Exception as e:
                    print(Colors.red, f"Proxy extension failed, skipping: {e}")
            else:
                opts.add_argument(f"--proxy-server=http://{proxy['host']}:{proxy['port']}")
                print(Colors.yellow, f"Using proxy {proxy['host']}:{proxy['port']}")

        driver = webdriver.Chrome(options=opts)
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Google Inc. (Intel)",
            renderer="ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
            fix_hairline=True,
        )

        try:
            login_soundcloud(driver, username, password, acct_idx)

            driver.get(sc_url)
            driver.maximize_window()

            # Wait for SoundCloud page content
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR,
                        ".l-container, #app, .sc-artwork, .playableTile, .soundTitle"))
                )
            except Exception:
                time.sleep(10)

            dismiss_overlays(driver)
            time.sleep(1)
            click_play_sc(driver)
            time.sleep(3)
            enable_sc_repeat(driver)

            print(Colors.green,
                  f"[{_ts()}] [{username.split('@')[0]}] Listening started on SoundCloud.")

        except Exception as e:
            print(Colors.red, f"Error starting {username}: {str(e)}")
            try:
                driver.quit()
            except Exception:
                pass
            continue

        set_random_timezone(driver)
        set_fake_geolocation(driver)
        drivers.append((driver, username))
        time.sleep(5)

    if not drivers:
        print(Colors.red, "No accounts successfully started.")
        return

    print(Colors.blue, Center.XCenter(
        f"All {len(drivers)} account(s) running. "
        f"Skip chance: {int(SKIP_CHANCE*100)}%  |  Skip window: {SKIP_AFTER_MIN}-{SKIP_AFTER_MAX}s"
    ))
    print(Colors.blue, Center.XCenter("Press Ctrl+C to stop."))

    threads = []
    for drv, uname in drivers:
        session_secs = random.randint(SESSION_MIN_SECS, SESSION_MAX_SECS)
        session_end  = time.time() + session_secs
        sess_h, sess_m = divmod(session_secs // 60, 60)
        print(Colors.cyan, Center.XCenter(f"[{uname}] Session length: {sess_h}h {sess_m}m"))
        t = threading.Thread(
            target=playback_loop_sc,
            args=(drv, uname, sc_url, session_end),
            daemon=True,
        )
        t.start()
        threads.append(t)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(Colors.yellow, "\nStopping — closing browsers…")
        for drv, _ in drivers:
            try:
                drv.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
