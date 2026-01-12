from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from typing import Mapping

import base64, json, hmac, hashlib, requests

import time

AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
API_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"
SCOPES = "com.intuit.quickbooks.accounting com.intuit.quickbooks.payment"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _basic_auth_header():
    pair = f"{settings.INTUIT_CLIENT_ID}:{settings.INTUIT_CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(pair).decode()


def oauth_authorize_url(state: str) -> str:
    # intuit accepts space delimited scopes; the'll be URL-encoded by the browser
    return (
        f"{AUTH_URL}"
        f"?client_id={settings.INTUIT_CLIENT_ID}"
        f"&redirect_uri={settings.INTUIT_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPES}"
        f"&state={state}"
    )


def _post_form(url: str, data: Mapping[str, str], headers: Mapping[str, str], *, tries: int = 3, timeout: int = 30):
    """
    POST application/x-www-form-urlencoded with small exponential backoff
    for transient errors (429/5xx). Non-retryable 4xx are returned immediately.

    Returns: requests.Response
    """
    last = None
    for attempt in range(1, tries + 1):
        r = requests.post(url, data = data, headers=headers, timeout=timeout)
        # retry only on known transient statuses
        if r.status_code in RETRYABLE_STATUS and attempt < tries:
            # simple backoff: 1s, 2s, 4s
            time.sleep(2 ** (attempt -1))
            last = r
            continue
        return r
    # if all attempts were retryable failures, return the last response
    return last or r


def exchange_code_for_tokens(code: str):
    data = {
        "grant_type": "authorization_code", 
        "code": code, 
        "redirect_uri": settings.INTUIT_REDIRECT_URI,
        }
    headers = {
        "Authorization": _basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    r = _post_form(TOKEN_URL, data = data, headers = headers)
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        # surfce the exact server message to debug (invalid_grant, invalid_client, etc.)
        raise requests.HTTPError(f"Token exchange failed: {r.status_code} {detail}")
    return r.json()


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    mac = hmac.new(settings.QBO_WEBHOOK_VERIFIER_TOKEN.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode()
    return hmac.compare_digest(expected, signature_header or "")


class QboApi:
    def __init__(self, conn):
        self.conn = conn
    
    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.conn.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    
    def _url(self, path: str) -> str:
        sep = "&" if "?" in path else "?"
        return f"{API_BASE}/{self.conn.realm_id}/{path}{sep}minorversion={settings.QBO_MINOR_VERSION}"
    
    def _ensure_fresh(self):
        from django.utils import timezone
        # refresh a little early
        if timezone.now() >= self.conn.access_token_expires_at - timedelta(seconds = 300):
            self.refresh_tokens()
    
    def refresh_tokens(self):
        data = {"grant_type": "refresh_token", "refresh_token": self.conn.refresh_token}
        headers = {
            "Authorization": _basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        r = _post_form(TOKEN_URL, data = data, headers = headers)
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise requests.HTTPError(f"Refresh failed: {r.status_code} {detail}")
        
        p = r.json()
        self.conn.access_token = p["access_token"]
        self.conn.refresh_token = p.get("refresh_token", self.conn.refresh_token)
        self.conn.access_token_expires_at = timezone.now() + timedelta(seconds = int(p.get("expires_in", 3600)))
        self.conn.save(update_fields=["access_token", "refresh_token", "access_token_expires_at"])
    
    def get(self, path: str):
        self._ensure_fresh()
        url = self._url(path)
        r = requests.get(url, headers = self.headers, timeout = 30)
        if r.status_code == 401:
            self.refresh_tokens()
            r = requests.get(url, headers = self.headers, timeout = 30)
        r.raise_for_status()
        return r.json()
    
    def post(self, path: str, payload: dict):
        self._ensure_fresh()
        url = self._url(path)
        r = requests.post(url, headers = self.headers, data = json.dumps(payload), timeout = 30)
        if r.status_code == 401:
            self.refresh_tokens()
            r = requests.post(url, headers = self.headers, data = json.dumps(payload), timeout = 30)
        r.raise_for_status()
        return r.json()
    
    def get_customer(self, customer_id: str) -> dict:
        return self.get(f"customer/{customer_id}")

    def get_invoice(self, invoice_id: str) -> dict:
        return self.get(f"invoice/{invoice_id}")