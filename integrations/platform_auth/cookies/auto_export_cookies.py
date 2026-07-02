#!/usr/bin/env python3
"""Automated cookie export using Playwright.

When you run this script, you explicitly authorize it to export cookies
from your logged-in browser session. This is automation of a manual process,
not unauthorized extraction.
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: Playwright not installed.")
    print("Install with: pip install playwright")
    print("Then run: playwright install chromium")
    exit(1)


PLATFORMS = {
    "douyin": {
        "name": "抖音",
        "url": "https://www.douyin.com",
        "domains": [".douyin.com"],
        "wait_selector": "//div[contains(@class, 'container')]",
    },
    "xiaohongshu": {
        "name": "小红书",
        "url": "https://www.xiaohongshu.com",
        "domains": [".xiaohongshu.com", ".xhscdn.com"],
        "wait_selector": "//div[contains(@class, 'container')]",
    },
}


def export_cookies(platform_key: str, output_dir: Path, headless: bool = False, use_existing_browser: bool = True, login_wait: int = 30):
    """Export cookies for a platform using Playwright."""
    platform = PLATFORMS[platform_key]
    output_file = output_dir / f"{platform_key}-cookies.json"

    print(f"\n{'='*60}")
    print(f"Exporting {platform['name']} cookies...")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        if use_existing_browser:
            # Connect to existing Chrome browser with CDP
            print("Trying to connect to existing Chrome browser...")
            print("Please make sure Chrome is running with remote debugging enabled.")
            print("If not, the script will launch a new browser.\n")

            try:
                # Try to connect to Chrome on default debugging port
                browser = p.chromium.connect_over_cdp("http://localhost:9222")
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
                print("✓ Connected to existing Chrome browser")
            except Exception as e:
                print(f"Could not connect to existing browser: {e}")
                print("Launching new browser (you'll need to log in)...\n")
                use_existing_browser = False

        if not use_existing_browser:
            # Launch browser with longer timeout and no proxy
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-proxy-server',
                ],
                env={
                    **os.environ,
                    'HTTP_PROXY': '',
                    'HTTPS_PROXY': '',
                    'ALL_PROXY': '',
                    'http_proxy': '',
                    'https_proxy': '',
                    'all_proxy': '',
                }
            )
            context = browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                proxy=None,  # Explicitly disable proxy
            )
            page = context.new_page()

        # Navigate to platform with timeout
        print(f"Navigating to {platform['url']}...")
        try:
            page.goto(platform["url"], wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation error: {e}")
            print("Trying with load event instead...")
            page.goto(platform["url"], wait_until="load", timeout=30000)

        # Wait a bit for page to fully load
        try:
            page.wait_for_selector(platform["wait_selector"], timeout=5000)
        except Exception:
            pass  # Continue even if selector not found

        if not use_existing_browser:
            print("\n" + "="*60)
            print("PLEASE LOG IN NOW")
            print("="*60)
            print(f"1. Log in to {platform['name']} in the browser window")
            print(f"2. Waiting {login_wait} seconds for you to log in...")
            print("="*60 + "\n")
            page.wait_for_timeout(login_wait * 1000)  # Convert to milliseconds

        print("Waiting for page to stabilize...")
        page.wait_for_timeout(3000)

        # Check if logged in by looking for cookies
        all_cookies = context.cookies()
        platform_cookies = [
            c
            for c in all_cookies
            if any(domain in c.get("domain", "") for domain in platform["domains"])
        ]

        if not platform_cookies:
            print(f"\n⚠️  Warning: No {platform['name']} cookies found!")
            print("You may not be logged in. Please:")
            print(f"1. Open {platform['url']} in your browser")
            print("2. Log in to your account")
            print("3. Run this script again")
            browser.close()
            return False

        # Save cookies in Cookie-Editor JSON format
        cookie_editor_format = [
            {
                "domain": c.get("domain", ""),
                "expirationDate": c.get("expires", -1),
                "hostOnly": not c.get("domain", "").startswith("."),
                "httpOnly": c.get("httpOnly", False),
                "name": c.get("name", ""),
                "path": c.get("path", "/"),
                "sameSite": c.get("sameSite", "no_restriction"),
                "secure": c.get("secure", False),
                "session": c.get("expires", -1) == -1,
                "storeId": None,
                "value": c.get("value", ""),
            }
            for c in platform_cookies
        ]

        # Write to file
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(cookie_editor_format, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"✓ Exported {len(platform_cookies)} cookies")
        print(f"✓ Saved to: {output_file}")

        browser.close()
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Export platform cookies using Playwright (requires user authorization)"
    )
    parser.add_argument(
        "--platform",
        choices=["all", "douyin", "xiaohongshu"],
        default="all",
        help="Which platform to export",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "Downloads",
        help="Output directory for cookie files",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no GUI)",
    )
    parser.add_argument(
        "--no-existing-browser",
        action="store_true",
        help="Don't try to connect to existing Chrome, launch new browser instead",
    )
    parser.add_argument(
        "--login-wait",
        type=int,
        default=30,
        help="Seconds to wait for manual login (default: 30)",
    )
    parser.add_argument(
        "--save-secrets",
        action="store_true",
        help="Automatically run save_platform_cookie_secret.py after export",
    )
    args = parser.parse_args()

    platforms = (
        ["douyin", "xiaohongshu"] if args.platform == "all" else [args.platform]
    )

    print("\n" + "="*60)
    print("AUTOMATED COOKIE EXPORT")
    print("="*60)
    print("\nYou are explicitly authorizing this script to export cookies")
    print("from your logged-in browser session.")
    print("\nIMPORTANT: Make sure you are logged in to the platforms first!")
    print("="*60)

    success_count = 0
    for platform_key in platforms:
        if export_cookies(platform_key, args.output_dir, args.headless, not args.no_existing_browser, args.login_wait):
            success_count += 1

    print(f"\n{'='*60}")
    print(f"Export complete: {success_count}/{len(platforms)} successful")
    print(f"{'='*60}\n")

    if success_count > 0:
        print("Next steps:")
        if args.save_secrets:
            print("Running save_platform_cookie_secret.py...")
            import subprocess
            result = subprocess.run(
                ["python3", "save_platform_cookie_secret.py"],
                cwd=Path(__file__).parent,
                timeout=int(os.getenv("COOKIE_SECRET_SAVE_TIMEOUT_SECONDS", "120")),
            )
            if result.returncode == 0:
                print("\n✓ Cookies saved to secrets/ and private/")
        else:
            print("1. Run: python3 save_platform_cookie_secret.py")
            print("2. Or run this script with --save-secrets flag")

        print(f"\nExported files in: {args.output_dir}")
        print("You can delete them after running save_platform_cookie_secret.py")


if __name__ == "__main__":
    main()
