"""FPL API client: public data (bootstrap-static, fixtures) and authenticated session (my-team, transfers)."""

import time
from typing import Any

import requests

# FPL API base; use /api/ for all endpoints (e.g. my-team, transfers).
FPL_BASE = "https://fantasy.premierleague.com/api"


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


def session_from_bearer_token(token: str) -> requests.Session:
    """Create a session that sends the token in X-Api-Authorization (same as the browser my-team request).
    Get the value from DevTools → Network → click 'Pick Team' → filter 'my-team' → Headers → X-Api-Authorization.
    Set FPL_ACCESS_TOKEN in .env to that value (never commit)."""
    raw = (token or "").strip()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-GB,en;q=0.9",
        "Origin": "https://fantasy.premierleague.com",
        "Referer": "https://fantasy.premierleague.com/my-team",
        "X-Api-Authorization": raw,
    })
    session.get("https://fantasy.premierleague.com/", timeout=30)
    return session


def get_my_team(session: requests.Session, manager_id: int) -> dict[str, Any]:
    """Fetch current picks, bank, transfers, chips (requires session with X-Api-Authorization)."""
    # Use same Origin/Referer as browser when calling /api/
    session.headers.setdefault("Referer", "https://fantasy.premierleague.com/my-team")
    return _get(f"{FPL_BASE}/my-team/{manager_id}/", session=session)


def get_entry(manager_id: int, session: requests.Session | None = None) -> dict[str, Any]:
    """Fetch public entry summary (no auth required)."""
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
    if not r.ok:
        try:
            err_body = r.json()
        except Exception:
            err_body = (r.text or "")[:500]
        raise requests.HTTPError(
            f"{r.status_code} {r.reason}: {err_body}", response=r, request=r.request
        )
    if not (r.text or "").strip():
        return {}
    try:
        return r.json()
    except ValueError as e:
        text = (r.text or "")[:500]
        raise ValueError(f"FPL transfer API returned non-JSON (status={r.status_code}): {e}. Body: {text!r}") from e


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
