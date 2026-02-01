# AutoFPL

Automated Fantasy Premier League pipeline: fetch FPL data, compute custom scores, get LLM (Gemini) decisions, and optionally apply them to your team. Supports dry-run by default.

## Setup

1. **UV and environment**
   ```bash
   uv sync
   ```

2. **Environment variables**  
   Copy `.env.example` to `.env` and set:
   - `FPL_EMAIL` – FPL account email
   - `FPL_PASSWORD` – FPL account password
   - `FPL_MANAGER_ID` – Your FPL entry ID (from the URL on the Points tab, e.g. `https://fantasy.premierleague.com/entry/12345/event/2` → `12345`)
   - `GOOGLE_AI_API_KEY` – API key from [Google AI Studio](https://aistudio.google.com/apikey) (Gemini). The script uses the `google-generativeai` package; Google recommends migrating to `google.genai` in future.
- `GEMINI_MODEL` (optional) – Model name, e.g. `gemini-2.0-flash` (default), `gemini-2.5-flash`. Use a model that has free-tier quota in your region.

3. **Run**
   - Dry-run (default; no changes to your team):
     ```bash
     uv run python main.py
     ```
     or
     ```bash
     uv run autofpl
     ```
   - Apply decisions to your FPL team:
     ```bash
     uv run python main.py --apply
     ```
   - Use a specific gameweek:
     ```bash
     uv run python main.py --gw 5
     ```

## Scheduling (run before each gameweek)

Run the script shortly before the gameweek deadline (e.g. 2–6 hours before). Options:

### GitHub Actions (cron)

A workflow runs on a schedule (e.g. Friday 18:00 UK). Add secrets in the repo: `FPL_EMAIL`, `FPL_PASSWORD`, `FPL_MANAGER_ID`, `GOOGLE_AI_API_KEY`. Use dry-run by default; to apply changes, set the workflow to pass `--apply` (e.g. via a secret or manual trigger).

### Deadline logic

The script uses the FPL API `bootstrap-static` → `events` to get the next gameweek and `deadline_time_epoch`. You can:

- Run on a fixed schedule (e.g. every Friday) so the run before each deadline picks up the correct GW.
- Add a check in your runner: only call the script if the next deadline is within the next N hours (using `deadline_time_epoch` from the API).

### AWS Lambda / other cloud

As in [this guide](https://conor-aspell.medium.com/updated-automatically-manage-your-fantasy-premier-league-team-with-python-and-aws-lambda-e92eebacd93f), you can deploy the script as a Lambda (or similar) and trigger it with EventBridge on a schedule. Store credentials in the platform’s secrets manager.

## Project layout

- `src/autofpl/` – Package: `fpl_client`, `scoring`, `decisions`, `llm`, `executor`, `main` (CLI)
- `main.py` – Entrypoint that calls the package
- `.env` – Local credentials (not committed; see `.env.example`)

## Idempotency

If you run with `--apply` more than once in the same gameweek, the executor skips applying transfers again (it checks transfer history for the current GW).

## Troubleshooting

- **FPL my-team returns 403:** The script falls back to a placeholder squad so the dry-run still runs; decisions use that placeholder. To fix: ensure `FPL_EMAIL` and `FPL_PASSWORD` match the account for `FPL_MANAGER_ID`; FPL may block some automated logins.
- **Gemini 429 (quota exceeded):** Your free-tier quota may be exhausted. Wait for the daily reset (Pacific Time) or try a different model via `GEMINI_MODEL` (e.g. `gemini-2.5-flash`). Check [Google AI Studio](https://aistudio.google.com/) and [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).
