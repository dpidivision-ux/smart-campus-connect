"""Record demo video segments of the real app (Playwright video) + title cards."""
import os, subprocess, sys, time
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..")
BASE = "http://127.0.0.1:5000"
SEGS = os.path.join(ROOT, "video", "segs")
CARDS = os.path.join(ROOT, "video", "cards")
VW, VH = 1280, 720

CREDS = {}
for line in open(os.path.join(ROOT, "demo", "DEMO_CREDENTIALS.txt")):
    parts = line.split()
    if len(parts) == 3 and parts[0] in ("admin", "lecturer", "student"):
        CREDS[parts[1]] = parts[2]

LECTURE = open(os.path.join(ROOT, "demo", "lecture_csc101.txt")).read()


def card(pw, name, title, subtitle):
    pg = pw["browser"].new_page(viewport={"width": VW, "height": VH})
    pg.set_content(f"""<body style="margin:0;width:{VW}px;height:{VH}px;display:flex;flex-direction:column;
      justify-content:center;align-items:center;background:#0b3d2e;color:#fff;
      font-family:-apple-system,'Segoe UI',Roboto,sans-serif;text-align:center">
      <div style="font-size:44px;font-weight:700;max-width:900px;line-height:1.25">{title}</div>
      <div style="font-size:22px;opacity:.85;margin-top:18px;max-width:820px">{subtitle}</div></body>""")
    pg.wait_for_timeout(600)
    pg.screenshot(path=os.path.join(CARDS, name))
    pg.close()


def seg(pw, name, actions):
    ctx = pw["browser"].new_context(viewport={"width": VW, "height": VH},
                                    record_video_dir=SEGS, record_video_size={"width": VW, "height": VH})
    pg = ctx.new_page()
    pg.goto(BASE + "/login"); pg.wait_for_load_state("networkidle")
    actions(pg)
    pg.wait_for_timeout(400)
    ctx.close()  # finalizes video
    saved = [f for f in os.listdir(SEGS) if f.endswith(".webm") and not f.startswith(name)]
    return


def login(pg, who):
    pg.fill("input[name=username]", who)
    pg.fill("input[name=password]", CREDS[who])
    pg.wait_for_timeout(600)
    pg.click("button[type=submit]"); pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(800)


def slow_type(pg, selector, text, delay=28):
    pg.click(selector)
    pg.keyboard.type(text, delay=delay)


def main():
    srv = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", args=["--no-sandbox"])
            pw = {"browser": browser}

            card(pw, "s1-title.png", "Smart Campus Connect",
                 "Fair internet hours and offline-first AI study tools<br>for the University of Nigeria, Nsukka")
            card(pw, "s6-close.png", "Smart Campus Connect",
                 "Meta Global AI Developer Hackathon 2026 &middot; Build for Your World")

            import contextlib
            def safe(name, fn):
                try:
                    seg(pw, name, fn)
                    print("OK", name)
                except Exception as e:
                    print("FAIL", name, type(e).__name__, str(e)[:200])

            # S2: admin sets pool + runs allocation
            def s2(pg):
                login(pg, "admin")
                pg.goto(BASE + "/admin"); pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(1200)
                btn = pg.locator("button:has-text('Run allocation')")
                btn.scroll_into_view_if_needed(); pg.wait_for_timeout(500); btn.click()
                pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(1000)
                pg.locator("text=Allocations").scroll_into_view_if_needed(); pg.wait_for_timeout(2200)
            safe("s2", s2)

            # S3: student dashboard + usage log
            def s3(pg):
                login(pg, "adaeze")
                pg.wait_for_timeout(1800)
                pg.fill("input[name=minutes]", "25")
                pg.fill("input[name=note]", "Downloading CSC 101 materials")
                pg.wait_for_timeout(600)
                pg.click("button:has-text('Log usage')"); pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(1800)
            safe("s3", s3)

            # S4: AI study tools (records whichever mode the app is in)
            def s4(pg):
                login(pg, "adaeze")
                box = pg.locator("textarea[name=source_text]")
                box.scroll_into_view_if_needed()
                pg.evaluate("t => { document.querySelector('textarea[name=source_text]').value = t }", LECTURE)
                pg.wait_for_timeout(800)
                pg.select_option("select[name=kind]", "summary")
                pg.wait_for_timeout(400)
                pg.click("button:has-text('Generate')"); pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(4500)   # model latency / fallback render
                pg.wait_for_selector(".result", timeout=15000); pg.locator(".result").first.scroll_into_view_if_needed(); pg.wait_for_timeout(3000)
                # quiz too
                pg.goto(BASE + "/dashboard"); pg.wait_for_load_state("networkidle")
                pg.evaluate("t => { document.querySelector('textarea[name=source_text]').value = t }", LECTURE)
                pg.select_option("select[name=kind]", "quiz")
                pg.click("button:has-text('Generate')"); pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(4500)
                pg.wait_for_selector(".result", timeout=15000); pg.locator(".result").first.scroll_into_view_if_needed(); pg.wait_for_timeout(2500)
            safe("s4", s4)

            # S5: cache hit + library
            def s5(pg):
                login(pg, "lecturer")
                pg.goto(BASE + "/dashboard"); pg.wait_for_load_state("networkidle")
                pg.evaluate("t => { document.querySelector('textarea[name=source_text]').value = t }", LECTURE)
                pg.select_option("select[name=kind]", "summary")
                pg.click("button:has-text('Generate')"); pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(2500)  # cache badge visible
                if pg.locator("button:has-text('Publish to student library')").count():
                    pg.fill("input[name=title]", "CSC 101 Week 3 - exam summary")
                    pg.click("button:has-text('Publish to student library')")
                    pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(1500)
                pg.goto(BASE + "/materials"); pg.wait_for_load_state("networkidle")
                pg.wait_for_timeout(1500)
                link = pg.locator("table a").first
                link.click(); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(2500)
            safe("s5", s5)

            browser.close()
        print("segments:", sorted(os.listdir(SEGS)))
        print("cards:", sorted(os.listdir(CARDS)))
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
