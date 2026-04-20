#!/usr/bin/env python3
"""
Shared WhatsApp file sender — used by all bots on this server.
Usage: python3 send_whatsapp_file.py <phone> <file_path>
Exit 0 = success, Exit 1 = failure.
"""

import sys
import os
import time
import fcntl
import subprocess

LOCK_PATH = '/tmp/whatsapp_sender.lock'
PROFILE   = os.path.join(os.path.dirname(__file__), 'wa_profile')


def send_file(phone: str, file_path: str) -> bool:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    if not os.path.isfile(file_path):
        print(f'[send_whatsapp_file] ERROR: file not found: {file_path}', file=sys.stderr)
        return False

    phone_clean = phone.replace('+', '').replace(' ', '')

    options = Options()
    options.add_argument('-profile')
    options.add_argument(PROFILE)

    service = Service('/snap/bin/geckodriver')

    lockfile = open(LOCK_PATH, 'w')
    fcntl.flock(lockfile, fcntl.LOCK_EX)

    driver = webdriver.Firefox(service=service, options=options)
    wait   = WebDriverWait(driver, 60)

    def safe_click(element):
        """Click element; fall back to JS click if an overlay intercepts it."""
        try:
            element.click()
        except Exception:
            driver.execute_script("arguments[0].click();", element)

    try:
        driver.get(f'https://web.whatsapp.com/send?phone={phone_clean}')
        time.sleep(8)

        wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "div[contenteditable='true'][data-tab='10']")
        ))
        time.sleep(2)

        # Open attach menu
        safe_click(driver.find_element(By.CSS_SELECTOR, "span[data-icon='plus-rounded']"))
        time.sleep(2)

        # Click Document button
        doc_btn = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "button[aria-label='Document']")
        ))
        safe_click(doc_btn)
        time.sleep(2)

        # Type file path in native GTK dialog via xdotool
        env = {'DISPLAY': ':0'}
        subprocess.run(['xdotool', 'key', 'ctrl+l'], env=env)
        time.sleep(0.5)
        subprocess.run(['xdotool', 'type', '--clearmodifiers', '--delay', '50', file_path], env=env)
        time.sleep(0.5)
        subprocess.run(['xdotool', 'key', 'Return'], env=env)
        time.sleep(4)

        # Click Send
        send_btn = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "div[aria-label='Send'], button[aria-label='Send']")
        ))
        safe_click(send_btn)
        time.sleep(5)

        print(f'[send_whatsapp_file] Sent {os.path.basename(file_path)} to {phone_clean}')
        return True

    except Exception as e:
        print(f'[send_whatsapp_file] ERROR: {e}', file=sys.stderr)
        return False

    finally:
        driver.quit()
        fcntl.flock(lockfile, fcntl.LOCK_UN)
        lockfile.close()


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: send_whatsapp_file.py <phone> <file_path>', file=sys.stderr)
        sys.exit(1)

    success = send_file(sys.argv[1], sys.argv[2])
    sys.exit(0 if success else 1)
