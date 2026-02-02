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
   - `GOOGLE_AI_API_KEY` – API key from [Google AI Studio](https://aistudio.google.com/apikey) (Gemini). The script uses the `google-genai` package.
   - `GEMINI_MODEL` (optional) – Model name, e.g. `gemini-2.0-flash`, `gemini-2.5-flash`. Use a model that has free-tier quota in your region.
   - `FPL_COOKIE` (optional) – If you get **403** on my-team, use your browser cookie (see [Fix 403](#fix-403-on-my-team) below).

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
   - Require real team data (exit with error if login/cookie fails; no LLM call with placeholder):
     ```bash
     uv run python main.py --require-team
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

- **Gemini 429 (quota exceeded):** Your free-tier quota may be exhausted. Wait for the daily reset (Pacific Time) or try a different model via `GEMINI_MODEL` (e.g. `gemini-2.5-flash`). Check [Google AI Studio](https://aistudio.google.com/) and [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

### Fix 403 on my-team

FPL often returns **403 Forbidden** for `/api/my-team/{id}/` when the request doesn’t look like a real browser (e.g. scripted login). The script then falls back to your placeholder squad. To get your real team data:

**Step 1 – Check credentials**  
- `FPL_EMAIL` and `FPL_PASSWORD` must be correct and match the account for `FPL_MANAGER_ID`.  
- Use the same email you use on [fantasy.premierleague.com](https://fantasy.premierleague.com).

**Step 2 – Use browser cookie (recommended when Step 1 still gives 403)**  
1. Log into [fantasy.premierleague.com](https://fantasy.premierleague.com) in your browser (Chrome or Firefox).  
2. Open DevTools: **F12** (or right‑click → Inspect).  
3. Go to **Application** (Chrome) or **Storage** (Firefox) → **Cookies**.  
4. Copy the **full cookie string**. Include cookies from **fantasy.premierleague.com** (`pl_profile`, `sessionid`) and **.premierleague.com** (`access_token`, `refresh_token`, `datadome`). In Chrome you can use an extension like “EditThisCookie” to export, or copy manually: e.g. `pl_profile=...; sessionid=...`.  
5. In `.env` set one line: `FPL_COOKIE=access_token=...; refresh_token=...; datadome=...; pl_profile=...; sessionid=...` (use your actual values).  
6. Save and run again. The script will try normal login first; if that returns 403 it will then try **cookie-only** auth using `FPL_COOKIE`, so your browser session is used without calling the login endpoint.

**Step 3 – Cookie expiry**  
Browser cookies expire (e.g. after a few days or when you log out). If 403 comes back later, repeat Step 2 to refresh `FPL_COOKIE`.

**If you still get 401/403:** FPL auth may have changed: [Reddit](https://www.reddit.com/r/FantasyPL/) reports that "you have to pass a key through in the call instead" of session cookies. Include in `FPL_COOKIE` all cookies you see for **fantasy.premierleague.com** (e.g. `_spdt`) and **.premierleague.com** (`access_token`, `refresh_token`, `datadome`, `global_sso_id`). Try `FPL_USE_BEARER=1` in `.env` to send `access_token` as `Authorization: Bearer` (can give 401 if the API rejects it). If you find a working Python solution (e.g. from FPL Discord), we can add that method.

**References**  
- [FPL API endpoints – detailed guide](https://medium.com/@frenzelts/fantasy-premier-league-api-endpoints-a-detailed-guide-acbd5598eb19) (Medium) – confirms base URL `fantasy.premierleague.com/api/` and that my-team requires authentication; links to auth guide below.  
- [How to authenticate with the FPL API](https://www.reddit.com/r/FantasyPL/comments/15q6tgd/how_to_authenticate_with_the_fpl_api/) (Reddit) – use cookies from the browser when programmatic login is blocked.  
- [FPL API authentication guide](https://medium.com/@bram.vanherle1/fantasy-premier-league-api-authentication-guide-2f7aeb2382e4) (Medium) – POST to `users.premierleague.com/accounts/login/` and cookies `pl_profile`, `sessionid` for restricted endpoints.
