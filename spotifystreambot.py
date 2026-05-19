from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium_stealth import stealth

import requests
import random
import pytz
import time
import os
import keyboard
import threading
from colorama import Fore
from pystyle import Center, Colors, Colorate
import zipfile
import json
import tempfile
from pathlib import Path

os.system("title Spotify Streaming Bot")

def check_for_updates():
    return True

def print_announcement():
    return None

supported_timezones = pytz.all_timezones

# ── URL / playback helpers ────────────────────────────────────────────────────

def detect_url_type(url):
    """Return 'track', 'album', or 'artist' based on the Spotify URL."""
    if '/track/' in url:
        return 'track'
    elif '/album/' in url:
        return 'album'
    elif '/artist/' in url:
        return 'artist'
    return 'track'  # safe fallback


def dismiss_overlays(driver):
    """
    Dismiss any Spotify overlays / banners that sit in front of the play button.
    Covers:
      • "Open in Desktop App" / smart-app-banner close button
      • "Get the App" preview bar dismiss
      • Generic modal close buttons
      • Cookie / consent banners
    Silently ignores anything that isn't present.
    """
    dismiss_selectors = [
        # Smart-app / preview bar dismiss
        "button[data-testid='preview-bar-dismiss-button']",
        "button[aria-label='Dismiss']",
        "button[aria-label='Close']",
        # "Open in app" modal close
        "[data-testid='modal-close-button']",
        # Cookies / consent
        "button#onetrust-accept-btn-handler",
        "button[data-testid='cookie-policy-banner-accept']",
        # Generic last-resort: any visible ×/close button in an overlay
        "div[role='dialog'] button[aria-label='Close']",
        "div[role='dialog'] button[aria-label='close']",
    ]
    for sel in dismiss_selectors:
        try:
            btn = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            btn.click()
            time.sleep(0.4)
        except Exception:
            pass
    # Also try pressing Escape once to close any keyboard-dismissable overlay
    try:
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
        time.sleep(0.3)
    except Exception:
        pass


def click_play(driver):
    """Click the primary play button on any Spotify page (track / album / artist)."""
    selectors = [
        # Page-level play button (artist / album hero)
        (By.CSS_SELECTOR, "button[data-testid='play-button']"),
        # Player bar play/pause (already playing context)
        (By.CSS_SELECTOR, "button[data-testid='control-button-playpause']"),
        # Generic aria-label fallbacks
        (By.XPATH, "//button[@aria-label='Play']"),
        (By.XPATH, "//button[starts-with(@aria-label,'Play')]"),
        (By.XPATH, "//button[contains(@aria-label,'Play')]"),
        # Tracklist first-row play
        (By.CSS_SELECTOR, "div[data-testid='tracklist-row'] button[aria-label]"),
    ]
    for by, sel in selectors:
        try:
            btn = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((by, sel)))
            btn.click()
            return
        except Exception:
            pass

    # Last resort: Space bar toggles play/pause on the Spotify web player
    try:
        from selenium.webdriver.common.keys import Keys
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.SPACE)
        return
    except Exception:
        pass

    # Save page for debugging before raising
    try:
        debug_file = Path(tempfile.gettempdir()) / "spotify_play_fail.html"
        debug_file.write_text(driver.page_source, encoding='utf-8')
    except Exception:
        pass
    raise NoSuchElementException(
        "Could not find a play button on the page — page saved to spotify_play_fail.html"
    )


def set_shuffle(driver, enable=True):
    """Enable or disable the shuffle control in the player bar."""
    try:
        btn = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='control-button-shuffle']"))
        )
        currently_on = (btn.get_attribute('aria-checked') or '').lower() == 'true'
        if enable != currently_on:
            btn.click()
            time.sleep(0.4)
    except Exception:
        pass


def set_repeat(driver, mode):
    """
    Set the player repeat mode.
      mode='off'     — no repeat
      mode='context' — repeat album / artist (Repeat All)
      mode='track'   — repeat current track (Repeat One)

    Spotify cycles:  off → context → track → off
    aria-label when in state:
      off     → "Enable repeat"
      context → "Enable repeat one track"   (next click goes to 'track')
      track   → "Disable repeat"            (next click goes to 'off')
    """
    for _ in range(4):
        try:
            btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='control-button-repeat']"))
            )
            label = (btn.get_attribute('aria-label') or '').lower()
            if 'disable' in label:
                current = 'track'
            elif 'one' in label:
                current = 'context'
            else:
                current = 'off'
            if current == mode:
                break
            btn.click()
            time.sleep(0.5)
        except Exception:
            break



def get_current_track(driver):
    """Return the now-playing track name, or None if it can't be read."""
    selectors = [
        (By.CSS_SELECTOR, "div[data-testid='now-playing-widget'] a[data-testid='context-item-link']"),
        (By.CSS_SELECTOR, "a[data-testid='context-item-link']"),
        (By.CSS_SELECTOR, "div[data-testid='tracklist-row--active'] a"),
    ]
    for by, sel in selectors:
        try:
            el = driver.find_element(by, sel)
            return el.text.strip()
        except Exception:
            pass
    return None


