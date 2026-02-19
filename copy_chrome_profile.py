#!/usr/bin/env python3
"""Copy Chrome profile data to BROWSER_USER_DATA_DIR"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# Try to load dotenv if available, otherwise use env vars directly
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Use environment variables directly

def get_chrome_profile_path():
    """Get Chrome profile path based on OS"""
    system = sys.platform
    
    if system == "darwin":  # macOS
        chrome_profile = Path.home() / "Library/Application Support/Google/Chrome/Default"
    elif system == "linux":
        chrome_profile = Path.home() / ".config/google-chrome/Default"
    elif system == "win32":
        chrome_profile = Path(os.environ.get("LOCALAPPDATA")) / "Google/Chrome/User Data/Default"
    else:
        raise OSError(f"Unsupported OS: {system}")
    
    return chrome_profile

def check_chrome_running():
    """Check if Chrome is running"""
    system = sys.platform
    
    try:
        if system == "darwin":
            result = subprocess.run(["pgrep", "-x", "Google Chrome"], 
                                  capture_output=True, text=True)
            return result.returncode == 0
        elif system == "linux":
            result = subprocess.run(["pgrep", "-x", "chrome"], 
                                  capture_output=True, text=True)
            return result.returncode == 0
        elif system == "win32":
            result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"], 
                                  capture_output=True, text=True)
            return "chrome.exe" in result.stdout
        else:
            return False
    except Exception:
        return False

def copy_chrome_profile(force=False):
    """Copy Chrome profile to BROWSER_USER_DATA_DIR"""
    # Get target directory from env
    target_dir = os.getenv('BROWSER_USER_DATA_DIR')
    if not target_dir:
        project_root = Path(__file__).parent
        target_dir = str(project_root / '.browser_data')
    
    target_path = Path(target_dir).expanduser().resolve()
    chrome_profile = get_chrome_profile_path()
    
    print("=" * 60)
    print("Chrome Profile Copy Script")
    print("=" * 60)
    print(f"Chrome Profile: {chrome_profile}")
    print(f"Target Directory: {target_path}")
    print()
    
    # Check if Chrome profile exists
    if not chrome_profile.exists():
        print(f"❌ Error: Chrome profile not found at: {chrome_profile}")
        print("Please check your Chrome installation.")
        return False
    
    # Check if Chrome is running
    if check_chrome_running():
        print("⚠️  Warning: Chrome appears to be running!")
        print("Please close Chrome completely before copying profile data.")
        print()
        if not force:
            response = input("Continue anyway? (y/N): ")
            if response.lower() != 'y':
                print("Cancelled.")
                return False
        else:
            print("Continuing with --force flag...")
        print()
    
    # Create target directory
    target_path.mkdir(parents=True, exist_ok=True)
    print(f"✓ Created target directory: {target_path}")
    print()
    
    # Files to copy
    files_to_copy = [
        "Cookies",
        "Preferences",
    ]
    
    # Directories to copy
    dirs_to_copy = [
        "Local Storage",
        "Session Storage",
    ]
    
    print("Copying Chrome profile data...")
    print()
    
    copied_count = 0
    failed_count = 0
    
    # Copy files
    for file_name in files_to_copy:
        source_file = chrome_profile / file_name
        if source_file.exists():
            try:
                print(f"✓ Copying {file_name}...", end=" ")
                dest_file = target_path / file_name
                shutil.copy2(source_file, dest_file)
                print("✓ Done")
                copied_count += 1
            except PermissionError:
                print(f"❌ Permission denied (file may be locked)")
                failed_count += 1
            except Exception as e:
                print(f"❌ Error: {e}")
                failed_count += 1
        else:
            print(f"⚠️  {file_name} not found, skipping...")
    
    # Copy directories
    for dir_name in dirs_to_copy:
        source_dir = chrome_profile / dir_name
        if source_dir.exists():
            try:
                print(f"✓ Copying {dir_name}/...", end=" ")
                dest_dir = target_path / dir_name
                if dest_dir.exists():
                    shutil.rmtree(dest_dir)
                shutil.copytree(source_dir, dest_dir)
                print("✓ Done")
                copied_count += 1
            except PermissionError:
                print(f"❌ Permission denied (directory may be locked)")
                failed_count += 1
            except Exception as e:
                print(f"❌ Error: {e}")
                failed_count += 1
        else:
            print(f"⚠️  {dir_name} not found, skipping...")
    
    # Set permissions
    try:
        print()
        print("Setting permissions...", end=" ")
        os.chmod(target_path, 0o755)
        for root, dirs, files in os.walk(target_path):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o755)
            for f in files:
                os.chmod(os.path.join(root, f), 0o644)
        print("✓ Done")
    except Exception as e:
        print(f"⚠️  Warning: Could not set permissions: {e}")
    
    print()
    print("=" * 60)
    if failed_count == 0:
        print(f"✅ Successfully copied {copied_count} items to: {target_path}")
    else:
        print(f"⚠️  Copied {copied_count} items, {failed_count} failed")
        print("Some files may be locked. Try closing Chrome completely and run again.")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Run: python main.py --keywords 'test' --max-results 1")
    print("2. Verify you're logged into LinkedIn automatically")
    print()
    
    return failed_count == 0

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Copy Chrome profile to BROWSER_USER_DATA_DIR")
    parser.add_argument('--force', '-f', action='store_true', 
                       help='Skip confirmation prompts')
    args = parser.parse_args()
    
    try:
        success = copy_chrome_profile(force=args.force)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
