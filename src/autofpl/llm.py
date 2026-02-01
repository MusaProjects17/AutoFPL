"""LLM module: Gemini client, chain-of-thought prompt, structured JSON output."""

import json
import re
import time
from typing import Any

import google.generativeai as genai

from autofpl.decisions import GameweekDecisions, parse_decisions_from_json


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
            squad_desc.append(
                f"  id={p['id']} {p['web_name']} cost={p.get('now_cost')} pts={p.get('total_points')} "
                f"value_index={p.get('value_index')} form={p.get('form_score')} fixture_diff={p.get('fixture_difficulty')}"
            )
    squad_text = "\n".join(squad_desc) if squad_desc else " (none )"
    all_players_text = json.dumps(player_scores[:400], indent=0)  # cap size for context

    return f"""You are an expert Fantasy Premier League (FPL) manager. Decide the best moves for gameweek {gameweek}.

Rules:
- Budget: bank = {bank/10:.1f}M (FPL stores in 0.1M units). Max 3 players per Premier League team.
- You have {free_transfers} free transfer(s). Each extra transfer costs 4 points.
- Chips available: {chips_available}. Use chip only if it is clearly optimal (e.g. wildcard for many changes, bench_boost when bench is strong).
- Captain and vice_captain must be from your 15-man squad. Prefer high form and easy fixtures.

First reason step-by-step (chain of thought): who to transfer out and why, who to bring in, captain choice, chip use. Then output exactly one JSON object with no extra text before or after, using this schema:

{{
  "transfers": [{{"element_out": <id>, "element_in": <id>}}, ...],
  "captain_id": <element_id or null>,
  "vice_captain_id": <element_id or null>,
  "chip": "none" | "wildcard" | "free_hit" | "bench_boost" | "triple_captain",
  "reasoning": "<short summary>"
}}

Your current squad (element ids and stats):
{squad_text}

Upcoming fixtures (gameweek {gameweek}):
{fixtures_summary}

All players with precomputed stats (id, web_name, element_type, team, now_cost, total_points, value_index, form_score, fixture_difficulty):
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
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
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
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            if not response.text:
                raise ValueError("Empty response from model")
            raw = extract_json_block(response.text)
            return parse_decisions_from_json(raw)
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "quota" in err_str or "resourcelimit" in err_str:
                if attempt < 2:
                    time.sleep(40)
                    continue
            raise
    raise ValueError("Failed to get decisions after retries")
