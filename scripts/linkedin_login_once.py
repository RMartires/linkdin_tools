#!/usr/bin/env python3
"""
One-time LinkedIn login into the persistent Playwright browser profile.

Run this once (and again when LinkedIn expires the session). Complete login / 2FA
manually in the opened Chrome window. The profile is saved under
LINKEDIN_BROWSER_PROFILE_DIR (default: .linkedin_browser_profile/).

Usage:
    python scripts/linkedin_login_once.py
    python scripts/linkedin_login_once.py --timeout 900
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.session_manager import LinkedInNotLoggedInError, SessionManager
from src.utils.logger import logger


async def main():
    parser = argparse.ArgumentParser(
        description="Log into LinkedIn once in the persistent automation profile"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Seconds to wait for manual login (default: 600)",
    )
    parser.add_argument(
        "--profile-dir",
        type=str,
        default=None,
        help="Override LINKEDIN_BROWSER_PROFILE_DIR",
    )
    args = parser.parse_args()

    if args.profile_dir:
        import os

        os.environ["LINKEDIN_BROWSER_PROFILE_DIR"] = args.profile_dir

    sm = SessionManager()
    print("=" * 60)
    print("LinkedIn persistent profile login")
    print("=" * 60)
    print(f"Profile directory: {sm.user_data_dir}")
    print()
    print("A Chrome window will open. Sign in to LinkedIn (and complete 2FA).")
    print("Do not close the window until this script reports success.")
    print()

    page = None
    try:
        page = await sm.get_page(headless=False)
        await page.goto(
            "https://www.linkedin.com/login",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await sm.wait_for_manual_login(page, timeout_seconds=args.timeout)
        print()
        print(f"✓ Logged in. Session saved to: {sm.user_data_dir}")
        print()
        print("You can now run scraping:")
        print('  python main.py --keywords "senior software engineer" --location "Dubai"')
        print()
        print("Re-run this script if you see Sign in / guest walls again.")
    except LinkedInNotLoggedInError as e:
        print(f"\n✗ Login failed: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    finally:
        await sm.close()


if __name__ == "__main__":
    asyncio.run(main())
