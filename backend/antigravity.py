import os
import sys
import json
import time
import argparse
import urllib.parse
from urllib.parse import urlparse, parse_qs
import requests
import logging
import datetime

# Setup logging (file and console)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("limits.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

# OAuth configuration
# These are PUBLIC credentials sourced from Google's own cliproxyapi/sdk/auth/antigravity.go.
# This is a well-known pattern for native/CLI OAuth applications: https://github.com/code-yeongyu/oh-my-openagent/issues/314
OAUTH_CONFIG = {
    'clientId': '1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com',
    'clientSecret': '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',
    'authUrl': 'https://accounts.google.com/o/oauth2/v2/auth',
    'tokenUrl': 'https://oauth2.googleapis.com/token',
    'scopes': [
        'https://www.googleapis.com/auth/cloud-platform',
        'https://www.googleapis.com/auth/userinfo.email'
    ]
}

CLOUDCODE_CONFIG = {
    'baseUrl': 'https://cloudcode-pa.googleapis.com',
    'userAgent': 'antigravity',
    'metadata': {
        'ideType': 'ANTIGRAVITY',
        'platform': 'PLATFORM_UNSPECIFIED',
        'pluginType': 'GEMINI'
    }
}

TOKEN_FILE = 'tokens.json'
LIMITS_FILE = 'limits.json'

def generate_state():
    import random
    import string
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))

def save_tokens(token_data):
    tokens = {
        'access_token': token_data.get('access_token'),
        'refresh_token': token_data.get('refresh_token'),
        'expires_at': time.time() + token_data.get('expires_in', 3600),
    }
    if 'refresh_token' not in token_data:
        old_tokens = load_tokens()
        if old_tokens and 'refresh_token' in old_tokens:
            tokens['refresh_token'] = old_tokens['refresh_token']
            
    with open(TOKEN_FILE, 'w') as f:
        json.dump(tokens, f, indent=2)

def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, 'r') as f:
        return json.load(f)

def refresh_access_token(refresh_token):
    logging.info("Refreshing access token...")
    data = {
        'refresh_token': refresh_token,
        'client_id': OAUTH_CONFIG['clientId'],
        'client_secret': OAUTH_CONFIG['clientSecret'],
        'grant_type': 'refresh_token'
    }
    
    resp = requests.post(OAUTH_CONFIG['tokenUrl'], data=data)
    if not resp.ok:
        logging.error(f"Token refresh failed: {resp.status_code} {resp.text}")
        return None
        
    token_data = resp.json()
    save_tokens(token_data)
    return token_data.get('access_token')

def get_valid_access_token():
    tokens = load_tokens()
    if not tokens:
        logging.error("Tokens not found. Please run 'login' command first.")
        return None
        
    if time.time() >= tokens.get('expires_at', 0) - 60:
        return refresh_access_token(tokens['refresh_token'])
            
    return tokens['access_token']

def complete_login(code, redirect_uri):
    logging.info("Exchanging code for tokens...")
    data = {
        'code': code,
        'client_id': OAUTH_CONFIG['clientId'],
        'client_secret': OAUTH_CONFIG['clientSecret'],
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }
    
    resp = requests.post(OAUTH_CONFIG['tokenUrl'], data=data)
    if not resp.ok:
        logging.error(f"Token exchange failed: {resp.status_code} {resp.text}")
        return
        
    token_data = resp.json()
    save_tokens(token_data)
    logging.info("Login successful! Tokens saved.")