def get_current_track_info(driver):
    """
    Return (track_name, artist_name) from the now-playing footer bar.
    Falls back to (track_name, None) or (None, None) if elements aren't found.
    """
    track = get_current_track(driver)

    artist = None
    artist_selectors = [
        "div[data-testid='now-playing-widget'] a[data-testid='context-item-info-artist']",
        "div[data-testid='now-playing-widget'] span[data-testid='context-item-info-artist']",
        "a[data-testid='context-item-info-artist']",
        "span[data-testid='context-item-info-artist']",
        # fallback: any artist link in the now-playing widget
        "div[data-testid='now-playing-widget'] a[href*='/artist/']",
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

    return track, artist


def _ts():
    """Return a short HH:MM:SS timestamp string for log lines."""
    return time.strftime('%H:%M:%S')


def click_next(driver):
    """Click the skip-forward (next track) button in the player bar."""
    for by, sel in [
        (By.CSS_SELECTOR, "button[data-testid='control-button-skip-forward']"),
        (By.XPATH,        "//button[@aria-label='Next']"),
        (By.XPATH,        "//button[contains(@aria-label,'Next')]"),
    ]:
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((by, sel)))
            btn.click()
            return True
        except Exception:
            pass
    return False


# Skip probability and timing constants
SKIP_CHANCE     = 0.40   # 40 % of tracks get skipped
SKIP_AFTER_MIN  = 40     # seconds — earliest skip
SKIP_AFTER_MAX  = 60     # seconds — latest skip
TRACK_WAIT_MAX  = 360    # seconds — max wait for a new track to start before giving up

# Session duration per account
SESSION_MIN_SECS = 30 * 60        # 30 minutes
SESSION_MAX_SECS = 4  * 60 * 60   # 4 hours

# Genre-wander: how many songs between each navigation to related/genre content
WANDER_EVERY_MIN = 4
WANDER_EVERY_MAX = 9

# Priority artist — when scraping related-artist links or picking from GENRE_URLS,
# the bot will choose this artist with PRIORITY_ARTIST_WEIGHT probability (0.70 = 70 %)
# whenever at least one of their links is in the candidate pool.
PRIORITY_ARTIST_ID     = "5HPfckmGMYRbxsdBqSLL9B"   # modern_monster
PRIORITY_ARTIST_URL    = f"https://open.spotify.com/artist/{PRIORITY_ARTIST_ID}"
PRIORITY_ARTIST_WEIGHT = 0.70   # 70 % chance of picking modern_monster when present

# Metal / rock / alt-rock artists to wander into (fallback list).
# Replace any ID that turns out to be wrong — artist IDs are the path segment
# after /artist/ in any Spotify URL.
GENRE_URLS = [
    PRIORITY_ARTIST_URL,                                         # modern_monster  ← priority
    "https://open.spotify.com/artist/2ye2Wgw4gimLv2eAKyk1NB",  # Metallica
    "https://open.spotify.com/artist/711MCceyCBcFnzjGY4Q7Un",  # AC/DC
    "https://open.spotify.com/artist/6olE6TJLqED3rqDCT0FyPh",  # Nirvana
    "https://open.spotify.com/artist/7Ln80lUS6He07XvHI8qqHH",  # Arctic Monkeys
    "https://open.spotify.com/artist/4Z8W4fKeB5YxbusRsdQVPb",  # Radiohead
    "https://open.spotify.com/artist/36QJpDe2go2KgaRleHCDTp",  # Led Zeppelin
    "https://open.spotify.com/artist/5M52tdBnJaKSvOpJGz8mfZ",  # Black Sabbath
    "https://open.spotify.com/artist/6FBDaR13swtiWwGhX1WQsP",  # Soundgarden
    "https://open.spotify.com/artist/4UXqAaa6dQYAk18Lv7PEgX",  # Alice in Chains
    "https://open.spotify.com/artist/0L8ExT028jH3ddEcZwqJJ5",  # Red Hot Chili Peppers
    "https://open.spotify.com/artist/6Ghvu1VvMGScGpOUvgLyPI",  # System of a Down
    "https://open.spotify.com/artist/5eAWCfyUhZtHHtBdNk56l1",  # Rage Against the Machine
    "https://open.spotify.com/artist/3RNrq3jvMZxD9ZyoOZbQOD",  # Foo Fighters
    "https://open.spotify.com/artist/7bDLHytU8vohbiWbePGriy",  # Slipknot
    "https://open.spotify.com/artist/2aaLAng2L2aWD2FClzwiep",  # Disturbed
    "https://open.spotify.com/artist/3TOqt5oJwL9BE2NG9MEwDa",  # Avenged Sevenfold
    "https://open.spotify.com/artist/4tZwfgrHOc3mvqYlEYSvVi",  # Deftones
    "https://open.spotify.com/artist/6DEXwkSBj8BTMv4IXy0iFE",  # Tool
    "https://open.spotify.com/artist/73sIBHcqh3Z3NyqHKZ7FOL",  # Pantera
    "https://open.spotify.com/artist/3YcBF2ttyueytpXtEzn1Za",  # The Black Keys
    "https://open.spotify.com/artist/0epOFNiUfyON9EYx7Tpr6V",  # Twenty One Pilots
    "https://open.spotify.com/artist/5INjqkS1o8h1imAzPqGZnR",  # Imagine Dragons
    "https://open.spotify.com/artist/4UgQ3EFa8sp5argyYBaFSb",  # Papa Roach
    "https://open.spotify.com/artist/3WrFJ7ztbogyGnTHbHJFl2",  # The Beatles
]


