#!/usr/bin/env python3
"""
Shared WhatsApp sender — used by all bots on this server.
Usage: python3 send_whatsapp.py <phone> <message>
Exit 0 = success, Exit 1 = failure.
"""

import sys
import os
import time
import fcntl
import signal
from urllib.parse import quote

LOCK_PATH = '/tmp/whatsapp_sender.lock'
LOCK_TIMEOUT = 180          # seconds — max wait for lock
SESSION_TIMEOUT = 90        # seconds — max wait for WA Web send flow


class Timeout(Exception): pass
def _alarm(signum, frame): raise Timeout("lock wait exceeded")


def acquire_lock(path: str, timeout: int):
    """Blocking file lock with overall timeout. Returns fd or raises Timeout."""
    fd = open(path, 'w')
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    finally:
        signal.alarm(0)
    return fd


def send(phone: str, message: str) -> bool:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    profile_dir = os.path.join(os.path.dirname(__file__), "wa_profile")
    options = Options()
    options.add_argument("-profile")
    options.add_argument(profile_dir)
    service = Service("/snap/bin/geckodriver")

    try:
        lockfile = acquire_lock(LOCK_PATH, LOCK_TIMEOUT)
    except Timeout:
        print(f"[send_whatsapp] ERROR: could not acquire WA lock in {LOCK_TIMEOUT}s", file=sys.stderr)
        return False

    driver = None
    try:
        driver = webdriver.Firefox(service=service, options=options)
        driver.set_page_load_timeout(60)
        wait = WebDriverWait(driver, SESSION_TIMEOUT)

        phone_clean = phone.replace("+", "").replace(" ", "")
        url = f"https://web.whatsapp.com/send?phone={phone_clean}&text={quote(message)}"
        driver.get(url)

        send_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button[aria-label='Send'], span[data-icon='send']")
        ))
        time.sleep(2)
        send_btn.click()

        # Verify the text box cleared (indicates message left the composer)
        for _ in range(10):
            time.sleep(1)
            try:
                box = driver.find_element(By.CSS_SELECTOR, "div[contenteditable='true'][data-tab='10']")
                if (box.text or "").strip() == "":
                    break
            except Exception:
                break

        time.sleep(3)
        print(f"[send_whatsapp] Sent to {phone_clean}")
        return True

    except Exception as e:
        print(f"[send_whatsapp] ERROR: {e}", file=sys.stderr)
        return False

    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass
        try:
            fcntl.flock(lockfile, fcntl.LOCK_UN)
            lockfile.close()
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: send_whatsapp.py <phone> <message>", file=sys.stderr)
        sys.exit(1)

    phone = sys.argv[1]
    message = sys.argv[2]

    if not phone or phone.lower() in ("none", "null", ""):
        print(f"[send_whatsapp] ERROR: empty phone", file=sys.stderr)
        sys.exit(1)

    sys.exit(0 if send(phone, message) else 1)
