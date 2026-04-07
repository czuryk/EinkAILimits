#!/usr/bin/env python3
"""
Claude Code Usage Monitor for Headless Ubuntu Server
=====================================================

Fetches 5-hour session and 7-day weekly usage limits via OAuth.
Designed to run continuously, updating every 1 minute.

First run (no credentials):
  - Generates an OAuth authorization URL
  - You open the URL in any browser, log in, copy the redirect URL back
  - Script exchanges the code for tokens and saves them

Subsequent runs:
  - Reads saved credentials
  - Runs in an infinite loop updating limits every minute
  - Refreshes access token if expired (or about to expire)
  - Saves to usage.json

Requirements:
  pip install requests
"""

import json
import sys
import os
import hashlib
import base64
import secrets
import time
import logging
from pathlib import Path
from datetime import datetime, timezone

import requests

# ── Configuration ─────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
CREDENTIALS_FILE = SCRIPT_DIR / "credentials.json"
USAGE_FILE = SCRIPT_DIR / "usage.json"
PKCE_STATE_FILE = SCRIPT_DIR / ".pkce_pending.json"
LOG_FILE = SCRIPT_DIR / "monitor.log"

# Anthropic OAuth (same client_id as Claude Code CLI)
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
REDIRECT_URI = "http://localhost:18924/callback"  # placeholder, we'll paste the URL manually
SCOPES = "user:inference user:profile"

# Refresh access token 10 minutes before expiry
REFRESH_BUFFER_SEC = 600

# User-Agent to mimic Claude Code CLI
USER_AGENT = "claude-code/2.0.32"
# ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── PKCE helpers ──────────────────────────────────────────────────
def generate_pkce():
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state():
    return secrets.token_urlsafe(32)


# ── Credential helpers ───────────────────────────────────────────
def load_credentials() -> dict | None:
    if CREDENTIALS_FILE.exists():
        try:
            return json.loads(CREDENTIALS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_credentials(creds: dict):
    CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    os.chmod(CREDENTIALS_FILE, 0o600)
    log.info("Credentials saved.")


def token_is_expired(creds: dict) -> bool:
    expires_at = creds.get("expiresAt", 0)
    # expiresAt is in milliseconds
    now_ms = int(time.time() * 1000)
    return now_ms >= (expires_at - REFRESH_BUFFER_SEC * 1000)


# ── OAuth flows ──────────────────────────────────────────────────
def start_authorization():
    """
    Step 1 of initial login: generate auth URL for the user to open in a browser.
    Saves PKCE state to disk so step 2 can use it.
    """
    verifier, challenge = generate_pkce()
    state = generate_state()

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = AUTHORIZE_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())

    # Save PKCE state for step 2
    PKCE_STATE_FILE.write_text(json.dumps({
        "verifier": verifier,
        "state": state,
    }))
    os.chmod(PKCE_STATE_FILE, 0o600)

    print()
    print("=" * 60)
    print("  AUTHORIZATION REQUIRED")
    print("=" * 60)
    print()
    print("1. Open this URL in any browser:")
    print()
    print(f"   {auth_url}")
    print()
    print("2. Log in with your Claude account.")
    print()
    print("3. After login, the browser will try to redirect to")
    print("   localhost (which will fail — that's OK).")
    print()
    print("4. Copy the FULL URL from the browser address bar")
    print("   (it looks like: http://localhost:0/callback?code=...&state=...)")
    print()
    print("5. Run this script again with --callback <URL>")
    print()
    print(f'   python3 {sys.argv[0]} --callback "http://localhost:0/callback?code=XXX&state=YYY"')
    print()
    print("=" * 60)


def complete_authorization(callback_url: str):
    """
    Step 2: exchange the authorization code for tokens.
    """
    if not PKCE_STATE_FILE.exists():
        log.error("No pending PKCE state found. Run the script without arguments first.")
        sys.exit(1)

    pkce = json.loads(PKCE_STATE_FILE.read_text())

    # Parse code and state from callback URL
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(callback_url)
    qs = parse_qs(parsed.query)

    # Anthropic sometimes returns code#state in fragment
    code = None
    state_from_url = None

    if "code" in qs:
        code = qs["code"][0]
        state_from_url = qs.get("state", [None])[0]
    elif parsed.fragment:
        # format: code#state
        parts = parsed.fragment.split("#")
        if parts:
            code = parts[0]
            state_from_url = parts[1] if len(parts) > 1 else None

    if not code:
        log.error("Could not extract authorization code from the URL.")
        log.error(f"URL received: {callback_url}")
        sys.exit(1)

    # Validate state if present
    if state_from_url and state_from_url != pkce["state"]:
        log.warning("State mismatch — proceeding anyway (may be fragmented).")

    # Exchange code for tokens
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": pkce["verifier"],
        "state": pkce["state"],
    }

    log.info("Exchanging authorization code for tokens...")
    resp = requests.post(TOKEN_URL, json=payload, timeout=15)

    if resp.status_code != 200:
        log.error(f"Token exchange failed: {resp.status_code} {resp.text}")
        sys.exit(1)

    data = resp.json()

    creds = {
        "accessToken": data["access_token"],
        "refreshToken": data["refresh_token"],
        "expiresAt": int(time.time() * 1000) + data.get("expires_in", 28800) * 1000,
        "scopes": data.get("scope", SCOPES).split(),
    }

    save_credentials(creds)
    PKCE_STATE_FILE.unlink(missing_ok=True)
    log.info("Authorization complete! Tokens saved.")
    print()
    print("Authorization successful!")
    print("The script will now fetch usage data automatically.")
    print()


