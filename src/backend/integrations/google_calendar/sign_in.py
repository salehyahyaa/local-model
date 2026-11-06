"""Sign in with Google, written with plain HTTP calls. offline access is what lets the sign-in last without logging in again."""

import asyncio
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

from src.backend.integrations.google_calendar import api
from src.backend.integrations.oauth import OAuthError

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
PENDING_LIFETIME_SECONDS = 600

pending_sign_ins = {}


def forget_expired_sign_ins():
    cutoff = time.time() - PENDING_LIFETIME_SECONDS
    for state in [state for state, pending in pending_sign_ins.items() if pending["startedAt"] < cutoff]:
        del pending_sign_ins[state]


def begin(client_id, client_secret, redirect_uri):
    """Returns the address the owner signs in at."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    forget_expired_sign_ins()
    pending_sign_ins[state] = {
        "clientId": client_id,
        "clientSecret": client_secret,
        "redirectUri": redirect_uri,
        "verifier": verifier,
        "startedAt": time.time(),
    }
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTHORIZATION_URL}?{urlencode(query)}"


async def finish(state, code):
    """Returns (client ID, client secret, refresh token, account) once Google Calendar has really answered.

    The account can be None. Raises OAuthError.
    """
    forget_expired_sign_ins()
    pending = pending_sign_ins.pop(state, None)
    if pending is None:
        raise OAuthError("This sign-in has expired. Connect Google Calendar again.")
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": pending["clientId"],
        "client_secret": pending["clientSecret"],
        "redirect_uri": pending["redirectUri"],
        "code_verifier": pending["verifier"],
    }
    try:
        tokens = await asyncio.to_thread(api.request_tokens, form)
        if not tokens.get("refresh_token"):
            raise OAuthError("Google didn't allow lasting access. Connect Google Calendar again.")
        account = await asyncio.to_thread(api.find_account, tokens["access_token"])
    except api.CalendarError as error:
        message = "Google rejected the sign-in. Check the client ID and secret." if str(error) == api.EXPIRED_MESSAGE else str(error)
        raise OAuthError(message) from error
    return pending["clientId"], pending["clientSecret"], tokens["refresh_token"], account
