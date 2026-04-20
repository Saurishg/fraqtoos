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
from urllib.parse import quote

LOCK_PATH = '/tmp/whatsapp_sender.lock'

def send(phone: str, message: str):
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
    # NOT headless — needs real display so WhatsApp Web session persists

    service = Service("/snap/bin/geckodriver")

    # File lock — prevents multiple bots from opening Firefox simultaneously
    lockfile = open(LOCK_PATH, 'w')
    fcntl.flock(lockfile, fcntl.LOCK_EX)

    driver = webdriver.Firefox(service=service, options=options)
    wait = WebDriverWait(driver, 60)

    try:
        phone_clean = phone.replace("+", "").replace(" ", "")
        url = f"https://web.whatsapp.com/send?phone={phone_clean}&text={quote(message)}"
        driver.get(url)

        # Wait for the Send button to appear (confirms logged in + message loaded)
        send_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "button[aria-label='Send'], span[data-icon='send']")
        ))
        time.sleep(2)
        send_btn.click()
        time.sleep(5)
        print(f"[send_whatsapp] Sent to {phone_clean}")
        return True

    except Exception as e:
        print(f"[send_whatsapp] ERROR: {e}", file=sys.stderr)
        return False

    finally:
        driver.quit()
        fcntl.flock(lockfile, fcntl.LOCK_UN)
        lockfile.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: send_whatsapp.py <phone> <message>", file=sys.stderr)
        sys.exit(1)

    phone   = sys.argv[1]
    message = sys.argv[2]

    success = send(phone, message)
    sys.exit(0 if success else 1)
