#!/usr/bin/env python3
"""Screenshot the web intro (key frames + loading screen, portrait + landscape) with Playwright Firefox."""
import os, sys, pathlib
from playwright.sync_api import sync_playwright
K = pathlib.Path(__file__).resolve().parent.parent
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else K / "preview")
out.mkdir(parents=True, exist_ok=True)
url = (K / "studio_intro_web" / "index.html").as_uri()
errs = []
with sync_playwright() as p:
    b = p.firefox.launch()
    for name, (w, h, dpr) in {"portrait": (432, 960, 2.5), "landscape": (960, 432, 2.5)}.items():
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=dpr)
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for t in ("0.56", "1.0", "1.75"):
            pg.goto(url + "?freeze=" + t); pg.wait_for_timeout(1600)
            pg.screenshot(path=str(out / f"web_key_{t}_{name}.png"))
        pg.goto(url + "?loading=0.6"); pg.wait_for_timeout(1200)
        pg.screenshot(path=str(out / f"web_loading_{name}.png"))
        # full run: intro then loading then the game
        pg.goto(url + "?load=4500"); pg.wait_for_timeout(3600)
        pg.screenshot(path=str(out / f"web_run_loading_{name}.png"))
        pg.wait_for_function("document.title === 'DONE'", timeout=15000)
        pg.screenshot(path=str(out / f"web_run_done_{name}.png"))
        pg.close()
    b.close()
print("web shots ok; console errors:", errs if errs else "none")
