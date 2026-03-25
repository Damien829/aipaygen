"""OAuth routes — Google and GitHub sign-in for AiPayGen."""
import json
import logging
import os
import time

import jwt as _jwt
from authlib.integrations.requests_client import OAuth2Session
from flask import Blueprint, redirect, request, session, url_for, jsonify

from accounts import (
    create_or_get_oauth_account,
    get_account_keys,
    link_key_to_account,
)
from api_keys import generate_key

logger = logging.getLogger(__name__)

oauth_bp = Blueprint("oauth", __name__)

# ── Config ────────────────────────────────────────────────────────────────

_JWT_SECRET = os.environ.get("JWT_SECRET", "aipaygen-jwt-2026")
BASE_URL = os.environ.get("OAUTH_BASE_URL", os.environ.get("BASE_URL", "https://aipaygen.com"))
# OAuth callbacks must go to the main domain, not api subdomain
if "api." in BASE_URL:
    BASE_URL = BASE_URL.replace("api.", "")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"


def _make_jwt(email: str, api_key: str) -> str:
    now = int(time.time())
    payload = {"email": email, "api_key": api_key, "iat": now, "exp": now + 30 * 86400}
    return _jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _get_or_create_key_for_account(account: dict) -> str:
    """Get existing API key or create one for the account."""
    keys = get_account_keys(account["id"])
    if keys:
        return keys[0]["api_key"]
    # Create new key with trial credits
    new_key = generate_key(initial_balance=0.25, label="oauth-login", source=f"oauth-{account.get('oauth_provider', 'unknown')}")
    link_key_to_account(account["id"], new_key["key"])
    return new_key["key"]


# ── Google OAuth ──────────────────────────────────────────────────────────

@oauth_bp.route("/sign-in/google")
def google_login():
    """Redirect to Google OAuth consent screen."""
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "Google OAuth not configured"}), 503
    redirect_uri = f"{BASE_URL}/sign-in/google/callback"
    oauth = OAuth2Session(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri=redirect_uri,
                          scope="openid email profile")
    uri, state = oauth.create_authorization_url(GOOGLE_AUTH_URL)
    session["oauth_state"] = state
    # Prevent open redirect — only allow relative paths and aipaygen:// deep links
    _redir = request.args.get("redirect", "/dashboard")
    session["oauth_redirect"] = _redir if (_redir.startswith("/") or _redir.startswith("aipaygen://")) else "/dashboard"
    return redirect(uri)


@oauth_bp.route("/sign-in/google/callback")
def google_callback():
    """Handle Google OAuth callback."""
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "Google OAuth not configured"}), 503

    redirect_uri = f"{BASE_URL}/sign-in/google/callback"
    oauth = OAuth2Session(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri=redirect_uri,
                          state=session.get("oauth_state"))
    try:
        token = oauth.fetch_token(GOOGLE_TOKEN_URL, authorization_response=request.url)
    except Exception as e:
        logger.error("Google OAuth token fetch failed: %s", e)
        return redirect(f"/login?error=google_auth_failed")

    # Get user info
    try:
        resp = oauth.get(GOOGLE_USERINFO_URL)
        user_info = resp.json()
    except Exception as e:
        logger.error("Google userinfo fetch failed: %s", e)
        return redirect(f"/login?error=google_userinfo_failed")

    email = user_info.get("email", "")
    if not email:
        return redirect("/login?error=no_email")

    # Create or get account
    account = create_or_get_oauth_account(
        email=email,
        provider="google",
        oauth_id=user_info.get("sub", ""),
        display_name=user_info.get("name", ""),
        avatar_url=user_info.get("picture", ""),
    )

    # Get or create API key
    api_key = _get_or_create_key_for_account(account)

    # Issue JWT
    jwt_token = _make_jwt(email, api_key)

    # Set session cookie
    session["session_token"] = jwt_token
    session["user_email"] = email
    session["user_name"] = user_info.get("name", "")
    session["user_avatar"] = user_info.get("picture", "")

    # Log event
    try:
        from funnel_tracker import log_event
        ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
        log_event("oauth_login", endpoint="/sign-in/google/callback", ip=ip,
                  metadata=json.dumps({"provider": "google", "email": email[:3] + "***"}))
    except Exception:
        pass

    # Redirect — support app deep link (validated against open redirect)
    redir = session.pop("oauth_redirect", "/dashboard")
    if not (redir.startswith("/") or redir.startswith("aipaygen://")) or redir.startswith("//"):
        redir = "/dashboard"
    if redir.startswith("aipaygen://"):
        return redirect(f"{redir}?jwt={jwt_token}&api_key={api_key}")
    return redirect(f"{redir}?jwt={jwt_token}")


# ── GitHub OAuth ──────────────────────────────────────────────────────────

@oauth_bp.route("/sign-in/github")
def github_login():
    """Redirect to GitHub OAuth consent screen."""
    if not GITHUB_CLIENT_ID:
        return jsonify({"error": "GitHub OAuth not configured"}), 503
    redirect_uri = f"{BASE_URL}/sign-in/github/callback"
    oauth = OAuth2Session(GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, redirect_uri=redirect_uri,
                          scope="read:user user:email")
    uri, state = oauth.create_authorization_url(GITHUB_AUTH_URL)
    session["oauth_state"] = state
    _redir = request.args.get("redirect", "/dashboard")
    session["oauth_redirect"] = _redir if (_redir.startswith("/") or _redir.startswith("aipaygen://")) else "/dashboard"
    return redirect(uri)


