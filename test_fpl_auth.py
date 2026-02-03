"""Test FPL authorization (X-Api-Authorization token only). Reads .env like the main script."""
import os
import sys

from dotenv import load_dotenv

# Ensure package is importable when run from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from autofpl.fpl_client import get_my_team, session_from_bearer_token


def main() -> None:
    load_dotenv()
    bearer = (os.getenv("FPL_ACCESS_TOKEN") or "").strip()
    manager_id_str = (os.getenv("FPL_MANAGER_ID") or "").strip()

    if not bearer:
        print("ERROR: FPL_ACCESS_TOKEN not set in .env")
        print("  Get it from DevTools → Network → Pick Team → filter 'my-team' → Headers → X-Api-Authorization")
        sys.exit(1)
    if not manager_id_str:
        print("ERROR: FPL_MANAGER_ID not set in .env")
        sys.exit(1)
    try:
        manager_id = int(manager_id_str)
    except ValueError:
        print("ERROR: FPL_MANAGER_ID must be an integer")
        sys.exit(1)

    print("Testing FPL authorization (X-Api-Authorization token)...")
    print(f"  FPL_MANAGER_ID = {manager_id}")
    print(f"  FPL_ACCESS_TOKEN set (never commit; .env only)")
    print()

    try:
        session = session_from_bearer_token(bearer)
        my_team = get_my_team(session, manager_id)
        print("SUCCESS: X-Api-Authorization token OK.")
        print(f"  Picks: {len(my_team.get('picks', []))} players, bank: {my_team.get('transfers', {}).get('bank', 0)}")
        sys.exit(0)
    except Exception as e:
        print(f"FAILED: {e}")
        print("  Token may be expired. Get a fresh value from DevTools (see README).")
        sys.exit(1)


if __name__ == "__main__":
    main()
