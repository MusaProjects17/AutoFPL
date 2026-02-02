"""Executor: dry-run (log only) or apply (POST transfers and lineup) with idempotency check."""

import logging
from typing import Any

from autofpl.decisions import ChipType, GameweekDecisions
from autofpl.fpl_client import get_my_team, get_transfers, post_team, post_transfer

logger = logging.getLogger(__name__)


def _picks_with_captaincy(my_team_picks: list[dict], captain_id: int | None, vice_captain_id: int | None) -> list[dict[str, Any]]:
    """Return picks list with captain/vice set. FPL expects element, position, is_captain, is_vice_captain."""
    out = []
    for p in my_team_picks:
        eid = p.get("element")
        out.append({
            "element": eid,
            "position": p.get("position", 0),
            "is_captain": eid == captain_id if captain_id else p.get("is_captain", False),
            "is_vice_captain": eid == vice_captain_id if vice_captain_id else p.get("is_vice_captain", False),
        })
    return out


def _chip_api_value(chip: ChipType) -> str | None:
    """Map ChipType to FPL API chip value (for transfer: wildcard/freehit; for team: bboost/3xc)."""
    if chip == ChipType.WILDCARD:
        return "wildcard"
    if chip == ChipType.FREE_HIT:
        return "freehit"
    if chip == ChipType.BENCH_BOOST:
        return "bboost"
    if chip == ChipType.TRIPLE_CAPTAIN:
        return "3xc"
    return None


def already_made_transfers_this_gw(session: Any, manager_id: int, gameweek: int) -> bool:
    """Return True if user has already made transfers in this gameweek (idempotency)."""
    try:
        transfers = get_transfers(session, manager_id)
        for t in transfers:
            if t.get("event") == gameweek:
                return True
    except Exception:
        pass
    return False


def _element_id_to_name(elements: list[dict] | None) -> dict[int, str]:
    """Build element_id -> web_name for human-readable output."""
    if not elements:
        return {}
    return {int(e["id"]): e.get("web_name", str(e["id"])) for e in elements if e.get("id") is not None}


def run_dry_run(
    decisions: GameweekDecisions,
    gameweek: int,
    elements: list[dict] | None = None,
) -> None:
    """Log decisions without calling FPL API. If elements is provided, show player names."""
    id_to_name = _element_id_to_name(elements)
    def _name(eid: int | None) -> str:
        if eid is None:
            return "—"
        return id_to_name.get(eid, str(eid))

    logger.info("Dry-run: gameweek %s decisions", gameweek)
    logger.info("  reasoning: %s", decisions.reasoning)
    logger.info("  chip: %s", decisions.chip.value)
    logger.info("  captain: %s (%s)", _name(decisions.captain_id), decisions.captain_id)
    logger.info("  vice_captain: %s (%s)", _name(decisions.vice_captain_id), decisions.vice_captain_id)
    for t in decisions.transfers:
        logger.info("  transfer out %s (%s) -> in %s (%s)", _name(t.element_out), t.element_out, _name(t.element_in), t.element_in)


def run_apply(
    session: Any,
    manager_id: int,
    gameweek: int,
    decisions: GameweekDecisions,
    my_team: dict[str, Any],
    elements: list[dict[str, Any]],
) -> None:
    """
    Apply decisions to FPL: POST transfers (with prices), then POST lineup (captain/vice/chip).
    Skips if transfers already made this GW (idempotency).
    """
    if already_made_transfers_this_gw(session, manager_id, gameweek):
        logger.warning("Transfers already made for gameweek %s; skipping apply.", gameweek)
        return

    picks = my_team.get("picks", [])
    pick_by_element: dict[int, dict] = {p["element"]: p for p in picks}

    elements_by_id = {int(e["id"]): e for e in elements}

    # Build transfer payload with purchase_price and selling_price
    transfer_chip = None
    if decisions.chip in (ChipType.WILDCARD, ChipType.FREE_HIT):
        transfer_chip = _chip_api_value(decisions.chip)

    transfers_payload: list[dict[str, Any]] = []
    for t in decisions.transfers:
        sell_pick = pick_by_element.get(t.element_out)
        buy_elem = elements_by_id.get(t.element_in)
        if not sell_pick or not buy_elem:
            logger.error("Missing pick or element for transfer out=%s in=%s", t.element_out, t.element_in)
            continue
        selling_price = sell_pick.get("selling_price", sell_pick.get("purchase_price", 0))
        purchase_price = buy_elem.get("now_cost", 0)
        transfers_payload.append({
            "element_out": t.element_out,
            "element_in": t.element_in,
            "selling_price": selling_price,
            "purchase_price": purchase_price,
        })

    if transfers_payload:
        # FPL: first POST with confirmed=False to validate, then confirmed=True
        post_transfer(session, manager_id, gameweek, transfers_payload, chip=transfer_chip, confirmed=False)
        post_transfer(session, manager_id, gameweek, transfers_payload, chip=transfer_chip, confirmed=True)
        logger.info("Applied %s transfer(s).", len(transfers_payload))
        # Refetch team so picks reflect new squad for lineup POST
        my_team = get_my_team(session, manager_id)
        picks = my_team.get("picks", [])

    # Lineup: captain, vice, chip (bboost/3xc)
    lineup_picks = _picks_with_captaincy(picks, decisions.captain_id, decisions.vice_captain_id)
    lineup_chip = None
    if decisions.chip in (ChipType.BENCH_BOOST, ChipType.TRIPLE_CAPTAIN):
        lineup_chip = _chip_api_value(decisions.chip)
    post_team(session, manager_id, lineup_picks, chip=lineup_chip)
    logger.info("Applied lineup (captain=%s, vice=%s, chip=%s).", decisions.captain_id, decisions.vice_captain_id, lineup_chip)