def _weighted_pick(candidates):
    """
    Pick a URL from candidates.
    If any URL contains PRIORITY_ARTIST_ID (modern_monster), there is a
    PRIORITY_ARTIST_WEIGHT chance of returning one of those priority URLs.
    Otherwise a regular random choice is made from the full pool.
    """
    priority = [u for u in candidates if PRIORITY_ARTIST_ID in u]
    others   = [u for u in candidates if PRIORITY_ARTIST_ID not in u]

    if priority and random.random() < PRIORITY_ARTIST_WEIGHT:
        return random.choice(priority)
    return random.choice(others) if others else random.choice(priority)


def playback_loop(driver, username, url_type, origin_url, session_end_time):
    """
    Runs in a background thread for one browser session.

    Each song cycle:
      • Checks if the session lifetime has expired — if so, closes the browser and exits.
      • 40 % chance: skips the song at a random 40-60 s mark.
      • Every 4-9 songs: navigates to a related artist ("Fans Also Like") or a
        fallback metal/rock/alt-rock artist from GENRE_URLS, then resumes shuffle play.
      • Waits for the track title to actually change before starting the next cycle.
    """
    # Short display name for log lines (strip domain from email)
    acct = username.split('@')[0]

    song_number        = 0
    songs_since_wander = 0
    next_wander_at     = random.randint(WANDER_EVERY_MIN, WANDER_EVERY_MAX)

    while True:
        try:
            # ── Session timeout ────────────────────────────────────────────
            if time.time() >= session_end_time:
                remaining = 0
                print(Colors.cyan,
                      f"[{_ts()}] [{acct}] Session time reached — closing browser.")
                try:
                    driver.quit()
                except Exception:
                    pass
                return

            song_number        += 1
            songs_since_wander += 1

            track_before, artist_before = get_current_track_info(driver)
            will_skip = random.random() < SKIP_CHANCE
            wait_time = random.randint(SKIP_AFTER_MIN, SKIP_AFTER_MAX)

            # ── Log song start ─────────────────────────────────────────────
            track_label  = f'"{track_before}"'  if track_before else '(unknown track)'
            artist_label = f' by {artist_before}' if artist_before else ''
            fate_label   = f'SKIP at {wait_time}s' if will_skip else f'playing ~{wait_time}s+'

            print(Colors.green,
                  f"[{_ts()}] [{acct}] #{song_number:>3} ▶ {track_label}{artist_label}  [{fate_label}]")

            # ── 15 % chance: like / save the current track ─────────────────
            if random.random() < 0.15:
                try:
                    like_btn = None
                    for by, sel in [
                        # Now-playing bar "Save to Your Liked Songs" heart button
                        (By.CSS_SELECTOR, "button[data-testid='add-button']"),
                        (By.CSS_SELECTOR, "button[aria-label='Save to Your Liked Songs']"),
                        (By.XPATH, "//button[contains(@aria-label,'Save to') and contains(@aria-label,'Liked')]"),
                        (By.XPATH, "//button[@aria-label='Add to Liked Songs']"),
                        # Encore heart icon in the now-playing widget
                        (By.CSS_SELECTOR, "div[data-testid='now-playing-widget'] button[data-encore-id='buttonTertiary']"),
                    ]:
                        try:
                            candidate = driver.find_element(by, sel)
                            if candidate.is_displayed():
                                # Only click if NOT already saved (aria-checked=false or aria-label says Save)
                                label = (candidate.get_attribute('aria-label') or '').lower()
                                checked = (candidate.get_attribute('aria-checked') or '').lower()
                                if checked == 'true' or 'remove' in label or 'saved' in label:
                                    break  # already liked — skip
                                like_btn = candidate
                                break
                        except Exception:
                            pass
                    if like_btn:
                        like_btn.click()
                        print(Colors.green,
                              f"[{_ts()}] [{acct}] #{song_number:>3} ♥  Liked {track_label}")
                except Exception:
                    pass  # silently ignore any like failures

            # ── Wait, then skip if decided ─────────────────────────────────
            time.sleep(wait_time)

            if will_skip:
                if click_next(driver):
                    print(Colors.yellow,
                          f"[{_ts()}] [{acct}] #{song_number:>3} ✂ Skipped at {wait_time}s")
                else:
                    print(Colors.yellow,
                          f"[{_ts()}] [{acct}] #{song_number:>3} ✂ Skip failed — letting Spotify advance")

            # ── Wait for the track to actually change ───────────────────────
            waited = 0
            while waited < TRACK_WAIT_MAX:
                if time.time() >= session_end_time:
                    break
                time.sleep(2)
                waited += 2
                track_now, artist_now = get_current_track_info(driver)
                if track_now and track_now != track_before:
                    new_label   = f'"{track_now}"'
                    new_artist  = f' by {artist_now}' if artist_now else ''
                    print(Colors.green,
                          f"[{_ts()}] [{acct}] #{song_number:>3} ↪ Now playing: {new_label}{new_artist}")
                    break

            # ── Genre / recommended wander ──────────────────────────────────
            if songs_since_wander >= next_wander_at:
                songs_since_wander = 0
                next_wander_at     = random.randint(WANDER_EVERY_MIN, WANDER_EVERY_MAX)
                print(Colors.cyan,
                      f"[{_ts()}] [{acct}] 🔀 Wandering to related/genre content "
                      f"(next in {next_wander_at} songs)…")
                new_ctx = navigate_to_recommended(driver, origin_url)
                if new_ctx:
                    # Try to get the artist name from the player after navigation
                    time.sleep(3)
                    _, new_ctx_artist = get_current_track_info(driver)
                    ctx_label = new_ctx_artist if new_ctx_artist else new_ctx
                    print(Colors.cyan,
                          f"[{_ts()}] [{acct}] 🔀 Now browsing: {ctx_label}")
                    set_shuffle(driver, True)
                    set_repeat(driver, 'context')
                else:
                    print(Colors.yellow,
                          f"[{_ts()}] [{acct}] 🔀 Wander failed — returning to origin URL.")
                    driver.get(origin_url)
                    time.sleep(4)
                    click_play(driver)

        except Exception as e:
            err = str(e).lower()
            if 'invalid session' in err or 'no such window' in err or 'target window already closed' in err:
                print(Colors.red,
                      f"[{_ts()}] [{acct}] Browser session ended — playback loop stopped.")
                break
            print(Colors.red,
                  f"[{_ts()}] [{acct}] Transient error (retrying): {str(e)[:120]}")
            time.sleep(5)