def start_oauth_flow():
    redirect_uri = "http://127.0.0.1:8080/callback" 
    state = generate_state()
    
    params = {
        'client_id': OAUTH_CONFIG['clientId'],
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(OAUTH_CONFIG['scopes']),
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state
    }
    
    auth_url = f"{OAUTH_CONFIG['authUrl']}?{urllib.parse.urlencode(params)}"
    
    print('\nMANUAL LOGIN MODE')
    print('1. Copy this URL and open it in your browser:')
    print(auth_url)
    print('\n2. Login with your Google account.')
    print('3. You will be redirected to a dead localhost URL.')
    print('4. Copy the ENTIRE localhost redirect URL and paste it below.\n')
    
    pasted_url = input('Paste the full localhost redirect URL here: ').strip()
    
    try:
        parsed_url = urlparse(pasted_url)
        query_params = parse_qs(parsed_url.query)
        
        if 'error' in query_params:
            logging.error(f"Error: {query_params['error'][0]}")
            return
            
        code = query_params.get('code', [None])[0]
        returned_state = query_params.get('state', [None])[0]
        
        if not code or returned_state != state:
            logging.error("Invalid URL: Missing code or state mismatch")
            return
            
        complete_login(code, redirect_uri)
    except Exception as e:
        logging.error(f"Failed to parse URL: {e}")

def make_api_request(endpoint, body=None):
    access_token = get_valid_access_token()
    if not access_token:
        return None
        
    url = f"{CLOUDCODE_CONFIG['baseUrl']}{endpoint}"
    headers = {
        'Authorization': f"Bearer {access_token}",
        'Content-Type': 'application/json',
        'User-Agent': CLOUDCODE_CONFIG['userAgent']
    }
    
    resp = requests.post(url, headers=headers, json=body or {})
    if not resp.ok:
        logging.error(f"API request failed: {resp.status_code} {resp.text}")
        return None
        
    return resp.json()

def fetch_and_save_quota():
    try:
        assist_data = make_api_request('/v1internal:loadCodeAssist', { 'metadata': CLOUDCODE_CONFIG['metadata'] })
        if not assist_data:
            logging.error("Failed to fetch Code Assist data")
            return
            
        project_field = assist_data.get('cloudaicompanionProject')
        project_id = None
        if isinstance(project_field, str):
            project_id = project_field
        elif isinstance(project_field, dict):
            project_id = project_field.get('id')
            
        plan_info = assist_data.get('planInfo', {})
        monthly_credits = plan_info.get('monthlyPromptCredits', 0)
        available_credits = assist_data.get('availablePromptCredits', 0)
        used_credits = monthly_credits - available_credits if monthly_credits is not None and available_credits is not None else 0
        
        body = {}
        if project_id:
            body['project'] = project_id
            
        models_data = make_api_request('/v1internal:fetchAvailableModels', body)
        if not models_data:
            logging.error("Failed to fetch available models data")
            return
            
        models = models_data.get('models', {})
        sorted_models = sorted(models.items(), key=lambda item: item[1].get('label', item[1].get('displayName', item[0])))
        
        output_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "promptCredits": {
                "used": used_credits,
                "limit": monthly_credits,
                "remaining": available_credits
            },
            "models": []
        }
        
        for model_id, model_info in sorted_models:
            label = model_info.get('label') or model_info.get('displayName') or model_id
            
            # Internal models filter
            if model_id.startswith('chat_') or model_id.startswith('tab_') or 'image' in model_id or model_id.startswith('rev') or 'mquery' in model_id or 'lite' in model_id:
                continue
                
            quota_info = model_info.get('quotaInfo')
            if not quota_info:
                continue
                
            remaining_fraction = quota_info.get('remainingFraction', 1.0)
            used_percentage = round((1 - remaining_fraction) * 100, 1)
            remaining_percentage = round(remaining_fraction * 100, 1)
            
            reset_time = quota_info.get('resetTime', 'N/A')
            
            output_data["models"].append({
                "modelId": model_id,
                "label": label,
                "usedPercentage": used_percentage,
                "remainingPercentage": remaining_percentage,
                "resetDate": reset_time
            })
            
        with open(LIMITS_FILE, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
            
        logging.info("Quota data fetched successfully")
        
    except Exception as e:
        logging.error(f"Error fetching quota data: {str(e)}")

def daemon_mode():
    logging.info("Starting daemon to fetch limits every 60 seconds...")
    while True:
        fetch_and_save_quota()
        time.sleep(60)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Antigravity Limits CLI')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    login_parser = subparsers.add_parser('login', help='Login to Google Account')
    
    args = parser.parse_args()
    
    if args.command == 'login':
        start_oauth_flow()
    else:
        # Default behavior is to run daemon
        daemon_mode()
