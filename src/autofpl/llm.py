"""LLM module: Gemini client, chain-of-thought prompt, structured JSON output."""

import json
import re
import time
from typing import Any

from google import genai
from google.genai import types

from autofpl.decisions import GameweekDecisions, parse_decisions_from_json

# Longer timeout for large prompts (3 minutes). Value in milliseconds.
GEMINI_TIMEOUT_MS = 180_000


def _build_prompt(
    gameweek: int,
    my_team_picks: list[dict[str, Any]],
    bank: int,
    free_transfers: int,
    chips_available: list[str],
    player_scores: list[dict[str, Any]],
    my_squad_element_ids: set[int],
    fixtures_summary: str,
) -> str:
    """Build the system + user prompt for the LLM."""
    squad_desc = []
    for p in player_scores:
        if p["id"] in my_squad_element_ids:
            chance = p.get("chance_of_playing_this_round")
            status = p.get("status", "")
            news = (p.get("news") or "")[:80]
            avail = f" status={status} chance={chance} news={news}" if (status or chance is not None or news) else ""
            squad_desc.append(
                f"  id={p['id']} {p['web_name']} cost={p.get('now_cost')} pts={p.get('total_points')} "
                f"value_index={p.get('value_index')} form={p.get('form_score')} fixture_diff={p.get('fixture_difficulty')}{avail}"
            )
    squad_text = "\n".join(squad_desc) if squad_desc else " (none )"
    all_players_text = json.dumps(player_scores[:400], indent=0)  # cap size for context

    return f"""You are an expert Fantasy Premier League (FPL) manager. Decide the best moves for gameweek {gameweek}.

Rules:
- Budget: bank = {bank/10:.1f}M (FPL stores in 0.1M units). Max 3 players per Premier League team.
- You have {free_transfers} free transfer(s). Each extra transfer costs 4 points.
- Chips available: {chips_available}. Use chip only if it is clearly optimal (e.g. wildcard for many changes, bench_boost when bench is strong).
- Captain and vice_captain must be from your 15-man squad. Prefer high form and easy fixtures.
- Availability (CRITICAL): FPL "status" can be "a" (available), "d" (doubtful), "i" (injured), "s" (suspended), "u" (unavailable). "news" often describes injury or suspension. "chance_of_playing_this_round" is 0-100 or null. You MUST prioritise transferring OUT any squad member who is injured, suspended, or has low chance (e.g. 0, 25, 50 or null when news suggests absence). Do not start injured/suspended players; bench them at minimum (CRITICAL:only if this is most optimal), and use free transfers to replace them with available players first before other transfers.
- Do not be afraid to spend all bank on transfers if it is most optimal.

First reason step-by-step (chain of thought): identify any squad players who are injured, suspended, or unlikely to play (check status, news, chance_of_playing_this_round); prioritise transferring them out. Then other transfers, captain choice, chip use, and which 11 players should start and which 4 on the bench (never start injured/suspended players). Then output exactly one JSON object with no extra text before or after, using this schema:

{{
  "transfers": [{{"element_out": <id>, "element_in": <id>}}, ...],
  "captain_id": <element_id or null>,
  "vice_captain_id": <element_id or null>,
  "chip": "none" | "wildcard" | "free_hit" | "bench_boost" | "triple_captain",
  "lineup_order": [<id1>, <id2>, ...] or null,
  "reasoning": "<short summary>"
}}

lineup_order: array of exactly 15 element IDs — your 15 squad members in the order you want them. Positions 1–11 = starting XI (1=GK, 2–5=DEF, 6–9=MID, 10–11=FWD or another valid formation), 12–15 = bench (12=GK, 13–15=outfield). Use the same 15 players as your squad (after any transfers). If you do not want to change who starts or bench order, set to null.

Your current squad (element ids and stats):
{squad_text}

Upcoming fixtures (gameweek {gameweek}):
{fixtures_summary}

All players with precomputed stats (id, web_name, element_type, team, now_cost, total_points, value_index, form_score, fixture_difficulty, chance_of_playing_this_round, status, news):
{all_players_text}

Output only the single JSON object, no markdown code block."""


def extract_json_block(text: str) -> str:
    """Extract a JSON object from the model response (handles markdown code blocks)."""
    text = text.strip()
    # Try raw JSON first
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return m.group(0)
    # Remove markdown code fence
    if "```json" in text:
        text = text.split("```json")[-1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip() if text.count("```") >= 2 else text
    return text.strip()


def get_decisions(
    api_key: str,
    gameweek: int,
    my_team_picks: list[dict[str, Any]],
    bank: int,
    free_transfers: int,
    chips_available: list[str],
    player_scores: list[dict[str, Any]],
    my_squad_element_ids: set[int],
    fixtures_summary: str,
    model_name: str = "gemini-2.5-flash",
) -> GameweekDecisions:
    """Call Gemini and return parsed GameweekDecisions."""
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
    )
    prompt = _build_prompt(
        gameweek=gameweek,
        my_team_picks=my_team_picks,
        bank=bank,
        free_transfers=free_transfers,
        chips_available=chips_available,
        player_scores=player_scores,
        my_squad_element_ids=my_squad_element_ids,
        fixtures_summary=fixtures_summary,
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if not response.text:
                raise ValueError("Empty response from model")
            raw = extract_json_block(response.text)
            return parse_decisions_from_json(raw)
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            is_retryable = (
                "429" in err_str
                or "quota" in err_str
                or "resourcelimit" in err_str
                or "504" in err_str
                or "deadline" in err_str
                or "timeout" in err_str
            )
            if is_retryable and attempt < 2:
                time.sleep(30 + attempt * 20)
                continue
            raise
    if last_error is not None:
        raise last_error
    raise ValueError("Failed to get decisions after retries")
