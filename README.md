# Spotify & SoundCloud Streaming Bot

Python bots that automate song plays on Spotify and SoundCloud using real Chrome browser sessions with stealth anti-detection.

---

## Features

- **Multi-account support** — separate account files per platform
- **Proxy support** — authenticated (`host:port:user:pass`) and unauthenticated (`host:port`) proxies via `proxy.txt`
- **Stealth mode** — `selenium-stealth` + up-to-date Chrome user agents to avoid bot detection
- **Smart playback** — random skip logic (40% chance, 40-60s), session timers (30min-4hrs), genre wandering
- **Priority artist** — modern_monster gets 70% pull during all wander/related navigation
- **Full login flow** — handles two-step login, challenge pages, OTP, and status confirmation (Spotify); captcha fallback prompt (SoundCloud)
- **Debug / headed mode** — optional visible browser windows for troubleshooting
- **Rich logging** — timestamped console output with track name, artist, skip timing, and session info

---

## Requirements

- Python 3.10+ (tested on 3.13)
- Google Chrome (recent version)

---

## Installation

```bat
py -3 -m pip install -r requirements.txt
```

> ChromeDriver is managed automatically by Selenium Manager — no manual download needed.

---

## Setup

### `accounts_spotify.txt`
Spotify accounts — one per line in `email:password` format:
```
user1@example.com:password1
user2@example.com:password2
```

### `accounts_soundcloud.txt`
SoundCloud accounts — same format:
```
user1@example.com:password1
user2@example.com:password2
```

Lines starting with `#` are ignored in both files.

### `proxy.txt`
One proxy per line. Shared by both bots.
```
# Authenticated proxy
host:port:username:password

# Unauthenticated proxy
host:port
```

---

## Usage

```bat
run.bat
```

Choose bot at the menu:
```
Which bot do you want to run?
  1) Spotify Streaming Bot
  2) SoundCloud Streaming Bot
```

Or run directly:
```bat
py -3 spotifystreambot.py
py -3 soundcloudbot.py
```

You will be prompted for:
1. Whether to use proxies (`y/n`)
2. The URL to stream (track, album, or artist/profile)
3. Whether to show browser windows for debugging (`y/n`)

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `python` not found | Use `py -3` — the `python` command may be a Microsoft Store stub |
| ChromeDriver version mismatch | Selenium Manager handles this automatically; delete any old `chromedriver.exe` |
| Spotify login challenge / OTP | Bot attempts password login on challenge page automatically; OTP prompted in terminal if needed |
| SoundCloud captcha | Bot pauses and asks you to complete it in the browser window |
| Play button not found | Bot saves a debug HTML to `%TEMP%\sc_play_fail.html` or `spotify_play_fail.html` for inspection |
