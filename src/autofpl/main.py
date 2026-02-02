"""CLI entrypoint: --dry-run / --apply, optional --gw; loads .env and runs the pipeline."""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from autofpl.decisions import GameweekDecisions
from autofpl.executor import run_apply, run_dry_run
from autofpl.fpl_client import (
    get_bootstrap_static,
    get_fixtures,
    get_my_team,
    login,
    next_gameweek_and_deadline,
    session_from_cookie,
)
from autofpl.llm import get_decisions
from autofpl.scoring import enrich_players_with_scores

# Placeholder squad when my-team cannot be fetched (e.g. 403). (element_type, name) per FPL: 1=GK, 2=DEF, 3=MID, 4=FWD.
# Names matched against web_name / second_name / first_name (case-insensitive). Accents normalized (ú->u, ñ->n, etc.).
# Order: starting XI (1 GK, 4 DEF, 4 MID, 2 FWD) then bench (1 GK, 1 DEF, 1 MID, 1 FWD).
PLACEHOLDER_SQUAD_SPEC: list[tuple[int, str]] = [
    (1, "Henderson"),
    (2, "Gabriel"), (2, "Dorgu"), (2, "Romero"), (2, "Rúben"),
    (3, "B.Fernandes"), (3, "Schade"), (3, "Rice"), (3, "Wirtz"),
    (4, "Haaland"), (4, "Marc Guiu"),
    (1, "Dúbravka"),
    (2, "Muñoz"), (3, "L.Miley"), (4, "Thiago"),
]