def get_artist_url_from_player(driver):
    """
    Read the current artist's Spotify URL from the now-playing footer bar.
    Returns the clean URL (no query params) or None.
    """
    for by, sel in [
        (By.CSS_SELECTOR, "div[data-testid='now-playing-widget'] a[href*='/artist/']"),
        (By.CSS_SELECTOR, "div[data-testid='context-item-info-artist'] a[href*='/artist/']"),
        (By.CSS_SELECTOR, "footer a[href*='/artist/']"),
        (By.XPATH,        "//div[contains(@data-testid,'now-playing')]//a[contains(@href,'/artist/')]"),
    ]:
        try:
            el = driver.find_element(by, sel)
            href = (el.get_attribute('href') or '').split('?')[0]
            if '/artist/' in href:
                return href
        except Exception:
            pass
    return None


def navigate_to_recommended(driver, origin_url):
    """
    Navigate to a related artist or genre artist to simulate organic listening.

    Strategy:
      1. Get the current artist page from the now-playing bar.
      2. Navigate there and scrape all /artist/ hrefs that appear under
         sections like "Fans also like" (any on-page artist link is a valid signal).
      3. Pick one via _weighted_pick — modern_monster gets a 70 % pull when present.
      4. If any step fails → pick from GENRE_URLS via _weighted_pick (modern_monster
         is in the list so it gets the same 70 % pull from the fallback pool too).

    Returns the URL navigated to, or None if everything failed.
    """
    try:
        artist_url = get_artist_url_from_player(driver)
        if artist_url:
            driver.get(artist_url)
            time.sleep(5)   # let the related-artist carousel render

            current_clean = driver.current_url.split('?')[0]

            # Collect all on-page /artist/ links that are NOT the artist we just loaded.
            # Always include PRIORITY_ARTIST_URL in the pool if it isn't already there,
            # so modern_monster can be chosen even when Spotify doesn't surface them.
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/artist/']")
            seen, candidates = set(), []
            for a in links:
                href = (a.get_attribute('href') or '').split('?')[0]
                if '/artist/' in href and href != current_clean and href not in seen:
                    seen.add(href)
                    candidates.append(href)

            # Inject priority artist if not already found on the page
            if PRIORITY_ARTIST_URL not in seen and PRIORITY_ARTIST_URL != current_clean:
                candidates.append(PRIORITY_ARTIST_URL)

            if candidates:
                chosen = _weighted_pick(candidates)
                driver.get(chosen)
                time.sleep(4)
                dismiss_overlays(driver)
                click_play(driver)
                return chosen
    except Exception:
        pass

    # ── Fallback: hardcoded genre list (modern_monster included) ────────────
    try:
        pool = [u for u in GENRE_URLS if u != origin_url]
        chosen = _weighted_pick(pool if pool else GENRE_URLS)
        driver.get(chosen)
        time.sleep(4)
        dismiss_overlays(driver)
        click_play(driver)
        return chosen
    except Exception:
        pass

    return None


# ─────────────────────────────────────────────────────────────────────────────

def set_random_timezone(driver):
    random_timezone = random.choice(supported_timezones)
    driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": random_timezone})

