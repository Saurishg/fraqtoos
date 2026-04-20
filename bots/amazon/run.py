#!/usr/bin/env python3
"""
FraqtoOS Amazon Bot — single entry point.
Modes:
  delete   — delete waste/missing listings
  listing  — update GTF + Proje content via ABIS
  reviews  — request reviews on recent orders
  health   — check listing suppression + Buy Box status
  all      — run delete → reviews → listing in sequence

Usage:
  python3 run.py delete
  python3 run.py listing
  python3 run.py all
"""
import sys, os, subprocess, time
sys.path.insert(0, "/home/work/fraqtoos")
from core.logger   import get_logger
from core.notifier import send_alert as _send_alert, send_success as _send_success
def send_alert(title, msg): log.warning(f"[SILENT] {title}: {msg[:100]}")
def send_success(title, msg): log.info(f"[SILENT] {title}: {msg[:100]}")

log = get_logger("amazon")
BOT_DIR = "/home/work/amazon-bot"

SCRIPTS = {
    "delete":  "scripts/delete_missing_info.py",
    "listing": "scripts/fix4_final.py",
    "reviews": "scripts/fix1_request_reviews.py",
    "b2b":     "scripts/fix3_b2b_discounts.py",
    "ads":     "scripts/fix2_sponsored_products.py",
}

def run_script(key: str, timeout: int = 600) -> bool:
    script = SCRIPTS.get(key)
    if not script:
        log.error(f"Unknown script: {key}")
        return False
    log.info(f"Amazon: running {key} ({script})")
    try:
        r = subprocess.run(
            f"python3 {script}", shell=True, cwd=BOT_DIR,
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "DISPLAY": ":0"}
        )
        out = (r.stdout + r.stderr).strip()
        log.info(f"  → {out[-500:]}")
        success = r.returncode == 0
        if not success:
            send_alert(f"Amazon {key} failed", out[-300:])
        return success
    except subprocess.TimeoutExpired:
        log.error(f"Amazon {key} timed out after {timeout}s")
        send_alert(f"Amazon {key} timeout", f"Exceeded {timeout}s")
        return False
    except Exception as e:
        log.error(f"Amazon {key} error: {e}")
        return False

def check_health() -> dict:
    """Check listing suppression and Buy Box status for both ASINs."""
    log.info("Amazon: checking listing health...")
    try:
        import sys as _sys
        _sys.path.insert(0, BOT_DIR)
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BOT_DIR, ".env"))

        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        from selenium.webdriver.support.ui import WebDriverWait

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--width=1440")
        options.add_argument("--height=900")
        options.profile = os.path.join(BOT_DIR, "amazon_profile")

        driver = webdriver.Firefox(service=Service("/snap/bin/geckodriver"), options=options)
        wait   = WebDriverWait(driver, 20)
        health = {}

        try:
            asins = {"B07T1Y999V": "GTF", "B0BKDY7RCD": "Proje"}
            for asin, name in asins.items():
                driver.get(f"https://www.amazon.in/dp/{asin}")
                time.sleep(5)
                body = driver.find_element(By.TAG_NAME, "body").text

                buy_box     = "Add to Cart" in body or "Buy Now" in body
                suppressed  = "unavailable" in body.lower() or "currently unavailable" in body.lower()
                price_shown = any(c in body for c in ["₹", "MRP"])

                health[name] = {
                    "asin":       asin,
                    "buy_box":    buy_box,
                    "suppressed": suppressed,
                    "price_shown": price_shown,
                    "status":     "OK" if buy_box and not suppressed else "ISSUE"
                }
                log.info(f"  {name}: buy_box={buy_box} suppressed={suppressed} price={price_shown}")
        finally:
            driver.quit()

        issues = [f"{n}: {v['status']}" for n, v in health.items() if v["status"] != "OK"]
        if issues:
            send_alert("Amazon Listing Issue", "\n".join(issues))
        return health

    except Exception as e:
        log.error(f"Health check error: {e}")
        return {}

def run_all():
    log.info("Amazon: running full sequence (delete → reviews → listing → health)")
    results = {}
    results["delete"]  = run_script("delete",  timeout=900)
    results["reviews"] = run_script("reviews", timeout=300)
    results["listing"] = run_script("listing", timeout=600)
    results["health"]  = check_health()

    ok = sum(1 for k, v in results.items() if (v is True or (isinstance(v, dict) and v)))
    summary = "\n".join([f"{'✓' if v else '✗'} {k}" for k, v in results.items() if isinstance(v, bool)])
    send_success("Amazon Bot Done", f"{ok}/3 tasks OK\n{summary}")
    return results

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "all":
        run_all()
    elif mode == "health":
        check_health()
    elif mode in SCRIPTS:
        run_script(mode)
    else:
        print(f"Usage: python3 run.py [{' | '.join(list(SCRIPTS.keys()) + ['health', 'all'])}]")
        sys.exit(1)
