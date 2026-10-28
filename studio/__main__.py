"""`python -m studio` starts the dashboard + worker.  `python -m studio doctor` checks the toolchain and providers.
`python -m studio demo` serves an offline demo (fake engine, throw-away data).
`python -m studio scan [dir]` runs the secret scan (use it before every push)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def doctor() -> int:
    from .godot import android_env_ready, find_godot
    from .workflow import Studio

    st = Studio()
    s = st.db.settings()
    ok = True

    def line(name: str, good: bool, detail: str) -> None:
        nonlocal ok
        print(f"[{'ok' if good else '!!'}] {name}: {detail}")

    for b in ("git", "python3", "node"):
        line(b, bool(shutil.which(b)), shutil.which(b) or "missing")
    agy = shutil.which(s.get("agy_bin", "agy")) or (os.path.expanduser("~/.local/bin/agy") if os.path.exists(os.path.expanduser("~/.local/bin/agy")) else None)
    line("agy (Antigravity CLI)", bool(agy), agy or "missing - see README step 3")
    if agy:
        v = subprocess.run([agy, "--version"], capture_output=True, text=True)
        print("     version:", (v.stdout or v.stderr).strip()[:80])
    g = shutil.which(s.get("gemini_bin", "gemini"))
    line("gemini (legacy, optional)", True, g or "not installed (fine)")
    gd = find_godot(s.get("godot_bin", ""))
    line("godot", bool(gd), gd or "missing - QA will skip engine tests")
    a_ok, a = android_env_ready()
    line("android sdk (optional)", True, a if a_ok else f"not ready: {a}")
    line("engine setting", True, s.get("engine"))
    from .wizard import check_prereqs
    for c in check_prereqs(s):
        line(c["label"], c["ok"] or not c["required"], c["detail"] + ("" if c["ok"] else f"  -> {c['fix']}"))
    for p in st.providers_info():
        if p["used"]:
            r = st.test_connection(p["id"])
            line(f"provider {p['label']}", True, ("OK: " if r.get("ok") else "NOT READY: ") + r.get("detail", ""))
    line("setup wizard", True, "done" if s.get("setup_complete") == "1" else "not finished: open http://localhost:8787/#setup")
    line("queue", True, "PAUSED: " + s.get("pause_reason", "") if s.get("paused") == "1" else "running")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        sys.exit(doctor())
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        from .secretscan import main as scan_main
        sys.exit(scan_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        from .demo import main as demo
        demo(sys.argv[2:])
        sys.exit(0)
    from .app import main
    main()
