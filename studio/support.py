"""Customer Support plumbing: feedback parsing, normalisation, de-duplication, rule-based triage and grouping.

Design (see CREDITS.md): deterministic first, LLM second. Parsing, fingerprints, de-duplication and
grouping are plain code so they are repeatable; the Support agent (LLM) only classifies, summarises and
drafts replies, and its labels are validated against the fixed taxonomy below (falling back to the rule
classifier when a reply is missing or invalid). Nothing here sends or posts anything.

Sources
* Google Play Console reviews CSV (reviews_<package>_YYYYMM.csv). Play ships these as UTF-16; columns are
  picked by NAME, never by position, because Google adds columns over time.
* Inbox folder: feedback/*.txt | *.json | *.csv (sub-folder name may be the game slug).
* In-game feedback JSON (object, list, or {"items": [...]}) dropped in the inbox or POSTed to the API.
* Optional IMAP mailbox, read-only (credentials only from the environment / .env).
"""
from __future__ import annotations

import csv
import email
import email.header
import email.utils
import hashlib
import imaplib
import io
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

CATEGORIES = ["bug", "crash", "feature_request", "praise", "billing", "ads", "abuse", "other"]
SENTIMENTS = ["positive", "neutral", "negative"]
SEVERITIES = ["low", "med", "high", "critical"]
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
# reply/handling pipeline; bug linkage (bug_ticket_id, fixed_sha, fixed_in_version) is tracked separately
STATUSES = ["new", "triaged", "reply_drafted", "awaiting_approval", "reply_approved", "replied", "closed", "ignored"]
BUGGY = {"bug", "crash"}

STOP = set("""a an the and or but if then so to of in on at for with from by is are was were be been it its this that
these those i me my we our you your he she they them their his her not no yes do does did done have has had will would
can could should just very really too also only even still again ever all any some more most much many one two game app
play playing played get got make made when what which who how why where there here than as please thanks thank hi hello
dear team pls plz""".split())


@dataclass
class RawItem:
    source: str
    text: str
    source_ref: str = ""
    external_id: str = ""
    author: str = ""
    rating: int | None = None
    language: str = ""
    device: str = ""
    app_version: str = ""
    title: str = ""
    submitted_at: float | None = None
    game_hint: str = ""          # slug, package name, or folder name
    category_hint: str = ""      # e.g. the in-game form's "type" field
    reply_channel: str = ""      # play | email | ingame
    already_replied: bool = False
    raw: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- normalisation
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_MAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_NUM = re.compile(r"\b\d+([.,:]\d+)*\b")
_HEX = re.compile(r"\b0x[0-9a-f]+\b", re.I)
_PUNCT = re.compile(r"[^\w\s]", re.U)


def normalize(text: str) -> str:
    t = (text or "").lower()
    t = _URL.sub(" ", t)
    t = _MAIL.sub(" ", t)
    t = _HEX.sub(" ", t)
    t = _NUM.sub(" ", t)
    t = _PUNCT.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def fingerprint(text: str, author: str = "", game_hint: str = "") -> str:
    # the author is an identity (often an email address): compare it verbatim, only case-folded
    canon = f"{normalize(game_hint)}|{(author or '').strip().lower()}|{normalize(text)}"
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def tokens(text: str) -> set[str]:
    out = set()
    for w in normalize(text).split():
        if len(w) < 3 or w in STOP:
            continue
        # crude stemming so "crashes", "crashing", "crashed" match
        for suf in ("ing", "es", "ed", "s"):
            if len(w) > len(suf) + 3 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ----------------------------------------------------------------------------- rule classifier
