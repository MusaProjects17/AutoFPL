"""FPL API client: public data (bootstrap-static, fixtures) and authenticated session (my-team, transfers)."""

import os
import time
from typing import Any

import requests

# FPL moved from /drf/ to /api/; use /api/ for all endpoints (e.g. my-team, transfers).
FPL_BASE = "https://fantasy.premierleague.com/api"
LOGIN_URL = "https://users.premierleague.com/accounts/login/"


def _get(url: str, session: requests.Session | None = None, **kwargs: Any) -> Any:
    """GET with optional session and retries on 429/5xx."""
    sess = session or requests.Session()
    for attempt in range(3):
        r = sess.get(url, timeout=30, **kwargs)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


def get_bootstrap_static(session: requests.Session | None = None) -> dict[str, Any]:
    """Fetch bootstrap-static: events (gameweeks), teams, elements (players), settings."""
    return _get(f"{FPL_BASE}/bootstrap-static/", session=session)


def get_fixtures(session: requests.Session | None = None, event_id: int | None = None) -> list[dict[str, Any]]:
    """Fetch fixtures. If event_id is set, filter by that gameweek."""
    url = f"{FPL_BASE}/fixtures/"
    if event_id is not None:
        url += f"?event={event_id}"
    return _get(url, session=session)


def session_from_cookie(cookie: str) -> requests.Session:
    """Create a session that uses only the given cookie (no login POST).
    Use when programmatic login returns 403: copy cookie from browser while logged into FPL (see README).
    Sets cookies for both .premierleague.com and fantasy.premierleague.com so _spdt and auth cookies are sent.
    Set FPL_USE_BEARER=1 to also send access_token as Bearer (can cause 401 if API does not accept it)."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-GB,en;q=0.9",
        "Origin": "https://fantasy.premierleague.com",
        "Referer": "https://fantasy.premierleague.com/my-team",
    })
    access_token_value: str | None = None
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            name, value = name.strip(), value.strip()
            if not name:
                continue
            if name.lower() == "access_token":
                access_token_value = value
            # Set for both domains: .premierleague.com (access_token, refresh_token, datadome) and fantasy.premierleague.com (_spdt)
            session.cookies.set(name, value, domain=".premierleague.com")
            session.cookies.set(name, value, domain=".fantasy.premierleague.com")
    if access_token_value and os.getenv("FPL_USE_BEARER", "").strip().lower() in ("1", "true", "yes"):
        session.headers["Authorization"] = f"Bearer {access_token_value}"
    session.get("https://fantasy.premierleague.com/", timeout=30)
    return session


def login(
    email: str,
    password: str,
    cookie: str | None = None,
) -> requests.Session:
    """Log in to FPL; returns a session with cookies for authenticated endpoints.
    My-team is at /api/my-team/{id}/ (FPL moved from /drf/ to /api/).
    If you get 403, set FPL_COOKIE in .env to your browser cookie when logged into FPL (see README)."""
    if cookie is None:
        cookie = os.getenv("FPL_COOKIE")
    session = requests.Session()
    # Browser-like headers (per Stack Overflow / FPL auth guides)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
        "Accept-Language": "en-GB,en;q=0.9",
        "Origin": "https://fantasy.premierleague.com",
        "Referer": "https://fantasy.premierleague.com/my-team",
        "Content-Type": "application/x-www-form-urlencoded",
        "Authority": "users.premierleague.com",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
    })
    # GET login page first so server can set session cookies
    session.get(LOGIN_URL, timeout=30)
    session.get("https://fantasy.premierleague.com/", timeout=30)
    payload = {
        "login": email,
        "password": password,
        "app": "plfpl-web",
        "redirect_uri": "https://fantasy.premierleague.com/a/login",
    }
    post_kwargs: dict[str, Any] = {"data": payload, "timeout": 30, "allow_redirects": True}
    if cookie:
        post_kwargs["headers"] = {"Cookie": cookie}
    r = session.post(LOGIN_URL, **post_kwargs)
    r.raise_for_status()
    # Follow to FPL so cookies for fantasy.premierleague.com are set
    session.get("https://fantasy.premierleague.com/", timeout=30)
    # For subsequent API calls
    session.headers["Accept"] = "application/json"
    session.headers["Referer"] = "https://fantasy.premierleague.com/my-team"
    if "pl_profile" not in session.cookies.get_dict() and "sessionid" not in session.cookies.get_dict():
        try:
            data = r.json()
            if data.get("detail") or data.get("error"):
                raise ValueError(f"Login failed: {data}")
        except Exception:
            pass
    return session


def get_my_team(session: requests.Session, manager_id: int) -> dict[str, Any]:
    """Fetch current picks, bank, transfers, chips (requires logged-in session)."""
    # Use same Origin/Referer as browser when calling /api/
    session.headers.setdefault("Referer", "https://fantasy.premierleague.com/my-team")
    return _get(f"{FPL_BASE}/my-team/{manager_id}/", session=session)


def get_entry(manager_id: int, session: requests.Session | None = None) -> dict[str, Any]:
    """Fetch public entry summary (no login)."""
    return _get(f"{FPL_BASE}/entry/{manager_id}/", session=session or requests.Session())


def get_entry_picks(session: requests.Session, manager_id: int, event_id: int) -> dict[str, Any]:
    """Fetch picks for a specific gameweek (authenticated for own team)."""
    return _get(f"{FPL_BASE}/entry/{manager_id}/event/{event_id}/picks/", session=session)


def get_transfers(session: requests.Session, manager_id: int) -> list[dict[str, Any]]:
    """Fetch transfer history (authenticated)."""
    return _get(f"{FPL_BASE}/entry/{manager_id}/transfers/", session=session)


def next_gameweek_and_deadline(bootstrap: dict[str, Any]) -> tuple[int | None, int | None]:
    """Return (next_gw_id, deadline_epoch) for the next gameweek, or (None, None) if season ended."""
    now = int(time.time())
    events = bootstrap.get("events", [])
    for ev in events:
        deadline = ev.get("deadline_time_epoch")
        if deadline is None:
            continue
        try:
            if int(deadline) > now:
                return int(ev["id"]), int(deadline)
        except (TypeError, ValueError):
            continue
    return None, None


def _transfer_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Origin": "https://fantasy.premierleague.com",
        "Referer": "https://fantasy.premierleague.com/transfers",
    }


def _my_team_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Origin": "https://fantasy.premierleague.com",
        "Referer": "https://fantasy.premierleague.com/my-team",
    }


def post_transfer(
    session: requests.Session,
    manager_id: int,
    gameweek: int,
    transfers: list[dict[str, Any]],
    chip: str | None = None,
    confirmed: bool = True,
) -> dict[str, Any]:
    """POST transfers. transfers = [{element_in, element_out, purchase_price, selling_price}]. chip: 'wildcard' or 'freehit' or None."""
    payload: dict[str, Any] = {
        "entry": manager_id,
        "event": gameweek,
        "transfers": transfers,
        "chip": chip,
        "confirmed": confirmed,
    }
    r = session.post(
        f"{FPL_BASE}/transfers/",
        json=payload,
        headers=_transfer_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def post_team(
    session: requests.Session,
    manager_id: int,
    picks: list[dict[str, Any]],
    chip: str | None = None,
) -> None:
    """POST lineup. picks = [{element, position, is_captain, is_vice_captain}, ...] for 15 players. chip: 'bboost', '3xc' or None."""
    payload = {"picks": picks, "chip": chip}
    r = session.post(
        f"{FPL_BASE}/my-team/{manager_id}/",
        json=payload,
        headers=_my_team_headers(),
        timeout=30,
    )
    r.raise_for_status()
