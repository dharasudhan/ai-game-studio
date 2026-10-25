"""Owner notifications: macOS desktop banners and (opt-in) a webhook to the owner's own channel, e.g. a
private ntfy topic. Respects quiet hours. Notifications go to the owner only - never to players or the public."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

KINDS = ("approvals", "errors", "standup", "feedback")


def parse_range(r: str) -> tuple[int, int] | None:
    """'22:30-07:30' -> (1350, 450) minutes; None when empty/invalid."""
    try:
        a, b = (r or "").split("-")
        ha, ma = (int(x) for x in a.strip().split(":"))
        hb, mb = (int(x) for x in b.strip().split(":"))
        if not (0 <= ha <= 24 and 0 <= hb <= 24 and 0 <= ma < 60 and 0 <= mb < 60):
            return None
        return ha * 60 + ma, hb * 60 + mb
    except (ValueError, AttributeError):
        return None


def in_range(r: str, t: time.struct_time | None = None) -> bool:
    rng = parse_range(r)
    if not rng:
        return False
    t = t or time.localtime()
    m = t.tm_hour * 60 + t.tm_min
    a, b = rng
    return a <= m < b if a <= b else (m >= a or m < b)


def notify(settings: dict, kind: str, title: str, message: str, sender=None) -> str:
    """Returns what happened ('sent', 'quiet', 'off') - used by tests and the activity log."""
    wanted = {k.strip() for k in (settings.get("notify_on") or "").split(",") if k.strip()}
    if kind not in wanted:
        return "off"
    if in_range(settings.get("quiet_hours", "")):
        return "quiet"
    sent = False
    if settings.get("notify_desktop") == "1" and sys.platform == "darwin":
        script = f'display notification {json.dumps(message[:200])} with title {json.dumps("AI Game Studio: " + title[:80])}'
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
            sent = True
        except Exception:  # noqa: BLE001 - a missed banner must never break the studio
            pass
    url = os.environ.get("STUDIO_NOTIFY_WEBHOOK", "")
    if settings.get("notify_webhook") == "1" and url:
        try:
            if sender:
                sender(url, title, message)
            else:
                req = urllib.request.Request(url, data=message[:1000].encode(), headers={"Title": title[:120]})
                urllib.request.urlopen(req, timeout=5).read()
            sent = True
        except Exception:  # noqa: BLE001
            pass
    return "sent" if sent else "off"
