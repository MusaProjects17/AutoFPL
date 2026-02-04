"""Custom score / maths layer: value index, form, fixture difficulty. Output is structured for the LLM."""

from typing import Any


def _float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def value_index(player: dict[str, Any]) -> float:
    """Points per million (cost in FPL is in 0.1 units, e.g. 85 = 8.5m)."""
    cost = _float(player.get("now_cost"), 1) / 10.0
    total_pts = _float(player.get("total_points"), 0)
    if cost <= 0:
        return 0.0
    return total_pts / cost


def form_score(player: dict[str, Any]) -> float:
    """FPL form string as float (e.g. '5.2' -> 5.2)."""
    return _float(player.get("form"), 0.0)


def fixture_difficulty_for_players(
    elements: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
    event_id: int,
) -> dict[int, float]:
    """
    For each player element id, return a difficulty score for the next gameweek.
    Lower = easier fixture (based on team strength). Uses team_a/team_h and strength.
    """
    team_strength: dict[int, float] = {}
    for t in teams:
        tid = t.get("id")
        if tid is not None:
            team_strength[int(tid)] = _float(t.get("strength_overall_home"), 1000) + _float(t.get("strength_overall_away"), 1000)

    element_to_team: dict[int, int] = {}
    for e in elements:
        eid = e.get("id")
        team = e.get("team")
        if eid is not None and team is not None:
            element_to_team[int(eid)] = int(team)

    # Fixtures for this event: team_a, team_h. Difficulty for a player = opposition strength.
    difficulty: dict[int, float] = {}
    for f in fixtures:
        if f.get("event") != event_id:
            continue
        team_a = f.get("team_a")
        team_h = f.get("team_h")
        if team_a is None or team_h is None:
            continue
        str_a = team_strength.get(int(team_a), 1000)
        str_h = team_strength.get(int(team_h), 1000)
        for eid, tid in element_to_team.items():
            if tid == int(team_a):
                difficulty[eid] = str_h  # away at team_h, so difficulty = home strength
            elif tid == int(team_h):
                difficulty[eid] = str_a  # home vs team_a
    return difficulty


def enrich_players_with_scores(
    elements: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
    event_id: int,
) -> list[dict[str, Any]]:
    """
    Add value_index, form_score, and fixture_difficulty to each player (for LLM context).
    Returns a list of dicts with id, web_name, element_type, team, now_cost, total_points,
    value_index, form_score, fixture_difficulty, chance_of_playing_this_round, status, news.
    """
    difficulty = fixture_difficulty_for_players(elements, teams, fixtures, event_id)
    out: list[dict[str, Any]] = []
    for p in elements:
        eid = p.get("id")
        if eid is None:
            continue
        out.append({
            "id": eid,
            "web_name": p.get("web_name", ""),
            "element_type": p.get("element_type"),
            "team": p.get("team"),
            "now_cost": p.get("now_cost"),
            "total_points": p.get("total_points"),
            "value_index": round(value_index(p), 2),
            "form_score": form_score(p),
            "fixture_difficulty": difficulty.get(int(eid)),
            "chance_of_playing_this_round": p.get("chance_of_playing_this_round"),
            "status": p.get("status"),
            "news": p.get("news") or "",
        })
    return out
