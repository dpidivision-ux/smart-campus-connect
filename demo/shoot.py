"""Screenshot key pages of the local app for visual verification."""
import os, subprocess, sys, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"
OUT = os.path.join(os.path.dirname(__file__), "..", "shots")

def main():
    from record import load_creds, CREDS
    load_creds()
    os.makedirs(OUT, exist_ok=True)
    srv = subprocess.Popen([sys.executable, "run.py"], cwd=os.path.join(os.path.dirname(__file__), ".."),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", args=["--no-sandbox"])
            pg = browser.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(BASE + "/login"); pg.wait_for_load_state("networkidle")
            pg.screenshot(path=f"{OUT}/01-login.png")
            # admin
            pg.fill("input[name=username]", "admin"); pg.fill("input[name=password]", CREDS["admin"])
            pg.click("button[type=submit]"); pg.wait_for_load_state("networkidle")
            pg.goto(BASE + "/admin"); pg.wait_for_load_state("networkidle")
            pg.screenshot(path=f"{OUT}/02-admin.png", full_page=True)
            # student
            pg.goto(BASE + "/logout")
            pg.fill("input[name=username]", "adaeze"); pg.fill("input[name=password]", CREDS["adaeze"])
            pg.click("button[type=submit]"); pg.wait_for_load_state("networkidle")
            pg.screenshot(path=f"{OUT}/03-student-dashboard.png", full_page=True)
            browser.close()
        print("shots saved to", OUT)
    finally:
        srv.terminate()

if __name__ == "__main__":
    main()
