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
)
from autofpl.llm import get_decisions
from autofpl.scoring import enrich_players_with_scores


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(description="AutoFPL: fetch data, LLM decisions, optional apply.")
    parser.add_argument("--dry-run", action="store_true", help="Only log decisions (default if --apply not set)")
    parser.add_argument("--apply", action="store_true", help="Apply decisions to FPL account")
    parser.add_argument("--gw", type=int, default=None, help="Gameweek (default: next GW from API)")
    args = parser.parse_args()
    apply_changes = args.apply  # default is dry-run when --apply not passed

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
            logger.warning("Could not fetch my-team (login or my-team failed: %s); using placeholder squad for dry-run.", e)
            session = None
            my_team = None
            my_squad_element_ids = set()
            for p in bootstrap.get("elements", [])[:15]:
                eid = p.get("id")
                if eid is not None:
                    my_squad_element_ids.add(int(eid))
            my_team_picks = [{"element": eid} for eid in my_squad_element_ids]
    else:
        logger.warning("FPL_EMAIL/FPL_PASSWORD not set; using placeholder squad (no my-team data).")
        my_squad_element_ids = set()
        for p in bootstrap.get("elements", [])[:15]:
            eid = p.get("id")
            if eid is not None:
                my_squad_element_ids.add(int(eid))
        my_team_picks = [{"element": eid} for eid in my_squad_element_ids]

    my_squad_element_ids = {p["element"] for p in my_team_picks}

    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
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
        run_dry_run(decisions, gameweek)
        if apply_changes and not session:
            logger.info("Use FPL_EMAIL and FPL_PASSWORD with --apply to apply changes.")


if __name__ == "__main__":
    main()
