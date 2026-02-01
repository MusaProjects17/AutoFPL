"""Decision schema: Pydantic models for LLM output (transfers, captain, chip, subs)."""

from enum import Enum

from pydantic import BaseModel, Field


class ChipType(str, Enum):
    NONE = "none"
    WILDCARD = "wildcard"
    FREE_HIT = "free_hit"
    BENCH_BOOST = "bench_boost"
    TRIPLE_CAPTAIN = "triple_captain"


class TransferDecision(BaseModel):
    """One transfer: element_out (sell), element_in (buy)."""

    element_out: int = Field(..., description="FPL element id of player to transfer out")
    element_in: int = Field(..., description="FPL element id of player to transfer in")


class GameweekDecisions(BaseModel):
    """Full set of decisions for one gameweek."""

    transfers: list[TransferDecision] = Field(default_factory=list, description="List of transfers (can be empty)")
    captain_id: int | None = Field(None, description="FPL element id of captain")
    vice_captain_id: int | None = Field(None, description="FPL element id of vice captain")
    chip: ChipType = Field(ChipType.NONE, description="Chip to play this gameweek")
    reasoning: str = Field("", description="Short reasoning for the decisions (chain of thought summary)")

    def transfers_for_api(self) -> list[dict]:
        """List of {element_out, element_in} for the FPL client."""
        return [{"element_out": t.element_out, "element_in": t.element_in} for t in self.transfers]


def parse_decisions_from_json(json_str: str) -> GameweekDecisions:
    """Parse and validate LLM JSON output into GameweekDecisions. Raises ValueError on invalid JSON/schema."""
    import json
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    # Normalise chip string to enum
    chip = data.get("chip", "none")
    if isinstance(chip, str):
        chip = chip.lower().replace(" ", "_").replace("-", "_")
        data = {**data, "chip": chip}
    return GameweekDecisions.model_validate(data)
