"""Temporary script to test FPL auth only. Reads .env like the main script. Delete when done."""
import os
import sys

from dotenv import load_dotenv

# Ensure package is importable when run from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from autofpl.fpl_client import get_my_team, login, session_from_cookie


def main() -> None:
    load_dotenv()
    email = (os.getenv("FPL_EMAIL") or "").strip()
    password = (os.getenv("FPL_PASSWORD") or "").strip()
    manager_id_str = (os.getenv("FPL_MANAGER_ID") or "").strip()
    cookie = (os.getenv("FPL_COOKIE") or "").strip()

    if not manager_id_str:
        print("ERROR: FPL_MANAGER_ID not set in .env")
        sys.exit(1)
    try:
        manager_id = int(manager_id_str)
    except ValueError:
        print("ERROR: FPL_MANAGER_ID must be an integer")
        sys.exit(1)

    print("Testing FPL auth (using .env)...")
    print(f"  FPL_MANAGER_ID = {manager_id}")
    print(f"  FPL_EMAIL set = {bool(email)}")
    print(f"  FPL_PASSWORD set = {bool(password)}")
    print(f"  FPL_COOKIE set = {bool(cookie)}")
    print()

    # 1) Try email/password login
    if email and password:
        print("1) Trying email/password login...")
        try:
            session = login(email, password)
            my_team = get_my_team(session, manager_id)
            print("   SUCCESS: Got my-team via login.")
            print(f"   Picks: {len(my_team.get('picks', []))} players, bank: {my_team.get('transfers', {}).get('bank', 0)}")
            sys.exit(0)
        except Exception as e:
            print(f"   FAILED: {e}")
    else:
        print("1) Skipping email/password (FPL_EMAIL or FPL_PASSWORD not set)")

    # 2) Try cookie-only
    if cookie:
        print("2) Trying cookie-only auth (FPL_COOKIE)...")
        try:
            session = session_from_cookie(cookie)
            my_team = get_my_team(session, manager_id)
            print("   SUCCESS: Got my-team via cookie.")
            print(f"   Picks: {len(my_team.get('picks', []))} players, bank: {my_team.get('transfers', {}).get('bank', 0)}")
            sys.exit(0)
        except Exception as e:
            print(f"   FAILED: {e}")
    else:
        print("2) Skipping cookie (FPL_COOKIE not set)")

    print()
    print("All auth methods failed. Check README 'Fix 403' and ensure cookies are from fantasy.premierleague.com.")
    sys.exit(1)


if __name__ == "__main__":
    main()