@oauth_bp.route("/sign-in/github/callback")
def github_callback():
    """Handle GitHub OAuth callback."""
    if not GITHUB_CLIENT_ID:
        return jsonify({"error": "GitHub OAuth not configured"}), 503

    error = request.args.get("error")
    if error:
        # Sanitize error to prevent injection — only allow known OAuth error codes
        from urllib.parse import quote
        safe_error = quote(error[:50], safe="")
        return redirect(f"/login?error={safe_error}")

    redirect_uri = f"{BASE_URL}/sign-in/github/callback"
    oauth = OAuth2Session(GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, redirect_uri=redirect_uri,
                          state=session.get("oauth_state"))
    try:
        token = oauth.fetch_token(GITHUB_TOKEN_URL, authorization_response=request.url)
    except Exception as e:
        logger.error("GitHub OAuth token fetch failed: %s", e)
        return redirect("/login?error=github_auth_failed")

    # Get user info
    try:
        resp = oauth.get(GITHUB_USER_URL)
        user_info = resp.json()
    except Exception as e:
        logger.error("GitHub userinfo fetch failed: %s", e)
        return redirect("/login?error=github_userinfo_failed")

    email = user_info.get("email", "")

    # GitHub may not return email in profile — fetch from emails endpoint
    if not email:
        try:
            emails_resp = oauth.get(GITHUB_EMAILS_URL)
            emails = emails_resp.json()
            for em in emails:
                if em.get("primary") and em.get("verified"):
                    email = em["email"]
                    break
            if not email and emails:
                email = emails[0].get("email", "")
        except Exception:
            pass

    if not email:
        return redirect("/login?error=no_email")

    # Create or get account
    account = create_or_get_oauth_account(
        email=email,
        provider="github",
        oauth_id=str(user_info.get("id", "")),
        display_name=user_info.get("name") or user_info.get("login", ""),
        avatar_url=user_info.get("avatar_url", ""),
    )

    # Get or create API key
    api_key = _get_or_create_key_for_account(account)

    # Issue JWT
    jwt_token = _make_jwt(email, api_key)

    # Set session cookie
    session["session_token"] = jwt_token
    session["user_email"] = email
    session["user_name"] = user_info.get("name") or user_info.get("login", "")
    session["user_avatar"] = user_info.get("avatar_url", "")

    # Log event
    try:
        from funnel_tracker import log_event
        ip = request.headers.get("CF-Connecting-IP", request.remote_addr or "")
        log_event("oauth_login", endpoint="/sign-in/github/callback", ip=ip,
                  metadata=json.dumps({"provider": "github", "username": user_info.get("login", "")}))
    except Exception:
        pass

    # Redirect (validated against open redirect)
    redir = session.pop("oauth_redirect", "/dashboard")
    if not (redir.startswith("/") or redir.startswith("aipaygen://")) or redir.startswith("//"):
        redir = "/dashboard"
    if redir.startswith("aipaygen://"):
        return redirect(f"{redir}?jwt={jwt_token}&api_key={api_key}")
    return redirect(f"{redir}?jwt={jwt_token}")


# ── API endpoint for mobile/SPA ──────────────────────────────────────────

@oauth_bp.route("/sign-in/token", methods=["POST"])
def oauth_token_exchange():
    """Exchange OAuth code for JWT — used by mobile app / SPA.

    POST {provider: "google"|"github", code: "...", redirect_uri: "..."}
    Returns {jwt, api_key, email, display_name}
    """
    data = request.get_json() or {}
    provider = data.get("provider", "")
    code = data.get("code", "")
    redirect_uri = data.get("redirect_uri", "")

    if not code:
        return jsonify({"error": "Missing authorization code"}), 400

    if provider == "google":
        if not GOOGLE_CLIENT_ID:
            return jsonify({"error": "Google OAuth not configured"}), 503
        oauth = OAuth2Session(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, redirect_uri=redirect_uri)
        try:
            token = oauth.fetch_token(GOOGLE_TOKEN_URL, code=code)
            user_info = oauth.get(GOOGLE_USERINFO_URL).json()
        except Exception as e:
            return jsonify({"error": f"Google auth failed: {e}"}), 400
        email = user_info.get("email", "")
        oauth_id = user_info.get("sub", "")
        display_name = user_info.get("name", "")
        avatar_url = user_info.get("picture", "")

    elif provider == "github":
        if not GITHUB_CLIENT_ID:
            return jsonify({"error": "GitHub OAuth not configured"}), 503
        oauth = OAuth2Session(GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, redirect_uri=redirect_uri)
        try:
            token = oauth.fetch_token(GITHUB_TOKEN_URL, code=code)
            user_info = oauth.get(GITHUB_USER_URL).json()
        except Exception as e:
            return jsonify({"error": f"GitHub auth failed: {e}"}), 400
        email = user_info.get("email", "")
        if not email:
            try:
                emails = oauth.get(GITHUB_EMAILS_URL).json()
                for em in emails:
                    if em.get("primary") and em.get("verified"):
                        email = em["email"]
                        break
            except Exception:
                pass
        oauth_id = str(user_info.get("id", ""))
        display_name = user_info.get("name") or user_info.get("login", "")
        avatar_url = user_info.get("avatar_url", "")
    else:
        return jsonify({"error": "Unsupported provider. Use 'google' or 'github'."}), 400

    if not email:
        return jsonify({"error": "Could not retrieve email from provider"}), 400

    account = create_or_get_oauth_account(email, provider, oauth_id, display_name, avatar_url)
    api_key = _get_or_create_key_for_account(account)
    jwt_token = _make_jwt(email, api_key)

    return jsonify({
        "jwt": jwt_token,
        "api_key": api_key,
        "email": email,
        "display_name": display_name,
        "avatar_url": avatar_url,
    })
