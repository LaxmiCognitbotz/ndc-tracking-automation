"""
Oracle Fusion - NDC Process Request Status Report Downloader
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Redirect stdout and stderr to a log file
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "download_ndc_report.log"

class LoggerWriter:
    def __init__(self, file_path):
        self.terminal = sys.stdout
        self.file_path = file_path
        self.new_line = True

    def write(self, message):
        self.terminal.write(message)
        try:
            with open(self.file_path, "a", encoding="utf-8") as f:
                for line in message.splitlines(keepends=True):
                    if self.new_line and line.strip():
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S ")
                        f.write(timestamp)
                    f.write(line)
                    self.new_line = line.endswith("\n")
        except Exception:
            pass

    def flush(self):
        self.terminal.flush()

sys.stdout = LoggerWriter(LOG_FILE)
sys.stderr = LoggerWriter(LOG_FILE)

load_dotenv(verbose=True)

# Oracle credentials
ORACLE_URL = os.getenv("ORACLE_URL")
ORACLE_EMAIL = os.getenv("ORACLE_EMAIL")
ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD")

# Output directory
DOWNLOAD_DIR = Path(__file__).parent.parent / "NDC_Reports"

# Standalone automation profile (persists Oracle session between headless runs)
AUTOMATION_PROFILE_DIR = Path(__file__).parent.parent / "chrome_automation_profile"

# Headless mode
HEADLESS = os.getenv("HEADLESS", "true").lower()

# Business unit
BUSINESS_UNIT_SEARCH = "Adani Green"

def ts():
    return datetime.now().strftime("%H:%M:%S")


def report_save_stem() -> str:
    """e.g. NDC_Process_Request_Status_10_June_2026_12.11PM"""
    now = datetime.now()
    return (
        f"NDC_Process_Request_Status_{now.day}_"
        f"{now.strftime('%B')}_{now.year}_{now.strftime('%I.%M%p')}"
    )


def _cleanup_profile_locks():
    """Remove Chrome lock files on the automation profile only."""
    lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"]
    if not AUTOMATION_PROFILE_DIR.exists():
        return
    for lock_name in lock_files:
        lock_path = AUTOMATION_PROFILE_DIR / lock_name
        try:
            if lock_path.exists():
                lock_path.unlink()
        except OSError:
            pass


async def save_debug_screenshot(page, label: str):
    path = DOWNLOAD_DIR / f"debug_{label}_{datetime.now().strftime('%H%M%S')}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"[{ts()}]   Screenshot: {path}")
    return str(path)


async def check_for_sso_errors(page):
    """Check if Microsoft SSO shows a validation error, and raise an exception if found."""
    # Check standard error IDs used by Microsoft login
    for error_id in ["usernameError", "passwordError", "error"]:
        try:
            loc = page.locator(f"#{error_id}").first
            if await loc.is_visible(timeout=1000):
                err_text = await loc.inner_text()
                err_text = err_text.strip().replace("\n", " ")
                if err_text:
                    raise RuntimeError(f"Microsoft SSO Error: {err_text}")
        except RuntimeError:
            raise
        except Exception:
            pass

    # Check for general alert roles
    try:
        alert_loc = page.locator('[role="alert"]').first
        if await alert_loc.is_visible(timeout=1000):
            text = (await alert_loc.inner_text()).strip().replace("\n", " ")
            if text:
                raise RuntimeError(f"Microsoft SSO Alert: {text}")
    except RuntimeError:
        raise
    except Exception:
        pass


async def _handle_microsoft_sso(page):
    """
    Automatically fill the Microsoft SSO login form:
      1. Enter email → click Next
      2. Enter password → click Sign In
      3. Handle "Stay signed in?" prompt
      4. Wait for RSA/MFA push approval (the real user approves on their phone)
    """
    if not ORACLE_EMAIL or not ORACLE_PASSWORD:
        print(f"[{ts()}] ⚠ No credentials in .env — waiting for manual login...")
        print(f"[{ts()}]   Create a .env file with ORACLE_EMAIL and ORACLE_PASSWORD")
        return False

    print(f"[{ts()}] SSO login detected — filling credentials automatically...")
    await page.wait_for_timeout(2000)
    await check_for_sso_errors(page)

    # ── Step 1: Email ─────────────────────────────────────────────────────
    email_selectors = [
        'input[name="loginfmt"]',
        'input[type="email"]',
        'input[id="i0116"]',
    ]
    email_filled = False
    for sel in email_selectors:
        try:
            email_input = page.locator(sel).first
            if await email_input.is_visible(timeout=5000):
                for attempt in range(1, 4):
                    await email_input.fill("")
                    await page.wait_for_timeout(200)
                    await email_input.fill(ORACLE_EMAIL)
                    print(f"[{ts()}]   Entered email: {ORACLE_EMAIL} (Attempt {attempt}/3)")
                    await page.wait_for_timeout(500)

                    # Click Next
                    next_btn = page.locator('input[type="submit"], #idSIButton9').first
                    await next_btn.click()
                    print(f"[{ts()}]   Clicked Next")
                    await page.wait_for_timeout(3000)
                    
                    # Check for errors immediately after clicking Next
                    try:
                        await check_for_sso_errors(page)
                        email_filled = True
                        break  # No errors, proceed to next step
                    except RuntimeError as e:
                        if attempt == 3:
                            raise
                        print(f"[{ts()}]   {e} - Retrying...")
                
                if email_filled:
                    break
        except RuntimeError:
            raise
        except Exception:
            continue

    if not email_filled:
        print(f"[{ts()}]   Email field not found — page may have changed.")
        await save_debug_screenshot(page, "email_not_found")
        return False

    # ── Step 2: Password ──────────────────────────────────────────────────
    password_selectors = [
        'input[name="passwd"]',
        'input[type="password"]',
        'input[id="i0118"]',
    ]
    password_filled = False
    for sel in password_selectors:
        try:
            pw_input = page.locator(sel).first
            if await pw_input.is_visible(timeout=5000):
                for attempt in range(1, 4):
                    await pw_input.fill("")
                    await page.wait_for_timeout(200)
                    await pw_input.fill(ORACLE_PASSWORD)
                    print(f"[{ts()}]   Entered password (Attempt {attempt}/3)")
                    await page.wait_for_timeout(500)

                    # Click Sign In
                    signin_btn = page.locator('input[type="submit"], #idSIButton9').first
                    await signin_btn.click()
                    print(f"[{ts()}]   Clicked Sign In")
                    await page.wait_for_timeout(3000)
                    
                    # Check for errors immediately after clicking Sign In
                    try:
                        await check_for_sso_errors(page)
                        password_filled = True
                        break  # No errors, proceed to next step
                    except RuntimeError as e:
                        if attempt == 3:
                            raise
                        print(f"[{ts()}]   {e} - Retrying...")
                
                if password_filled:
                    break
        except RuntimeError:
            raise
        except Exception:
            continue

    if not password_filled:
        print(f"[{ts()}]   Password field not found — may need different auth flow.")
        await save_debug_screenshot(page, "password_not_found")
        return False

    # ── Step 3: Choose RSA method if prompted ─────────────────────────────
    # Sometimes Microsoft asks "Verify your identity" and you have to click the RSA button
    try:
        rsa_btn = page.locator('div[role="button"], button').filter(has_text="RSAEntraMFA").first
        if await rsa_btn.is_visible(timeout=5000):
            print(f"[{ts()}]   'Verify your identity' screen detected.")
            await rsa_btn.click()
            print(f"[{ts()}]   Clicked 'Approve with RSAEntraMFA'")
            await page.wait_for_timeout(3000)
    except Exception:
        pass  # If it doesn't appear, the push might have been sent automatically

    # ── Step 4: RSA / MFA approval ────────────────────────────────────────
    print(f"[{ts()}] Waiting for RSA/MFA approval...")
    print()
    print("  +------------------------------------------------------------+")
    print("  |  RSA push notification sent to the user's phone.           |")
    print("  |  Please ask them to APPROVE it.                            |")
    print("  |  Waiting up to 5 minutes...                                |")
    print("  +------------------------------------------------------------+")
    print()

    # ── Step 5: "Stay signed in?" prompt (may appear after MFA) ───────────
    # We handle this in parallel with waiting for redirect
    return True


async def wait_for_oracle_home(page, timeout_s: int = 300):
    """Wait for Oracle Fusion home page. Handles SSO login if needed."""
    print(f"[{ts()}] Waiting for Oracle home page (up to {timeout_s}s)...")

    home_selectors = [
        'text="HR SPOC Reports"',
        'a:has-text("HR SPOC Reports")',
        '.fuse-welcome-page',
        '.springboard',
    ]

    login_handled = False
    rsa_retry_count = 0
    deadline = asyncio.get_event_loop().time() + timeout_s

    while asyncio.get_event_loop().time() < deadline:

        # ── Check if we're on a login/SSO page ────────────────────────────
        current_url = page.url.lower()
        if any(x in current_url for x in ["login.microsoftonline", "login.microsoft", "adfs", "saml"]):
            if not login_handled:
                login_handled = await _handle_microsoft_sso(page)
            # If handled, just continue letting the loop run so it can catch "Stay signed in?"

        # ── Handle RSA / SecurID Rejection ────────────────────────────────
        try:
            if "securid.com" in current_url or "adani.auth" in current_url:
                retry_btn = page.locator('button:has-text("Retry")').first
                if await retry_btn.is_visible(timeout=1000):
                    rsa_retry_count += 1
                    print(f"[{ts()}] ⚠ RSA/MFA Authentication failed or rejected (Attempt {rsa_retry_count}/3).")
                    if rsa_retry_count >= 3:
                        await save_debug_screenshot(page, "rsa_failed_3_times")
                        raise RuntimeError("RSA/MFA Authentication failed 3 times. Please ensure you are approving the prompt.")
                    
                    print(f"[{ts()}]   Clicking 'Retry' for RSA...")
                    await retry_btn.click()
                    await page.wait_for_timeout(3000)
                    print(f"[{ts()}] Waiting for RSA/MFA approval...")
                    continue
        except RuntimeError:
            raise
        except Exception:
            pass

        # ── Handle "Stay signed in?" prompt ───────────────────────────────
        try:
            stay_signed = page.locator('#idSIButton9, input[value="Yes"]').first
            if await stay_signed.is_visible(timeout=1000):
                await stay_signed.click()
                print(f"[{ts()}]   Clicked 'Stay signed in? → Yes'")
                await page.wait_for_timeout(3000)
                continue
        except Exception:
            pass

        # ── Check for Oracle home page ────────────────────────────────────
        for sel in home_selectors:
            try:
                if await page.locator(sel).first.is_visible(timeout=2000):
                    print(f"[{ts()}]   Home page ready (matched: {sel!r})")
                    return
            except Exception:
                pass
        await page.wait_for_timeout(2000)

    await save_debug_screenshot(page, "home_load_timeout")
    raise RuntimeError(
        f"Oracle home page did not load within {timeout_s}s.\nCurrent URL: {page.url}"
    )


async def safe_click(locator, description: str, timeout: int = 15_000):
    try:
        await locator.wait_for(state="visible", timeout=timeout)
        await locator.scroll_into_view_if_needed()
        await locator.click(timeout=timeout)
        print(f"[{ts()}]   Clicked: {description}")
    except PlaywrightTimeoutError:
        raise RuntimeError(f"Could not click '{description}' within {timeout}ms")


async def wait_for_loading(frame, timeout_ms: int = 90_000):
    """Wait for Oracle ADF loading overlays to disappear (skip if none present)."""
    mask = frame.locator('div.modalMask')
    try:
        if await mask.count() == 0:
            return
        if not await mask.first.is_visible(timeout=2000):
            return
        print(f"[{ts()}] Waiting for modal loading masks to disappear...")
        await mask.first.wait_for(state="hidden", timeout=timeout_ms)
        print(f"[{ts()}]   Loading masks cleared.")
    except Exception as e:
        print(f"[{ts()}]   (Debug) Loading mask wait skipped: {e}")


async def click_with_fallback(page_or_frame, selectors: list, description: str,
                              timeout_each: int = 10_000):
    errors = []
    for sel in selectors:
        try:
            loc = page_or_frame.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout_each)
            await loc.scroll_into_view_if_needed()
            await loc.click()
            print(f"[{ts()}]   Clicked '{description}' via: {sel!r}")
            return
        except Exception as e:
            errors.append(f"    {sel!r}: {e}")
    raise RuntimeError(
        f"No working selector for '{description}'.\nTried:\n" + "\n".join(errors)
    )


def _is_report_page(url: str) -> bool:
    return "bipublisherEntry" in url or (
        "saw.dll" in url and "NDC" in url
    )


async def wait_for_report_tab(context, timeout_s: int = 90):
    """
    The NDC report opens in a NEW browser tab (not the Fusion home tab).
    Wait for that tab to appear and return it.
    """
    print(f"[{ts()}] Waiting for BI Publisher report tab...")
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_print = 0

    while asyncio.get_event_loop().time() < deadline:
        for p in context.pages:
            if _is_report_page(p.url):
                await p.bring_to_front()
                try:
                    await p.wait_for_load_state("domcontentloaded", timeout=10_000)
                except Exception:
                    pass
                print(f"[{ts()}]   Report tab found: {p.url[:80]}...")
                return p

        now = asyncio.get_event_loop().time()
        if now - last_print > 10:
            urls = [p.url[:70] for p in context.pages]
            print(f"[{ts()}]   (Debug) {len(urls)} open tabs: {urls}")
            last_print = now

        await asyncio.sleep(1.0)

    urls = [p.url for p in context.pages]
    raise RuntimeError(
        f"BI Publisher report tab not found within {timeout_s}s.\n"
        f"Open tabs:\n  " + "\n  ".join(urls)
    )


async def get_bipublisher_frame(report_page, timeout_s: int = 90):
    """
    Report parameters live inside the first child iframe of the main frame
    (matches Puppeteer recording: mainFrame().childFrames()[0]).
    """
    print(f"[{ts()}] Waiting for report parameter iframe...")
    bu_input = '#xdo\\:xdo\\:_paramsP_Business_Unit_div_input'
    bu_input_loose = '[id*="Business_Unit_div_input"]'
    apply_btn = '#reportViewApply'
    deadline = asyncio.get_event_loop().time() + timeout_s

    while asyncio.get_event_loop().time() < deadline:
        # Primary: first child frame of main (from screen recording)
        children = report_page.main_frame.child_frames
        if children:
            frame = children[0]
            try:
                loc = frame.locator(bu_input)
                if await loc.count() > 0 and await loc.first.is_visible(timeout=2000):
                    print(f"[{ts()}]   Parameter iframe found (main child frame [0]).")
                    return frame
            except Exception:
                pass

        # Fallback: scan every frame on the report tab
        for frame in report_page.frames:
            try:
                loc = frame.locator(bu_input_loose)
                if await loc.count() > 0 and await loc.first.is_visible(timeout=1000):
                    print(f"[{ts()}]   Parameter iframe found (frame scan).")
                    return frame
            except Exception:
                pass

        # Page shell may be ready before the iframe — wait for Apply as readiness signal
        try:
            await report_page.locator(apply_btn).first.wait_for(
                state="visible", timeout=1500
            )
        except Exception:
            pass

        await asyncio.sleep(1.0)

    await save_debug_screenshot(report_page, "report_frame_not_found")
    raise RuntimeError(
        f"BI Publisher parameter iframe not found within {timeout_s}s.\n"
        f"Page URL: {report_page.url}"
    )


async def wait_for_report_completed(report_page, report_frame, timeout_ms: int = 300_000):
    """Wait until the report area shows 'Report Completed'."""
    print(f"[{ts()}] Waiting for 'Report Completed' (up to {timeout_ms // 1000}s)...")
    deadline = asyncio.get_event_loop().time() + timeout_ms / 1000
    while asyncio.get_event_loop().time() < deadline:
        for frame in report_page.frames:
            try:
                loc = frame.get_by_text("Report Completed", exact=True)
                if await loc.count() > 0 and await loc.first.is_visible(timeout=500):
                    print(f"[{ts()}]   Report Completed.")
                    return True
            except Exception:
                pass
        await asyncio.sleep(2)
    print(f"[{ts()}]   'Report Completed' not seen — still waiting for download...")
    return False


def _download_extension(suggested_filename: str) -> str:
    """Use the extension Oracle sends — this report is .xls, not .xlsx."""
    ext = Path(suggested_filename).suffix.lower() if suggested_filename else ""
    if ext in (".xls", ".xlsx", ".xlsm", ".csv"):
        return ext
    return ".xls"


async def click_apply_and_wait_for_download(
    report_page, report_frame, download_dir: Path, timeout_ms: int = 300_000
):
    """
    Apply triggers an automatic Excel download — no Export button needed.
    Wait for the download event and save with a timestamped filename.
    """
    print(f"[{ts()}] Clicking Apply — automatic download will start...")
    try:
        async with report_page.expect_download(timeout=timeout_ms) as dl_info:
            await safe_click(report_frame.locator('#reportViewApply'), "Apply button")
            await wait_for_loading(report_frame, timeout_ms=90_000)
            await wait_for_report_completed(report_page, report_frame, timeout_ms=timeout_ms)

        download = await dl_info.value
        failure = await download.failure()
        if failure:
            raise RuntimeError(f"Browser download failed: {failure}")

        suggested = download.suggested_filename or ""
        ext = _download_extension(suggested)
        save_path = download_dir / f"{report_save_stem()}{ext}"

        await download.save_as(save_path)

        size = save_path.stat().st_size
        if size < 512:
            raise RuntimeError(
                f"Downloaded file is too small ({size} bytes) — likely incomplete."
            )

        print(f"[{ts()}]   Saved: {save_path}")
        if suggested:
            print(f"[{ts()}]   Browser filename: {suggested}")
        print(f"[{ts()}]   File size: {size:,} bytes")
        return str(save_path)

    except PlaywrightTimeoutError:
        await save_debug_screenshot(report_page, "download_timeout")
        return None


# ─── MAIN ────────────────────────────────────────────────────────────────────

async def download_ndc_report():
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[{ts()}] Starting NDC report download ({'headless' if HEADLESS == 'true' else 'visible'})")
    print(f"[{ts()}] Output directory: {DOWNLOAD_DIR}")

    _cleanup_profile_locks()

    try:
        async with async_playwright() as p:
            print(f"[{ts()}] Starting dedicated automation browser...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(AUTOMATION_PROFILE_DIR),
                channel="chrome",
                headless=(HEADLESS == "true"),
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-session-crashed-bubble",
                    "--hide-crash-restore-bubble",
                    "--window-size=1517,900",
                ]
            )
            print(f"[{ts()}] Connected to automation Chrome.")

            page = context.pages[0] if context.pages else await context.new_page()

            print(f"[{ts()}] Navigating to Oracle Fusion...")
            await page.goto(ORACLE_URL, wait_until="domcontentloaded", timeout=90_000)
            await page.wait_for_timeout(3000)

            await wait_for_oracle_home(page, timeout_s=120)
            await page.wait_for_timeout(2000)

            print(f"[{ts()}] Clicking 'HR SPOC Reports'...")
            await click_with_fallback(page, [
                'a:has-text("HR SPOC Reports")',
                'text="HR SPOC Reports"',
                '#c_64db9d54bc7c456d958c987c0cc83fcf',
                'xpath=//a[normalize-space()="HR SPOC Reports"]',
                'xpath=//*[contains(text(),"HR SPOC Reports")]',
            ], "HR SPOC Reports")
            await page.wait_for_timeout(3000)

            print(f"[{ts()}] Clicking 'NDC Process Request Status' (expecting new tab)...")
            ndc_selectors = [
                'a:has-text("NDC Process Request Status")',
                'text="NDC Process Request Status"',
                '#c_fc8798b561de4e0bb05f5b982200a547_0',
                'text="NDC Process Request"',
                'xpath=//*[contains(text(),"NDC Process Request")]',
            ]
            try:
                async with context.expect_page(timeout=60_000) as new_page_info:
                    await click_with_fallback(page, ndc_selectors, "NDC Process Request Status")
                report_page = await new_page_info.value
                print(f"[{ts()}]   New report tab opened.")
            except PlaywrightTimeoutError:
                print(f"[{ts()}]   No new tab event — looking for existing report tab...")
                report_page = await wait_for_report_tab(context, timeout_s=30)

            await report_page.bring_to_front()
            try:
                await report_page.wait_for_load_state("networkidle", timeout=30_000)
            except PlaywrightTimeoutError:
                await report_page.wait_for_load_state("domcontentloaded", timeout=15_000)
            await report_page.wait_for_timeout(3000)

            report_frame = await get_bipublisher_frame(report_page, timeout_s=90)
            await wait_for_loading(report_frame, timeout_ms=30_000)

            print(f"[{ts()}] Clicking Business Unit field...")
            await safe_click(
                report_frame.locator('#xdo\\:xdo\\:_paramsP_Business_Unit_div_input'),
                "Business Unit field",
            )

            print(f"[{ts()}] Clicking Business Unit search icon (magnifier)...")
            await safe_click(
                report_frame.locator(
                    '#xdo\\:xdo\\:_paramsP_Business_Unit_div_b span.dialogFloatLeft'
                ),
                "Business Unit search icon",
            )
            await report_page.wait_for_timeout(2000)

            print(f"[{ts()}] Filling '{BUSINESS_UNIT_SEARCH}'...")
            dialog_input = report_frame.locator(
                '#xdo\\:xdo\\:_paramsP_Business_Unit_div_input_searchDialog_input'
            )
            await dialog_input.wait_for(state="visible", timeout=15_000)
            await dialog_input.fill(BUSINESS_UNIT_SEARCH)

            print(f"[{ts()}] Clicking Search...")
            await safe_click(
                report_frame.locator(
                    '#xdo\\:xdo\\:_paramsP_Business_Unit_div_input_searchDialog_button'
                ),
                "Search button",
            )
            await report_page.wait_for_timeout(3000)

            print(f"[{ts()}] Moving all results to selected...")
            await safe_click(
                report_frame.locator(
                    '#xdo\\:xdo\\:_paramsP_Business_Unit_div_input_searchDialog_moveAllImg'
                ),
                "Move All button",
            )
            await report_page.wait_for_timeout(1000)

            print(f"[{ts()}] Clicking OK...")
            ok_selectors = [
                'xpath=//*[@id="xdo:xdo:_paramsP_Business_Unit_div_input_searchDialog_dialogTable"]/tbody/tr[3]/td[2]/table/tbody/tr/td[2]/button[1]',
                'button.button_mo',
            ]
            await click_with_fallback(report_frame, ok_selectors, "OK button")
            await report_page.wait_for_timeout(2000)

            result = await click_apply_and_wait_for_download(
                report_page, report_frame, DOWNLOAD_DIR, timeout_ms=300_000
            )

            if result:
                print(f"\nSUCCESS! Report saved to:\n   {result}")
            else:
                print(f"\nDownload did not complete in time. Check screenshot in {DOWNLOAD_DIR}")

    except Exception as e:
        print(f"[{ts()}] Error: {e}")


if __name__ == "__main__":
    asyncio.run(download_ndc_report())