def _norm(s: str) -> str:
    """Normalize for matching: lowercase and strip common accents (ú->u, ñ->n, etc.)."""
    s = (s or "").lower()
    for old, new in [("ú", "u"), ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ñ", "n"), ("\u00f1", "n")]:
        s = s.replace(old, new)
    return s


def _resolve_placeholder_squad(elements: list[dict]) -> list[int]:
    """Resolve PLACEHOLDER_SQUAD_SPEC to FPL element ids using bootstrap elements. Returns list of 15 ids (or fewer if some names do not match)."""
    seen: set[int] = set()
    result: list[int] = []
    for etype, name in PLACEHOLDER_SQUAD_SPEC:
        key = _norm(name)
        for p in elements:
            if p.get("element_type") != etype:
                continue
            eid = p.get("id")
            if eid is None or int(eid) in seen:
                continue
            web = _norm(p.get("web_name") or "")
            second = _norm(p.get("second_name") or "")
            first = _norm(p.get("first_name") or "")
            if key in web or key in second or key in first:
                result.append(int(eid))
                seen.add(int(eid))
                break
        else:
            # Fallbacks if FPL spells differently: Dorgu, Schade, Rúben (Dias)
            if name == "Dorgu":
                for p in elements:
                    eid = p.get("id")
                    if p.get("element_type") != 2 or eid is None or int(eid) in seen:
                        continue
                    w, sec = _norm(p.get("web_name") or ""), _norm(p.get("second_name") or "")
                    if "dorgu" in w or "dorgu" in sec:
                        result.append(int(eid))
                        seen.add(int(eid))
                        break
            elif name == "Schade":
                for p in elements:
                    eid = p.get("id")
                    if p.get("element_type") != 3 or eid is None or int(eid) in seen:
                        continue
                    w, sec = _norm(p.get("web_name") or ""), _norm(p.get("second_name") or "")
                    if "schade" in w or "schade" in sec:
                        result.append(int(eid))
                        seen.add(int(eid))
                        break
            elif name == "Rúben":
                for p in elements:
                    eid = p.get("id")
                    if p.get("element_type") != 2 or eid is None or int(eid) in seen:
                        continue
                    w, sec = _norm(p.get("web_name") or ""), _norm(p.get("second_name") or "")
                    if "dias" in w or "dias" in sec or ("ruben" in w and "dias" in sec):
                        result.append(int(eid))
                        seen.add(int(eid))
                        break
    return result


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="AutoFPL: fetch data, LLM decisions, optional apply.")
    parser.add_argument("--dry-run", action="store_true", help="Only log decisions (default if --apply not set)")
    parser.add_argument("--apply", action="store_true", help="Apply decisions to FPL account")
    parser.add_argument("--gw", type=int, default=None, help="Gameweek (default: next GW from API)")
    parser.add_argument("--test-placeholder", action="store_true", help="Resolve and print placeholder squad then exit (no API key needed)")
    parser.add_argument("--require-team", action="store_true", help="Exit with error if real team data cannot be fetched (no LLM call with placeholder)")
    args = parser.parse_args()
    apply_changes = args.apply  # default is dry-run when --apply not passed

    if args.test_placeholder:
        bootstrap = get_bootstrap_static()
        elements = bootstrap.get("elements", [])
        ids = _resolve_placeholder_squad(elements)
        id_to_player = {int(e["id"]): e for e in elements if e.get("id") is not None}
        print("Placeholder squad (resolved from your list):")
        print("  Starting XI:")
        for i, eid in enumerate(ids[:11]):
            p = id_to_player.get(eid, {})
            pos = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(p.get("element_type"), "?")
            print(f"    {i+1}. {p.get('web_name', str(eid))} (id={eid}, {pos})")
        print("  Bench:")
        for i, eid in enumerate(ids[11:], 1):
            p = id_to_player.get(eid, {})
            pos = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(p.get("element_type"), "?")
            print(f"    {i}. {p.get('web_name', str(eid))} (id={eid}, {pos})")
        if len(ids) < 15:
            print(f"  (Only {len(ids)}/15 players matched; check name spelling in PLACEHOLDER_SQUAD_SPEC.)")
        sys.exit(0)

    email = os.getenv("FPL_EMAIL")
    password = os.getenv("FPL_PASSWORD")
    manager_id_str = os.getenv("FPL_MANAGER_ID")
    api_key = os.getenv("GOOGLE_AI_API_KEY")

    if not api_key:
        logger.error("GOOGLE_AI_API_KEY not set. Set it in .env or environment.")
        sys.exit(1)
    if apply_changes and (not email or not password):
        logger.error("FPL_EMAIL and FPL_PASSWORD required when using --apply.")
        sys.exit(1)
    if not manager_id_str:
        logger.error("FPL_MANAGER_ID not set. Set it in .env (your FPL entry ID from the URL).")
        sys.exit(1)
    try:
        manager_id = int(manager_id_str)
    except ValueError:
        logger.error("FPL_MANAGER_ID must be an integer.")
        sys.exit(1)

    bootstrap = get_bootstrap_static()
    next_gw, deadline_epoch = next_gameweek_and_deadline(bootstrap)
    if next_gw is None:
        logger.error("No upcoming gameweek (season may have ended).")
        sys.exit(1)
    gameweek = args.gw if args.gw is not None else next_gw
    logger.info("Using gameweek %s (deadline epoch %s).", gameweek, deadline_epoch)

    elements = bootstrap.get("elements", [])
    teams = bootstrap.get("teams", [])
    fixtures = get_fixtures(event_id=gameweek)
    player_scores = enrich_players_with_scores(elements, teams, fixtures, gameweek)

    fixtures_summary = ""
    for f in fixtures:
        team_h = f.get("team_h")
        team_a = f.get("team_a")
        if team_h is not None and team_a is not None:
            name_h = next((t.get("short_name", str(team_h)) for t in teams if t.get("id") == team_h), str(team_h))
            name_a = next((t.get("short_name", str(team_a)) for t in teams if t.get("id") == team_a), str(team_a))
            fixtures_summary += f"  {name_h} vs {name_a}\n"

    session = None
    my_team = None
    my_team_picks: list[dict] = []
    bank = 0
    free_transfers = 1
    chips_available = ["wildcard", "free_hit", "bench_boost", "triple_captain"]

    if email and password:
        try:
            session = login(email, password)
            my_team = get_my_team(session, manager_id)
            picks_raw = my_team.get("picks", [])
            my_team_picks = picks_raw
            bank = my_team.get("transfers", {}).get("bank", 0) or 0
            free_transfers = my_team.get("transfers", {}).get("free", 1) or 1
            chips = my_team.get("chips", [])
            chips_available = [c.get("name", "").lower().replace(" ", "_") for c in chips if c.get("status") == "available"]
            if not chips_available:
                chips_available = ["none"]
        except Exception as e:
            # If login/my-team failed and FPL_COOKIE is set, try cookie-only (browser cookie)
            cookie = os.getenv("FPL_COOKIE")
            if cookie:
                try:
                    session = session_from_cookie(cookie)
                    my_team = get_my_team(session, manager_id)
                    picks_raw = my_team.get("picks", [])
                    my_team_picks = picks_raw
                    bank = my_team.get("transfers", {}).get("bank", 0) or 0
                    free_transfers = my_team.get("transfers", {}).get("free", 1) or 1
                    chips = my_team.get("chips", [])
                    chips_available = [c.get("name", "").lower().replace(" ", "_") for c in chips if c.get("status") == "available"]
                    if not chips_available:
                        chips_available = ["none"]
                except Exception as e2:
                    logger.warning("Cookie-only auth also failed: %s; using placeholder squad.", e2)
                    session = None
                    my_team = None
                    placeholder_ids = _resolve_placeholder_squad(bootstrap.get("elements", []))
                    my_team_picks = [{"element": eid} for eid in placeholder_ids]
            else:
                logger.warning("Could not fetch my-team (login or my-team failed: %s); using placeholder squad for dry-run.", e)
                session = None
                my_team = None
                placeholder_ids = _resolve_placeholder_squad(bootstrap.get("elements", []))
                my_team_picks = [{"element": eid} for eid in placeholder_ids]
    else:
        logger.warning("FPL_EMAIL/FPL_PASSWORD not set; using placeholder squad (no my-team data).")
        placeholder_ids = _resolve_placeholder_squad(bootstrap.get("elements", []))
        my_team_picks = [{"element": eid} for eid in placeholder_ids]

    # If --require-team: stop here unless we have real team data (avoid using LLM with placeholder)
    if args.require_team and my_team is None:
        logger.error(
            "Real team data could not be fetched (login and cookie fallback failed or no credentials). "
            "Stopping so the LLM is not called with placeholder data."
        )
        logger.error(
            "Next step: DevTools → Application → Cookies → select *fantasy.premierleague.com* (not .premierleague.com). "
            "While logged in, copy every cookie from that origin into FPL_COOKIE (name1=value1; name2=value2; ...). "
            "If that origin has no cookies, FPL may not support scripted access. See README 'Fix 403' or remove --require-team."
        )
        sys.exit(1)

    my_squad_element_ids = {p["element"] for p in my_team_picks}

    model_name = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    decisions: GameweekDecisions = get_decisions(
        api_key=api_key,
        gameweek=gameweek,
        my_team_picks=my_team_picks,
        bank=bank,
        free_transfers=free_transfers,
        chips_available=chips_available,
        player_scores=player_scores,
        my_squad_element_ids=my_squad_element_ids,
        fixtures_summary=fixtures_summary,
        model_name=model_name,
    )

    if apply_changes and session and my_team is not None:
        run_apply(session, manager_id, gameweek, decisions, my_team, elements)
    else:
        run_dry_run(decisions, gameweek, elements=elements)
        if apply_changes and not session:
            logger.info("Use FPL_EMAIL and FPL_PASSWORD with --apply to apply changes.")


if __name__ == "__main__":
    main()