def set_fake_geolocation(driver, latitude, longitude):
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "accuracy": 100
    }
    driver.execute_cdp_cmd("Emulation.setGeolocationOverride", params)

def main():
    if not check_for_updates():
        return
    print(Colorate.Vertical(Colors.white_to_green, Center.XCenter("""

                        ███████╗██████╗  ██████╗ ████████╗██╗███████╗██╗   ██╗
                        ██╔════╝██╔══██╗██╔═══██╗╚══██╔══╝██║██╔════╝╚██╗ ██╔╝
                        ███████╗██████╔╝██║   ██║   ██║   ██║█████╗   ╚████╔╝ 
                        ╚════██║██╔═══╝ ██║   ██║   ██║   ██║██╔══╝    ╚██╔╝  
                        ███████║██║     ╚██████╔╝   ██║   ██║██║        ██║   
                        ╚══════╝╚═╝      ╚═════╝    ╚═╝   ╚═╝╚═╝        ╚═╝   
                              Spotify Streaming Bot — stealth edition
""")))
    print("")

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

    driver_path = 'chromedriver.exe'

    # Read accounts and parse into (username, password) pairs. Skip empty or invalid lines.
    raw_accounts = []
    with open('accounts_spotify.txt', 'r') as file:
        for ln in file:
            ln = ln.strip()
            if ln:
                raw_accounts.append(ln)

    accounts = []
    for i, ln in enumerate(raw_accounts, start=1):
        if ln.startswith('#'):
            continue
        if ':' in ln:
            u, p = ln.split(':', 1)
            accounts.append((u, p))
        else:
            print(Colors.red, Center.XCenter(f"Skipping invalid account line {i}: {ln}"))

    use_proxy = input(Colorate.Vertical(Colors.green_to_blue, "Do you want to use proxies? (y/n):"))

    if use_proxy.lower() == 'y':
        # Try to load proxies from proxy.txt. Format per line: host:port:user:pass or host:port
        proxy_file = Path('proxy.txt')
        proxies = []
        if proxy_file.exists():
            for line in proxy_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(':')
                if len(parts) == 4:
                    host, port, user, pw = parts
                    proxies.append({'host': host, 'port': port, 'user': user, 'pass': pw})
                elif len(parts) == 2:
                    host, port = parts
                    proxies.append({'host': host, 'port': port, 'user': None, 'pass': None})
                else:
                    # fallback: try to interpret first two as host:port
                    host = parts[0]
                    port = parts[1] if len(parts) > 1 else ''
                    proxies.append({'host': host, 'port': port, 'user': None, 'pass': None})
            if not proxies:
                print(Colors.red, Center.XCenter("No valid proxies found in proxy.txt — continuing without proxy"))
                proxies = None
        else:
            print(Colors.red, Center.XCenter("proxy.txt not found. Continuing without proxy."))
            proxies = None
        time.sleep(1)

    spotify_url = input(Colorate.Vertical(Colors.green_to_blue, "Enter a Spotify URL (track, album, or artist): ")).strip()
    url_type = detect_url_type(spotify_url)
    type_labels = {
        'track':  'Single track  — repeat one forever',
        'album':  'Album         — play start-to-finish, repeat forever',
        'artist': 'Artist        — shuffle all songs, repeat forever',
    }
    print(Colors.yellow, Center.XCenter(f"Mode: {type_labels[url_type]}"))
    print("")

    debug_mode = input(Colorate.Vertical(Colors.green_to_blue, "Enable headed/debug mode? Shows browser windows (y/n): ")).strip().lower() == 'y'
    if debug_mode:
        print(Colors.yellow, Center.XCenter("Debug mode ON — browser windows will be visible"))
    else:
        print(Colors.green, Center.XCenter("Headless mode — browsers will run in background"))

    # (no hidden browser needed — removed to avoid chromedriver headless issues)

    drivers = []

    for acct_idx, account in enumerate(accounts):
        username, password = account
        random_user_agent = random.choice(user_agents)
        random_language = random.choice(supported_languages)

        chrome_options = webdriver.ChromeOptions()
        # Hide Selenium / automation signals from Spotify's bot detection
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--disable-logging')
        chrome_options.add_argument('--log-level=3')
        chrome_options.add_argument('--disable-infobars')
        chrome_options.add_argument("--window-size=1366,768")
        chrome_options.add_argument(f"--user-agent={random_user_agent}")
        chrome_options.add_argument(f"--lang={random_language}")
        chrome_options.add_argument("--mute-audio")
        chrome_options.add_argument('--disable-dev-shm-usage')
        if not debug_mode:
            chrome_options.add_argument('--headless=new')

        # If proxies are enabled and available, assign one per account (round-robin)
        if use_proxy.lower() == 'y' and proxies:
            # pick proxy by account index
            try:
                idx = acct_idx
                proxy = proxies[idx % len(proxies)]
            except Exception:
                proxy = random.choice(proxies)

            if proxy.get('user') and proxy.get('pass'):
                # Create a small Chrome extension to handle proxy with authentication
                def create_proxy_auth_extension(proxy_host, proxy_port, proxy_user, proxy_pass, plugin_path):
                    manifest_json = {
                        "version": "1.0.0",
                        "manifest_version": 2,
                        "name": "Chrome Proxy",
                        "permissions": [
                            "proxy",
                            "tabs",
                            "unlimitedStorage",
                            "storage",
                            "<all_urls>",
                            "webRequest",
                            "webRequestBlocking"
                        ],
                        "background": {"scripts": ["background.js"]},
                        "minimum_chrome_version": "22.0.0"
                    }

                    background_js = f"""
var config = {{
  mode: "fixed_servers",
  rules: {{
    singleProxy: {{
      scheme: "http",
      host: "{proxy_host}",
      port: parseInt({proxy_port})
    }},
    bypassList: ["localhost"]
  }}
}};

chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});

function callbackFn(details) {{
  return {{authCredentials: {{username: "{proxy_user}", password: "{proxy_pass}"}}}};
}}

chrome.webRequest.onAuthRequired.addListener(
  callbackFn,
  {{urls: ["<all_urls>"]}},
  ['blocking']
);
"""

                    # write files into a zip
                    with zipfile.ZipFile(plugin_path, 'w') as zp:
                        zp.writestr('manifest.json', json.dumps(manifest_json))
                        zp.writestr('background.js', background_js)

                # create plugin file in temp directory
                plugin_file = Path(tempfile.gettempdir()) / f"proxy_auth_plugin_{len(drivers)}.zip"
                try:
                    create_proxy_auth_extension(proxy['host'], proxy['port'], proxy['user'], proxy['pass'], str(plugin_file))
                    chrome_options.add_extension(str(plugin_file))
                    print(Colors.yellow, f"Using authenticated proxy {proxy['host']}:{proxy['port']}")
                except Exception as e:
                    print(Colors.red, "Failed to create proxy extension, falling back to no-proxy:", str(e))
            else:
                # simple proxy without auth
                chrome_options.add_argument(f"--proxy-server=http://{proxy['host']}:{proxy['port']}")
                print(Colors.yellow, f"Using proxy {proxy['host']}:{proxy['port']}")

        # Use Selenium Manager to auto-download matching chromedriver
        driver = webdriver.Chrome(options=chrome_options)

        # Apply selenium-stealth to mask all automation fingerprints
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Google Inc. (Intel)",
            renderer="ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
            fix_hairline=True,
        )



        try:
            driver.get("https://accounts.spotify.com/en/login")

            # ── STEP 1: wait for the email field, click it, type email, click Continue ──
            # Spotify uses a two-step flow: email on page 1, password on page 2.
            # Do NOT look for the password field here — it does not exist yet.

            email_wait = WebDriverWait(driver, 15)
            try:
                username_input = email_wait.until(
                    EC.element_to_be_clickable((By.ID, "username"))
                )
            except Exception:
                debug_file = Path(tempfile.gettempdir()) / f"spotify_login_page_{acct_idx}.html"
                try:
                    debug_file.write_text(driver.page_source, encoding='utf-8')
                except Exception:
                    pass
                raise NoSuchElementException(
                    f"Email field (id='username') not found on login page. Page saved to {debug_file}"
                )

            username_input.click()
            username_input.clear()
            username_input.send_keys(username)

            # Click the Continue button (data-testid="login-button" on step 1)
            try:
                continue_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='login-button']"))
                )
                continue_btn.click()
            except Exception:
                username_input.send_keys('\n')

            # ── STEP 2: wait for the password field OR a challenge redirect ──
            # Spotify sometimes skips the password step entirely and goes straight
            # to challenge.spotify.com — so we must detect that here too.
            password_input = None
            otp_detected = False
            for attempt in range(15):
                # First check if Spotify already redirected us to the challenge page
                cur = driver.current_url.lower()
                if 'challenge.spotify.com' in cur or '/otc' in cur:
                    otp_detected = True
                    break

                for by, sel in [
                    (By.CSS_SELECTOR, "input[data-testid='login-password']"),
                    (By.ID, "login-password"),
                    (By.NAME, "password"),
                    (By.CSS_SELECTOR, "input[type='password']"),
                ]:
                    try:
                        password_input = WebDriverWait(driver, 2).until(
                            EC.element_to_be_clickable((by, sel))
                        )
                        break
                    except Exception:
                        pass
                if password_input:
                    break
                time.sleep(1)

            if not otp_detected and password_input is None:
                debug_file = Path(tempfile.gettempdir()) / f"spotify_login_page_{acct_idx}.html"
                try:
                    debug_file.write_text(driver.page_source, encoding='utf-8')
                except Exception:
                    pass
                raise NoSuchElementException(
                    f"Password field not found after clicking Continue. Page saved to {debug_file}"
                )

            if not otp_detected:
                password_input.clear()
                password_input.send_keys(password)

                try:
                    driver.find_element(By.CSS_SELECTOR, "button[data-testid='login-button']").click()
                except Exception:
                    password_input.send_keys('\n')

                # ── STEP 3: detect OTP after password submit ──
                for _ in range(15):
                    time.sleep(1)
                    cur = driver.current_url.lower()
                    if 'challenge.spotify.com' in cur or '/otc' in cur:
                        otp_detected = True
                        break
                    # Left accounts page without a challenge → login succeeded
                    if 'accounts.spotify.com' not in cur:
                        break

            if otp_detected:
                print(Colors.yellow, f"\n[CHALLENGE PAGE] Account: {username} — attempting 'Log in with password'…")

                # ── Try clicking "Log in with password" to skip the OTP entirely ──
                password_login_clicked = False
                for by, sel in [
                    (By.CSS_SELECTOR, "button[data-encore-id='buttonTertiary']"),
                    (By.XPATH, "//*[contains(text(),'password') and (self::button or self::a)]"),
                    (By.XPATH, "//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'password') and (self::button or self::a)]"),
                ]:
                    try:
                        btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((by, sel)))
                        btn.click()
                        password_login_clicked = True
                        print(Colors.green, "  Clicked 'Log in with password' — waiting for password field…")
                        break
                    except Exception:
                        pass

                if password_login_clicked:
                    # Wait for the password field to appear again after clicking
                    pw2_input = None
                    for _ in range(10):
                        for by, sel in [
                            (By.CSS_SELECTOR, "input[data-testid='login-password']"),
                            (By.ID, "login-password"),
                            (By.NAME, "password"),
                            (By.CSS_SELECTOR, "input[type='password']"),
                        ]:
                            try:
                                pw2_input = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((by, sel)))
                                break
                            except Exception:
                                pass
                        if pw2_input:
                            break
                        time.sleep(1)

                    if pw2_input:
                        pw2_input.clear()
                        pw2_input.send_keys(password)
                        try:
                            driver.find_element(By.CSS_SELECTOR, "button[data-testid='login-button']").click()
                        except Exception:
                            pw2_input.send_keys('\n')
                        print(Colors.green, f"  Password submitted for {username} via password-login fallback.")
                        time.sleep(4)
                        otp_detected = False  # cleared — handled via password now
                    else:
                        print(Colors.yellow, "  Password field didn't appear after clicking 'Log in with password'.")

                if otp_detected:
                    # 'Log in with password' wasn't available or didn't work — fall back to OTP prompt
                    print(Colors.yellow, "Spotify sent a 6-digit verification code to your email.")
                    print(Colors.yellow, "Check your inbox (and spam folder) then enter it below.")
                    otp_code = input(Colorate.Vertical(Colors.green_to_blue, f"  Enter 6-digit code for {username}: ")).strip()

                    # The challenge page has 6 individual digit inputs with inputmode="numeric".
                    # Find all of them and type one digit per field.
                    try:
                        digit_inputs = WebDriverWait(driver, 10).until(
                            EC.presence_of_all_elements_located(
                                (By.CSS_SELECTOR, "input[inputmode='numeric']")
                            )
                        )
                    except Exception:
                        digit_inputs = []

                    if digit_inputs and len(otp_code) == len(digit_inputs):
                        for inp, digit in zip(digit_inputs, otp_code):
                            try:
                                inp.click()
                                inp.send_keys(digit)
                            except Exception:
                                pass
                        try:
                            submit_btn = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
                            )
                            submit_btn.click()
                        except Exception:
                            try:
                                digit_inputs[-1].send_keys('\n')
                            except Exception:
                                pass
                        print(Colors.green, f"  OTP submitted for {username}. Waiting for login…")
                        time.sleep(6)
                    elif digit_inputs:
                        try:
                            digit_inputs[0].click()
                            digit_inputs[0].send_keys(otp_code)
                        except Exception:
                            pass
                        try:
                            submit_btn = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
                            )
                            submit_btn.click()
                        except Exception:
                            pass
                        print(Colors.green, f"  OTP submitted for {username}. Waiting for login…")
                        time.sleep(6)
                    else:
                        print(Colors.yellow, "  Could not find OTP input automatically.")
                        print(Colors.yellow, "  Please type the code in the browser window, then press ENTER here.")
                        input(Colorate.Vertical(Colors.green_to_blue, "  Press ENTER once OTP is done in browser: "))

            # ── STEP 4: handle the "You are logged in as X" status/confirmation page ──
            # After OTP (or sometimes after password), Spotify shows accounts.spotify.com/*/status
            # with a green confirm/login button that must be clicked before the app loads.
            time.sleep(3)
            for _ in range(10):
                cur = driver.current_url.lower()
                if '/status' in cur and 'accounts.spotify.com' in cur:
                    print(Colors.cyan, f"  [STATUS PAGE] Clicking confirm for {username}…")
                    try:
                        confirm_btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-encore-id='buttonPrimary']"))
                        )
                        confirm_btn.click()
                        time.sleep(3)
                    except Exception:
                        try:
                            # Fallback: any primary/submit button
                            confirm_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], button.primary")
                            confirm_btn.click()
                            time.sleep(3)
                        except Exception:
                            pass
                    break
                # Already left accounts — no status page
                if 'accounts.spotify.com' not in cur:
                    break
                time.sleep(1)

            driver.get(spotify_url)
            driver.maximize_window()

            # Wait for the main Spotify content to be present before doing anything
            try:
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "main, #main, div[data-testid]"))
                )
            except Exception:
                time.sleep(10)   # fallback flat wait if selector never appears

            # Dismiss the "Open in Desktop App" banner, cookie consent, and any modals
            dismiss_overlays(driver)
            time.sleep(1)

            if url_type == 'album':
                # For albums, click the album hero play button.
                # Note: image-blocking changes page rendering, so we must NOT rely on
                # selectors scoped inside image/art containers. Use data-testid and
                # aria-label attributes which are always present regardless of images.
                #
                # Strategy: wait for the page's main content section, then find the
                # first play button that is NOT inside the player transport bar
                # (the transport bar uses data-testid='control-button-playpause').
                album_play_clicked = False

                # Wait a bit longer for the SPA to fully render the action bar
                time.sleep(2)

                album_play_selectors = [
                    # Action bar row sits directly below the header art — always rendered
                    (By.CSS_SELECTOR, "div[data-testid='action-bar-row'] button[data-testid='play-button']"),
                    # Generic page-level play button scoped to main content (not the transport bar)
                    (By.CSS_SELECTOR, "main button[data-testid='play-button']"),
                    # aria-label contains "Play" and "album" — set by Spotify on the hero button
                    (By.XPATH, "//button[contains(@aria-label,'Play') and contains(@aria-label,'album')]"),
                    # aria-label is exactly "Play" but scoped outside the player footer
                    (By.XPATH, "//main//button[@aria-label='Play']"),
                    # Any button whose aria-label starts with "Play " (catches "Play album", "Play Cast(mending)", etc.)
                    (By.XPATH, "//main//button[starts-with(@aria-label,'Play')]"),
                    # Broadest safe fallback: any play-button data-testid on the whole page
                    (By.CSS_SELECTOR, "button[data-testid='play-button']"),
                ]
                for by, sel in album_play_selectors:
                    try:
                        btn = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((by, sel)))
                        # Extra guard: skip if this is the transport bar play/pause button
                        testid = btn.get_attribute('data-testid') or ''
                        if 'control-button-playpause' in testid:
                            continue
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                        time.sleep(0.3)
                        try:
                            btn.click()
                        except Exception:
                            driver.execute_script("arguments[0].click();", btn)
                        album_play_clicked = True
                        print(Colors.cyan, f"  [{username}] Album play button clicked (selector: {sel}).")
                        break
                    except Exception:
                        pass
                if not album_play_clicked:
                    print(Colors.yellow, f"  [{username}] Album hero play button not found — falling back to generic click_play().")
                    click_play(driver)
            else:
                click_play(driver)

            time.sleep(3)

            # Configure shuffle / repeat based on what kind of URL was given
            if url_type == 'artist':
                set_shuffle(driver, True)
                set_repeat(driver, 'context')
                mode_msg = "Artist mode — shuffle ON, repeat all"
            elif url_type == 'album':
                set_shuffle(driver, False)
                set_repeat(driver, 'context')
                mode_msg = "Album mode — repeat all (start-to-finish loop)"
            else:
                set_repeat(driver, 'track')
                mode_msg = "Track mode — repeat one"

            print(Colors.green, f"[{username}] Listening started. {mode_msg}.")

        except Exception as e:
            print(Colors.red, "An error occurred in the bot system:", str(e))
            # Ensure we close the broken driver and move to next account
            try:
                driver.quit()
            except Exception:
                pass
            continue

        set_random_timezone(driver)
        latitude = random.uniform(-90, 90)
        longitude = random.uniform(-180, 180)
        set_fake_geolocation(driver, latitude, longitude)

        drivers.append((driver, username))

        # Stagger logins — random delay between accounts to avoid simultaneous
        # login bursts that look like bot activity to Spotify's systems.
        # Skip the delay after the last account.
        if acct_idx < len(accounts) - 1:
            login_delay = random.randint(10, 90)
            print(Colors.cyan,
                  f"  Waiting {login_delay}s before next account login…")
            time.sleep(login_delay)

    if not drivers:
        print(Colors.red, "No accounts successfully started.")
        return

    print(Colors.blue, Center.XCenter(
        f"All {len(drivers)} account(s) running. "
        f"Skip chance: {int(SKIP_CHANCE*100)}%  |  Skip window: {SKIP_AFTER_MIN}-{SKIP_AFTER_MAX}s"
    ))
    print(Colors.blue, Center.XCenter("Press Ctrl+C to stop."))

    # Launch one playback-loop thread per account
    threads = []
    for drv, uname in drivers:
        session_secs = random.randint(SESSION_MIN_SECS, SESSION_MAX_SECS)
        session_end  = time.time() + session_secs
        sess_h, sess_m = divmod(session_secs // 60, 60)
        print(Colors.cyan, Center.XCenter(
            f"[{uname}] Session length: {sess_h}h {sess_m}m"
        ))
        t = threading.Thread(
            target=playback_loop,
            args=(drv, uname, url_type, spotify_url, session_end),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # Keep the main thread alive until the user presses Ctrl+C
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

# ==========================================
# Copyright 2023 Kichi779

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# ==========================================