_RULES: list[tuple[str, re.Pattern]] = [
    ("abuse", re.compile(r"\b(kill you|idiot|stupid dev|f+u+c+k|scam(mer)?s?|free (coins|gems)|hack(ed)? apk|telegram\.me|whatsapp me)\b", re.I)),
    ("crash", re.compile(r"\b(crash\w*|force[ds]? clos\w*|keeps? closing|closes (itself|by itself|immediately)|shuts down|black screen|freez\w*|frozen|anr|not responding|won'?t (open|start|load)|doesn'?t (open|start|launch))\b", re.I)),
    ("billing", re.compile(r"\b(refund\w*|charged|charge me|purchase\w*|payment|paid|bought|subscription|in.?app|iap|receipt|money back|remove ads (didn'?t|not) work)\b", re.I)),
    ("ads", re.compile(r"\b(ads?|adverts?|advertisement\w*|commercials?|too many ads|ad after|unskippable)\b", re.I)),
    ("bug", re.compile(r"\b(bug\w*|broken|glitch\w*|doesn'?t work|does not work|not working|isn'?t working|error|lost (my )?progress|progress (was )?lost|stuck|can'?t|cannot|wrong|missing|lag\w*|disappear\w*|reset)\b", re.I)),
    ("feature_request", re.compile(r"\b(please add|add (a|an|more|some)|would (be|love) (nice|great|it)|i wish|wish (it|there|you)|feature|suggest\w*|should (have|add)|more levels|dark mode|option to|could you add)\b", re.I)),
    ("praise", re.compile(r"\b(love\w*|great|awesome|amazing|fun|addict\w*|best|relaxing|cute|beautiful|perfect|nice game|well done|enjoy\w*|10/10)\b", re.I)),
]
_POS = re.compile(r"\b(love|great|awesome|amazing|fun|best|relaxing|cute|beautiful|perfect|nice|enjoy|thanks|thank)\w*", re.I)
_NEG = re.compile(r"\b(hate|bad|worst|awful|terrible|annoying|broken|crash|refund|scam|useless|boring|unplayable|angry|disappoint)\w*", re.I)
_CRIT = re.compile(r"\b(every time|always|on (start|launch|startup)|can'?t (even )?(open|start|play)|won'?t (open|start)|lost (all|my) (progress|purchases?)|charged twice|data loss)\b", re.I)


def rule_classify(text: str, rating: int | None = None, hint: str = "") -> dict:
    """Deterministic fallback (and the offline fake engine's brain)."""
    hint = (hint or "").lower().strip().replace(" ", "_")
    hint = {"feature": "feature_request", "request": "feature_request", "suggestion": "feature_request",
            "ad": "ads", "payment": "billing", "purchase": "billing"}.get(hint, hint)
    cat = hint if hint in CATEGORIES and hint != "other" else ""
    if not cat:
        for name, pat in _RULES:
            if pat.search(text or ""):
                cat = name
                break
    if cat == "praise" and rating is not None and rating <= 2:
        cat = "other"
    if not cat:
        cat = "praise" if (rating or 0) >= 4 else "other"
    pos, neg = len(_POS.findall(text or "")), len(_NEG.findall(text or ""))
    if rating is not None:
        sentiment = "positive" if rating >= 4 else ("negative" if rating <= 2 else ("positive" if pos > neg else "negative" if neg > pos else "neutral"))
    else:
        sentiment = "positive" if pos > neg else ("negative" if neg > pos else "neutral")
    if cat in ("crash",):
        sev = "critical" if _CRIT.search(text or "") else "high"
    elif cat == "billing":
        sev = "high"
    elif cat == "bug":
        sev = "high" if _CRIT.search(text or "") else "med"
    elif cat in ("ads", "abuse"):
        sev = "low" if cat == "abuse" else ("med" if sentiment == "negative" else "low")
    else:
        sev = "low"
    return {"category": cat, "sentiment": sentiment, "severity": sev}


def default_reply(item: dict, cls: dict, game_title: str = "the game") -> str | None:
    """Template reply used by the fake engine and as a last-resort draft. None = no reply (abuse)."""
    c = cls["category"]
    if c == "abuse":
        return None
    who = "Thanks for writing to us"
    return {
        "crash": f"{who}, and sorry {game_title} crashed for you. We're looking into it now. If you can, tell us your phone model and what you were doing when it closed - it helps us fix it faster.",
        "bug": f"{who}, and sorry about the trouble. We've logged this as a bug and are working on a fix. We'll let you know when an update is out.",
        "billing": f"{who}. Sorry about the purchase problem. Please email us your order number (from your Google Play receipt) and we'll sort it out. Refunds for Play purchases are handled by Google Play.",
        "ads": f"{who}. We hear you on the ads and are reviewing how often they show. There is a one-time Remove Ads option in the shop if you'd like an ad-free game.",
        "feature_request": f"{who} - great idea! We've added it to our list of things to consider for future updates.",
        "praise": f"Thank you so much for playing {game_title} and for the kind words! It means a lot to our small studio.",
    }.get(c, f"{who}. We read every message and appreciate you taking the time.")


