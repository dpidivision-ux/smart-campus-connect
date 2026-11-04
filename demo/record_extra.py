"""Extra real-footage segments for the final demo (no model calls)."""
import html, os, subprocess, sys, time, json
sys.path.insert(0, os.path.dirname(__file__))
import record as R
from playwright.sync_api import sync_playwright
ROOT = R.ROOT; SEGS = R.SEGS; BASE = R.BASE

def textpage(pg, title, blocks):
    body = "".join(f"<h3>{html.escape(h)}</h3><pre>{html.escape(t)}</pre>" for h, t in blocks)
    pg.set_content(f"""<body style="margin:0;background:#0f1b17;color:#e8f3ee;font-family:-apple-system,'Segoe UI',sans-serif">
    <div style="background:#0b3d2e;padding:16px 28px;font-size:26px;font-weight:700">{html.escape(title)}</div>
    <div style="padding:10px 40px 400px"><style>pre{{font:19px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;background:#16251f;padding:16px;border-radius:8px}}h3{{color:#9fd8bd;font-size:20px;margin:18px 0 6px}}</style>{body}</div></body>""")

def smooth_scroll(pg, total_ms, dist):
    pg.evaluate("""([ms,d]) => new Promise(r=>{const s=performance.now();(function f(){const t=Math.min(1,(performance.now()-s)/ms);
      window.scrollTo(0,d*t); t<1?requestAnimationFrame(f):r()})()})""", [total_ms, dist])

def state(pw, who):
    c = pw["browser"].new_context(viewport={"width": R.VW, "height": R.VH}); pg = c.new_page()
    pg.goto(BASE + "/login"); R.login(pg, who); st = c.storage_state(); c.close(); return st

def rawseg(pw, name, fn, st=None):
    kw = {"storage_state": st} if st else {}
    ctx = pw["browser"].new_context(viewport={"width": R.VW, "height": R.VH}, record_video_dir=SEGS, record_video_size={"width": R.VW, "height": R.VH}, **kw)
    pg = ctx.new_page(); fn(pg); pg.wait_for_timeout(400)
    v = pg.video; ctx.close(); v.save_as(os.path.join(SEGS, name + ".webm")); v.delete(); print("OK", name)

def alloc_out():
    code = f"""
import sys; sys.path.insert(0, {ROOT!r})
from app.allocation import compute_allocation
S=[dict(id=1,full_name='Student A',exam_urgency=9,need_bonus=0.0),dict(id=2,full_name='Student B',exam_urgency=5,need_bonus=0.0),
   dict(id=3,full_name='Student C',exam_urgency=1,need_bonus=0.0),dict(id=4,full_name='Student D',exam_urgency=1,need_bonus=1.0)]
for r in compute_allocation(S,1200): print(r['user_id'], str(r['minutes'])+' min', '-', r['rationale'])
"""
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout

ONLY = sys.argv[1:] or ["e1","e3","e2","e4"]
def main():
    R.load_creds()
    srv = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)
    try:
        with sync_playwright() as p:
            pw = {"browser": p.chromium.launch(channel="chrome", args=["--no-sandbox"])}
            alloc_src = open(os.path.join(ROOT, "app/allocation.py")).read().split("def compute_allocation")[0]
            def e1(pg):
                textpage(pg, "app/allocation.py - how hours are split", [
                    ("Source (app/allocation.py, excerpt)", alloc_src),
                    ("Real output: compute_allocation(4 sample students, pool 1200 min)", "Sample inputs: A urgency 9, B urgency 5, C urgency 1, D urgency 1 + documented need\n\n" + alloc_out())])
                pg.wait_for_timeout(3500); smooth_scroll(pg, 9000, 520); pg.wait_for_timeout(1500)
            if "e1" in ONLY: rawseg(pw, "e1", e1)
            def e3(pg):
                pg.goto(BASE + "/ai/4"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(2000)
                h = pg.evaluate("document.body.scrollHeight")
                smooth_scroll(pg, 5500, max(0, h - 720)); pg.wait_for_timeout(1800)
            if "e3" in ONLY: rawseg(pw, "e3", e3, state(pw, "adaeze"))
            def e2(pg):
                pg.goto(BASE + "/admin"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(1000)
                pg.locator("text=AI system status").first.scroll_into_view_if_needed(); pg.wait_for_timeout(6000)
                pg.locator("text=Measured usage").first.scroll_into_view_if_needed(); pg.wait_for_timeout(8000)
            if "e2" in ONLY: rawseg(pw, "e2", e2, state(pw, "admin"))
            src = open(os.path.join(ROOT, "app/ai_module.py")).read().splitlines()
            i = next(k for k, l in enumerate(src) if "if not (result or" in l)
            exc = "\n".join(src[i:i+6])
            tl = open(os.path.join(ROOT, "tests/test_ai_module.py")).read().rstrip().split("\n\n\n")[-1]
            tst = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
            def e4(pg):
                textpage(pg, "Code: empty model output is a failed attempt", [
                    ("app/ai_module.py (excerpt)", exc),
                    ("tests/test_ai_module.py (the new regression test)", tl), ("$ python -m pytest -q   (real run)", tst)])
                pg.wait_for_timeout(6000); smooth_scroll(pg, 9000, 330); pg.wait_for_timeout(3500)
            if "e4" in ONLY: rawseg(pw, "e4", e4)
            pw["browser"].close()
    finally:
        srv.terminate()
main()
