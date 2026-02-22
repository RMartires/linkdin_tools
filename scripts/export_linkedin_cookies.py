#!/usr/bin/env python3
"""
Export LinkedIn cookies from Chrome to Playwright storage state format.

Run this script once (and again when your LinkedIn session expires) to enable
the automation to use your logged-in LinkedIn session.

Requirements:
- macOS only (uses Keychain for cookie decryption)
- Google Chrome with LinkedIn logged in
- Full Disk Access for Terminal (System Settings → Privacy & Security → Full Disk Access)

Usage:
    python scripts/export_linkedin_cookies.py

    # Or with custom profile/output:
    python scripts/export_linkedin_cookies.py --profile "Profile 3" --output linkedin_storage_state.json
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Export LinkedIn cookies from Chrome for Playwright automation"
    )
    parser.add_argument(
        "--profile", "-p",
        default=os.getenv("BROWSER_PROFILE_DIRECTORY", "Default"),
        help="Chrome profile name (e.g., 'Profile 3', 'Default')",
    )
    parser.add_argument(
        "--output", "-o",
        default=os.getenv("LINKEDIN_STORAGE_STATE", "linkedin_storage_state.json"),
        help="Output file path for Playwright storage state",
    )
    parser.add_argument(
        "--domain", "-d",
        default="linkedin.com",
        help="Filter cookies by domain (default: linkedin.com)",
    )
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    print(f"Exporting LinkedIn cookies from Chrome profile '{args.profile}'...")
    print(f"Output: {output_path}")
    print()

    try:
        # Use python -m to ensure we use the venv's installed package
        result = subprocess.run(
            [
                sys.executable, "-m", "chrome_cookies_to_playwright.main",
                "--profile", args.profile,
                "--domain", args.domain,
                "--output", str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            print("Error exporting cookies:", file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            if "Full Disk Access" in (result.stderr or ""):
                print(
                    "\nTip: On macOS, grant Full Disk Access to Terminal in "
                    "System Settings → Privacy & Security → Full Disk Access",
                    file=sys.stderr,
                )
            sys.exit(1)

        print(f"✓ Cookies exported successfully to {output_path}")
        print()
        print("You can now run the automation:")
        print("  python main.py --keywords 'software engineer' --location 'Dubai'")
        print()
        print("Re-run this script when your LinkedIn session expires (typically every few weeks).")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