def refresh_access_token(creds: dict) -> dict | None:
    """
    Use refresh_token to get a new access_token.
    Returns updated creds or None on failure.
    """
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": creds["refreshToken"],
        "client_id": CLIENT_ID,
    }

    try:
        resp = requests.post(TOKEN_URL, json=payload, timeout=15)
    except requests.RequestException as e:
        log.error(f"Network error during refresh: {e}")
        return None

    if resp.status_code != 200:
        log.error(f"Token refresh failed: {resp.status_code} {resp.text}")
        return None

    data = resp.json()

    creds["accessToken"] = data["access_token"]
    creds["expiresAt"] = int(time.time() * 1000) + data.get("expires_in", 28800) * 1000

    # Refresh token rotation: server may return a new refresh token
    if "refresh_token" in data:
        creds["refreshToken"] = data["refresh_token"]

    save_credentials(creds)
    log.info("Access token refreshed successfully.")
    return creds


# ── Usage fetch ──────────────────────────────────────────────────
def fetch_usage(access_token: str) -> dict | None:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(USAGE_URL, headers=headers, timeout=15)
    except requests.RequestException as e:
        log.error(f"Network error fetching usage: {e}")
        return None

    if resp.status_code == 401:
        log.warning("Usage request returned 401 — token may be invalid.")
        return None
    if resp.status_code == 429:
        log.warning("Usage request returned 429 — rate limited, will retry next run.")
        return None
    if resp.status_code != 200:
        log.error(f"Usage request failed: {resp.status_code} {resp.text}")
        return None

    return resp.json()


def save_usage(raw: dict):
    """Extract and save only the fields we care about."""
    five = raw.get("five_hour")
    seven = raw.get("seven_day")

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "five_hour": {
            "utilization": five.get("utilization", 0) if five else 0,
            "resets_at": five.get("resets_at") if five else None,
        },
        "seven_day": {
            "utilization": seven.get("utilization", 0) if seven else 0,
            "resets_at": seven.get("resets_at") if seven else None,
        },
    }

    USAGE_FILE.write_text(json.dumps(output, indent=2))
    log.info(
        f"Usage saved: session={output['five_hour']['utilization']}%, "
        f"weekly={output['seven_day']['utilization']}%"
    )


# ── Main ─────────────────────────────────────────────────────────
def main():
    # ── Handle --callback (step 2 of initial auth) ──
    if len(sys.argv) >= 3 and sys.argv[1] == "--callback":
        complete_authorization(sys.argv[2])
        # Continue to fetch usage immediately
        creds = load_credentials()
        if not creds:
            return
    else:
        creds = load_credentials()

    # ── No credentials → start auth flow ──
    if not creds:
        log.info("No credentials found. Starting authorization flow.")
        start_authorization()
        return

    log.info("Starting monitoring loop. Updates every 1 minute.")
    while True:
        try:
            # ── Refresh token if expired / about to expire ──
            if token_is_expired(creds):
                log.info("Access token expired or expiring soon. Refreshing...")
                new_creds = refresh_access_token(creds)

                if new_creds is None:
                    log.error(
                        "Failed to refresh token. Refresh token may be invalid.\n"
                        "Delete credentials.json and re-run to authorize again:\n"
                        f"  rm {CREDENTIALS_FILE}\n"
                        f"  python3 {sys.argv[0]}"
                    )
                    # Save error state to usage.json so dashboard knows
                    USAGE_FILE.write_text(json.dumps({
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "error": "token_refresh_failed",
                        "five_hour": {"utilization": -1, "resets_at": None},
                        "seven_day": {"utilization": -1, "resets_at": None},
                    }, indent=2))
                    return
                creds = new_creds

            # ── Fetch usage ──
            raw = fetch_usage(creds["accessToken"])

            if raw is None:
                # If 401, try one refresh and retry
                log.info("Attempting token refresh after failed fetch...")
                new_creds = refresh_access_token(creds)
                if new_creds:
                    creds = new_creds
                    raw = fetch_usage(creds["accessToken"])

            if raw:
                save_usage(raw)
            else:
                log.error("Could not fetch usage data.")
                
        except Exception as e:
            log.error(f"Unexpected error in monitoring loop: {e}")
            
        time.sleep(60)


if __name__ == "__main__":
    main()
