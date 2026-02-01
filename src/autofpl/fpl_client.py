"""FPL API client: public data (bootstrap-static, fixtures) and authenticated session (my-team, transfers)."""

import time
from typing import Any

import requests

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


def login(email: str, password: str) -> requests.Session:
    """Log in to FPL; returns a session with cookies for authenticated endpoints."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "AutoFPL/1.0",
        "Origin": "https://fantasy.premierleague.com",
        "Referer": "https://fantasy.premierleague.com/",
    })
    payload = {
        "login": email,
        "password": password,
        "app": "plfpl-web",
        "redirect_uri": "https://fantasy.premierleague.com/",
    }
    r = session.post(LOGIN_URL, data=payload, timeout=30)
    r.raise_for_status()
    if "pl_profile" not in session.cookies.get_dict() and "session" not in str(r.url).lower():
        try:
            data = r.json()
            if data.get("detail") or data.get("error"):
                raise ValueError(f"Login failed: {data}")
        except Exception:
            pass
    return session


def get_my_team(session: requests.Session, manager_id: int) -> dict[str, Any]:
    """Fetch current picks, bank, transfers, chips (requires logged-in session)."""
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