# ----------------------------------------------------------------------------- file parsing
def decode_bytes(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if len(data) > 3 and data[1:2] == b"\x00" and data[3:4] == b"\x00":  # UTF-16 LE without BOM
        try:
            return data.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _ts(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        f = float(v)
        return f / 1000.0 if f > 1e11 else f
    except (TypeError, ValueError):
        pass
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return (datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)).timestamp()
        except ValueError:
            continue
    return None


def _int(v: Any) -> int | None:
    try:
        i = int(float(str(v).strip()))
        return i if 0 <= i <= 5 else None
    except (TypeError, ValueError):
        return None


PLAY_COLS = {"package name", "star rating", "review text"}
ALIASES = {
    "text": ["text", "message", "review", "review text", "body", "comment", "feedback", "content", "description"],
    "title": ["title", "subject", "review title"],
    "rating": ["rating", "stars", "star rating", "score"],
    "version": ["version", "app_version", "app version", "app version name", "build"],
    "game": ["game", "slug", "package", "package name", "app", "app_id"],
    "author": ["author", "name", "user", "player", "player_id", "email", "from", "reviewer"],
    "date": ["date", "created_at", "timestamp", "time", "submitted_at"],
    "id": ["id", "review_id", "feedback_id", "uuid"],
    "device": ["device", "model", "phone"],
    "type": ["type", "category", "kind"],
}


def _pick(row: dict, key: str) -> str:
    low = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
    for a in ALIASES[key]:
        if a in low and low[a] not in (None, ""):
            return str(low[a]).strip()
    return ""


def parse_play_csv(text: str, ref: str) -> list[RawItem]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        r = {str(k).strip(): (v or "").strip() for k, v in row.items() if k}
        body = r.get("Review Text", "")
        title = r.get("Review Title", "")
        if not body and not title:
            continue  # star-only rating: nothing to triage
        submit = r.get("Review Submit Millis Since Epoch") or r.get("Review Submit Date and Time")
        updated = r.get("Review Last Update Millis Since Epoch") or submit
        link = r.get("Review Link", "")
        ext = link or f"{r.get('Package Name', '')}:{submit}:{r.get('Device', '')}"
        replied_at = _ts(r.get("Developer Reply Millis Since Epoch") or r.get("Developer Reply Date and Time"))
        upd = _ts(updated)
        out.append(RawItem(
            source="play", text=body or title, title=title if body else "", source_ref=ref, external_id=ext,
            author="", rating=_int(r.get("Star Rating")), language=r.get("Reviewer Language", ""),
            device=r.get("Device", ""), app_version=r.get("App Version Name", "") or r.get("App Version Code", ""),
            submitted_at=upd, game_hint=r.get("Package Name", ""), reply_channel="play",
            already_replied=bool(r.get("Developer Reply Text")) and (replied_at or 0) >= (upd or 0),
            raw={"review_link": link, "version_code": r.get("App Version Code", ""), "updated": updated}))
    return out


def parse_generic_csv(text: str, ref: str, folder_hint: str = "") -> list[RawItem]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        body = _pick(row, "text")
        if not body:
            continue
        out.append(RawItem(source="inbox", text=body, title=_pick(row, "title"), source_ref=ref,
                           external_id=_pick(row, "id"), author=_pick(row, "author"), rating=_int(_pick(row, "rating")),
                           app_version=_pick(row, "version"), submitted_at=_ts(_pick(row, "date")),
                           device=_pick(row, "device"), game_hint=_pick(row, "game") or folder_hint,
                           category_hint=_pick(row, "type"), reply_channel="email" if "@" in _pick(row, "author") else ""))
    return out


def parse_json_feedback(text: str, ref: str, folder_hint: str = "", source: str = "ingame") -> list[RawItem]:
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        defaults = {k: v for k, v in data.items() if k != "items"}
        rows = [dict(defaults, **r) for r in data["items"] if isinstance(r, dict)]
    elif isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        rows = [data]
    else:
        rows = []
    out = []
    for r in rows:
        body = _pick(r, "text")
        log = r.get("log") or r.get("stack") or r.get("stacktrace") or ""
        if not body and not log:
            continue
        if log:
            body = (body + "\n\nLog:\n" + str(log)[:4000]).strip()
        out.append(RawItem(source=source, text=body, title=_pick(r, "title"), source_ref=ref, external_id=_pick(r, "id"),
                           author=_pick(r, "author"), rating=_int(_pick(r, "rating")), app_version=_pick(r, "version"),
                           device=_pick(r, "device"), submitted_at=_ts(_pick(r, "date")),
                           game_hint=_pick(r, "game") or folder_hint, category_hint=_pick(r, "type"),
                           reply_channel="ingame", raw={k: v for k, v in r.items() if k not in ("log", "stack", "stacktrace")}))
    return out


_HDR = re.compile(r"^(game|version|from|rating|device|date|type|title|subject|id)\s*:\s*(.*)$", re.I)


def parse_txt(text: str, ref: str, folder_hint: str = "") -> list[RawItem]:
    out = []
    for chunk in re.split(r"\n-{3,}\s*\n", text):
        lines = chunk.strip().splitlines()
        meta: dict[str, str] = {}
        while lines and _HDR.match(lines[0].strip()):
            m = _HDR.match(lines.pop(0).strip())
            meta[m.group(1).lower()] = m.group(2).strip()
        body = "\n".join(lines).strip()
        if not body:
            continue
        frm = meta.get("from", "")
        out.append(RawItem(source="inbox", text=body, title=meta.get("title") or meta.get("subject", ""), source_ref=ref,
                           external_id=meta.get("id", ""), author=frm, rating=_int(meta.get("rating")),
                           app_version=meta.get("version", ""), device=meta.get("device", ""),
                           submitted_at=_ts(meta.get("date")), game_hint=meta.get("game") or folder_hint,
                           category_hint=meta.get("type", ""), reply_channel="email" if "@" in frm else ""))
    return out


def parse_file(path: Path, root: Path) -> list[RawItem]:
    text = decode_bytes(path.read_bytes()[:20_000_000])
    rel = str(path.relative_to(root)) if root in path.parents else path.name
    folder = path.parent.name if path.parent != root else ""
    suf = path.suffix.lower()
    if suf == ".csv":
        head = text.splitlines()[0].lower() if text.strip() else ""
        if all(c in head for c in PLAY_COLS):
            return parse_play_csv(text, rel)
        return parse_generic_csv(text, rel, folder)
    if suf == ".json":
        return parse_json_feedback(text, rel, folder)
    if suf == ".txt":
        return parse_txt(text, rel, folder)
    return []


FEEDBACK_EXT = {".csv", ".json", ".txt"}


def scan_folder(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in FEEDBACK_EXT
                  and not any(part.startswith(".") or part == "processed" for part in p.relative_to(root).parts))


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- IMAP (read-only)
def imap_config() -> dict | None:
    host, user, pw = (os.environ.get(k, "") for k in ("STUDIO_IMAP_HOST", "STUDIO_IMAP_USER", "STUDIO_IMAP_PASSWORD"))
    if not (host and user and pw):
        return None
    return {"host": host, "user": user, "password": pw, "port": int(os.environ.get("STUDIO_IMAP_PORT", "993") or 993),
            "ssl": os.environ.get("STUDIO_IMAP_SSL", "1") != "0"}


def _dec(h: str | None) -> str:
    if not h:
        return ""
    parts = []
    for b, enc in email.header.decode_header(h):
        parts.append(b.decode(enc or "utf-8", errors="replace") if isinstance(b, bytes) else b)
    return "".join(parts)


def _body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                return (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="replace")
                return re.sub(r"<[^>]+>", " ", html)
        return ""
    return (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", errors="replace")


def strip_quoted(text: str) -> str:
    keep = []
    for line in text.splitlines():
        if line.startswith(">") or re.match(r"^On .+ wrote:$", line.strip()):
            break
        keep.append(line)
    return "\n".join(keep).strip()


def fetch_imap(folder: str = "INBOX", search: str = "UNSEEN", limit: int = 50, factory=None) -> list[RawItem]:
    """Read messages without marking them read (folder opened read-only, BODY.PEEK)."""
    cfg = imap_config()
    if not cfg:
        raise RuntimeError("IMAP enabled but STUDIO_IMAP_HOST / STUDIO_IMAP_USER / STUDIO_IMAP_PASSWORD are not set in .env")
    factory = factory or (imaplib.IMAP4_SSL if cfg["ssl"] else imaplib.IMAP4)
    m = factory(cfg["host"], cfg["port"])
    try:
        m.login(cfg["user"], cfg["password"])
        m.select(folder, readonly=True)
        typ, data = m.search(None, *(search or "ALL").split())
        ids = (data[0] or b"").split()[-limit:] if typ == "OK" else []
        out = []
        for i in ids:
            typ, parts = m.fetch(i, "(BODY.PEEK[])")
            if typ != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            msg = email.message_from_bytes(parts[0][1])
            subject, frm = _dec(msg.get("Subject")), _dec(msg.get("From"))
            body = strip_quoted(_body(msg))
            if not body.strip():
                continue
            date = msg.get("Date")
            try:
                ts = email.utils.parsedate_to_datetime(date).timestamp() if date else None
            except (TypeError, ValueError):
                ts = None
            out.append(RawItem(source="imap", text=body[:20000], title=subject, source_ref=f"imap:{folder}",
                               external_id=msg.get("Message-ID", "") or f"imap:{i.decode()}",
                               author=email.utils.parseaddr(frm)[1] or frm, submitted_at=ts, game_hint=subject,
                               reply_channel="email"))
        return out
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def iter_batches(seq: list, n: int) -> Iterable[list]:
    n = max(1, n)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
