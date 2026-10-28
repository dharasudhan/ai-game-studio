"""FastAPI dashboard (Approval Desk) on http://localhost:8787. Binds to 127.0.0.1 only."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import API_KEY_ENV, ENGINES, SECRET_ENV, SETTINGS_SCHEMA
from .wizard import check_prereqs
from .worker import Worker, retry_job
from .workflow import Studio

STATIC = Path(__file__).parent / "static"
EDITABLE = set(SETTINGS_SCHEMA)


class NewGame(BaseModel):
    goal: str
    title: str = ""


class Decision(BaseModel):
    note: str = ""


class AgentPatch(BaseModel):
    enabled: bool | None = None
    paused: bool | None = None
    engine: str | None = None
    model: str | None = None
    effort: str | None = None


class RunNow(BaseModel):
    game_id: int | None = None


class PromptBody(BaseModel):
    content: str


class TextBody(BaseModel):
    text: str = ""


class StatusBody(BaseModel):
    status: str


class GameBody(BaseModel):
    game_id: int | None = None


class VersionBody(BaseModel):
    version: str = ""


class StepBody(BaseModel):
    step: str


class PresetBody(BaseModel):
    preset: str


class RolesBody(BaseModel):
    roles: dict


class KeyBody(BaseModel):
    name: str
    value: str
    backend: str = "keychain"


class TestBody(BaseModel):
    deep: bool = False


class IdentityBody(BaseModel):
    studio_name: str = ""
    package_prefix: str = ""
    contact_email: str = ""
    studio_website: str = ""
    github_owner: str = ""
    play_account_type: str = "personal"


def validate_setting(key: str, value) -> str:
    import json
    import re
    spec = SETTINGS_SCHEMA[key]
    v = "" if value is None else str(value).strip()
    t = spec["type"]
    if t == "bool":
        if v.lower() not in ("0", "1", "true", "false", "on", "off", "yes", "no", ""):
            raise ValueError(f"{key}: expected on/off")
        return "1" if v.lower() in ("1", "true", "on", "yes") else "0"
    if t == "int":
        try:
            n = int(float(v or 0))
        except ValueError:
            raise ValueError(f"{key}: expected a number")
        if n < 0:
            raise ValueError(f"{key}: must be 0 or more")
        if key == "concurrency" and not 1 <= n <= 4:
            raise ValueError("concurrency: 1 to 4")
        return str(n)
    if t == "choice":
        if v not in spec["choices"]:
            raise ValueError(f"{key}: one of {spec['choices']}")
        return v
    if t == "json":
        try:
            o = json.loads(v or "{}")
        except json.JSONDecodeError:
            raise ValueError(f"{key}: invalid JSON")
        if not isinstance(o, dict):
            raise ValueError(f"{key}: expected a JSON object")
        return json.dumps(o)
    if t == "time":
        if v and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", v):
            raise ValueError(f"{key}: expected HH:MM")
        return v
    if t == "range":
        if v and not re.fullmatch(r"([01]?\d|2[0-4]):[0-5]\d-([01]?\d|2[0-4]):[0-5]\d", v):
            raise ValueError(f"{key}: expected HH:MM-HH:MM")
        return v
    if len(v) > 2000:
        raise ValueError(f"{key}: too long")
    return v


def create_app(studio: Studio | None = None, start_worker: bool = True) -> FastAPI:
    st = studio or Studio()
    worker = Worker(st) if start_worker else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()

    app = FastAPI(title="AI Game Studio", lifespan=lifespan)
    app.state.studio = st

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        # Browsers cannot send this custom header cross-site without a CORS preflight we never allow.
        if request.method in ("POST", "PUT", "DELETE") and request.headers.get("x-studio") != "1":
            return JSONResponse({"detail": "missing X-Studio header"}, status_code=403)
        return await call_next(request)

    def guard(fn, *a):
        try:
            return fn(*a)
        except KeyError as e:
            raise HTTPException(404, str(e).strip("'\""))
        except ValueError as e:
            raise HTTPException(400, str(e))

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    # ---------------------------------------------------------------- status & agents
    @app.get("/api/status")
    def status():
        return st.status()

    @app.get("/api/agents")
    def agents():
        s = st.status()
        return {"agents": s["agents"], "games": s["games"], "engines": [""] + ENGINES,
                "efforts": ["", "low", "medium", "high"]}

    @app.post("/api/agents/{name}")
    def patch_agent(name: str, body: AgentPatch):
        return guard(lambda: st.set_agent(name, **body.model_dump()))

    @app.post("/api/agents/{name}/run")
    def run_agent(name: str, body: RunNow):
        return {"job_id": guard(st.run_now, name, body.game_id)}

    @app.get("/api/agents/{name}/prompt")
    def get_prompt(name: str):
        return guard(st.get_prompt, name)

    @app.post("/api/agents/{name}/prompt")
    def save_prompt(name: str, body: PromptBody):
        return guard(st.save_prompt, name, body.content)

    @app.post("/api/agents/{name}/prompt/reset")
    def reset_prompt(name: str):
        return guard(st.reset_prompt, name)

    @app.get("/api/agents/{name}/feedback")
    def agent_feedback(name: str):
        return {"notes": guard(st.agent_feedback, name)}

    @app.delete("/api/agent-feedback/{fid}")
    def delete_agent_feedback(fid: int):
        guard(st.delete_agent_feedback, fid)
        return {"ok": True}

    @app.post("/api/agents-all/{action}")
    def all_agents(action: str):
        if action not in ("pause", "resume"):
            raise HTTPException(400, "pause or resume")
        for a in st.agents_brief():
            st.set_agent(a["name"], paused=action == "pause")
        return {"ok": True}

    # ---------------------------------------------------------------- settings
    @app.get("/api/settings")
    def get_settings():
        cur = st.db.settings()
        return {"values": {k: cur.get(k, "") for k in SETTINGS_SCHEMA}, "schema": SETTINGS_SCHEMA,
                "secrets": {k: ("set" if (st.secrets.get(k) if k in API_KEY_ENV else os.environ.get(k)) else "not set") for k in SECRET_ENV},
                "feedback_dir": str(st.feedback_dir()), "prompts_dir": str(st.paths.prompts), "home": str(st.paths.home)}

    # ---------------------------------------------------------------- setup wizard + providers
    @app.get("/api/setup")
    def setup_state():
        return st.setup_state()

    @app.get("/api/setup/prereqs")
    def setup_prereqs():
        checks = check_prereqs(st.db.settings())
        return {"checks": checks, "ok": all(c["ok"] for c in checks if c["required"])}

    @app.post("/api/setup/step")
    def setup_step(body: StepBody):
        guard(st.set_setup_step, body.step)
        return {"step": body.step}

    @app.post("/api/setup/preset")
    def setup_preset(body: PresetBody):
        return {"roles": guard(st.apply_preset, body.preset)}

    @app.post("/api/setup/roles")
    def setup_roles(body: RolesBody):
        return {"roles": guard(st.apply_roles, body.roles)}

    @app.get("/api/setup/keys")
    def setup_keys():
        return st.keys_status()

    @app.post("/api/setup/keys")
    def setup_save_key(body: KeyBody):
        return guard(st.save_key, body.name, body.value, body.backend)

    @app.post("/api/setup/identity")
    def setup_identity(body: IdentityBody):
        return guard(st.save_identity, body.model_dump())

    @app.post("/api/setup/finish")
    def setup_finish():
        return st.finish_setup()

    @app.get("/api/providers")
    def providers():
        return {"providers": st.providers_info()}

    @app.post("/api/providers/{pid}/test")
    def provider_test(pid: str, body: TestBody):
        return st.test_connection(pid, body.deep)

    # ---------------------------------------------------------------- launch audit
    @app.post("/api/games/{gid}/audit")
    def run_audit(gid: int):
        return {"job_id": guard(st.request_audit, gid)}

    @app.get("/api/games/{gid}/audit")
    def latest_audit(gid: int):
        guard(st.game, gid)
        au = st.latest_audit(gid)
        if not au:
            return {"audit": None, "block_reason": st.release_block_reason(gid)}
        au = dict(au)
        import json as _j
        au["items"] = _j.loads(au.pop("items_json") or "[]")
        return {"audit": au, "block_reason": st.release_block_reason(gid)}

    @app.get("/api/audits/{aid}/pdf")
    def audit_pdf(aid: int):
        au = st.db.one("SELECT pdf_path FROM audits WHERE id=?", aid)
        if not au or not au["pdf_path"] or not Path(au["pdf_path"]).exists():
            raise HTTPException(404, "audit PDF not found")
        return FileResponse(au["pdf_path"], media_type="application/pdf", filename=Path(au["pdf_path"]).name)

    # ---------------------------------------------------------------- feedback (Customer Support)
    @app.get("/api/feedback")
    def feedback(game_id: int | None = None, status: str = "", category: str = "", severity: str = "", source: str = "",
                 q: str = "", bug: str = "", limit: int = 200):
        return st.feedback_query(game_id, status, category, severity, source, q, bug, limit)

    @app.get("/api/feedback/{iid}")
    def feedback_item(iid: int):
        it = st.db.one("SELECT * FROM feedback_items WHERE id=?", iid)
        if not it:
            raise HTTPException(404, "feedback item not found")
        it.pop("raw_json", None)
        return it

    @app.post("/api/feedback/upload")
    async def feedback_upload(file: UploadFile = File(...), game: str = ""):
        data = await file.read()
        if len(data) > 20_000_000:
            raise HTTPException(413, "file too large (20 MB max)")
        return {"job_id": guard(st.add_feedback_file, file.filename or "feedback.txt", data, game)}

    @app.post("/api/feedback/ingame")
    async def feedback_ingame(request: Request):
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "send JSON")
        return {"job_id": guard(st.add_ingame_feedback, payload)}

    @app.post("/api/feedback/scan")
    def feedback_scan():
        return {"job_id": st.enqueue(None, "support", "support.ingest", {"reason": "scan now"}, front=True)}

    @app.post("/api/feedback/{iid}/status")
    def feedback_status(iid: int, body: StatusBody):
        return guard(st.set_feedback_status, iid, body.status)

    @app.post("/api/feedback/{iid}/draft")
    def feedback_draft(iid: int, body: TextBody):
        return guard(st.edit_reply_draft, iid, body.text)

    @app.post("/api/feedback/{iid}/request_approval")
    def feedback_request(iid: int):
        return {"approval_id": guard(st.request_reply_approval, iid)}

    @app.post("/api/feedback/{iid}/flag_bug")
    def feedback_flag(iid: int):
        return {"job_id": guard(st.flag_bug, iid)}

    @app.post("/api/feedback/{iid}/game")
    def feedback_game(iid: int, body: GameBody):
        return guard(st.set_feedback_game, iid, body.game_id)

    @app.post("/api/games/{gid}/version")
    def game_version(gid: int, body: VersionBody):
        guard(st.game, gid)
        st.set_game(gid, version=body.version.strip()[:40])
        return st.game(gid)

    @app.post("/api/games/{gid}/fixed_replies")
    def fixed_replies(gid: int, body: VersionBody):
        g = guard(st.game, gid)
        jid = st.queue_fixed_replies(gid, body.version.strip() or g.get("version") or "")
        if not jid:
            raise HTTPException(400, "no fixed player reports waiting for a follow-up reply")
        return {"job_id": jid}

    @app.get("/api/bugs")
    def bugs(game_id: int | None = None):
        rows = st.db.all("SELECT t.*, g.title AS game_title FROM tickets t LEFT JOIN games g ON g.id=t.game_id WHERE t.kind='bug'"
                         + (" AND t.game_id=?" if game_id else "") + " ORDER BY t.id DESC", *((game_id,) if game_id else ()))
        for r in rows:
            r["feedback_items"] = st.linked_item_ids(r["id"])
        return {"bugs": rows}

    @app.get("/api/state")
    def state(game_id: int | None = None):
        return st.state(game_id)

    @app.post("/api/games")
    def new_game(body: NewGame):
        return {"game_id": guard(st.new_game, body.goal, body.title)}

    @app.post("/api/approvals/{aid}/approve")
    def approve(aid: int):
        return guard(st.approve, aid)

    @app.post("/api/approvals/{aid}/reject")
    def reject(aid: int, body: Decision):
        return guard(st.reject, aid, body.note)

    @app.post("/api/pause")
    def pause():
        st.db.set("paused", "1")
        st.db.set("pause_reason", "paused by you")
        return {"paused": True}

    @app.post("/api/resume")
    def resume():
        st.db.set("paused", "0")
        st.db.set("pause_reason", "")
        st.log("Queue resumed")
        return {"paused": False}

    @app.post("/api/games/{gid}/standup")
    def standup(gid: int):
        guard(st.game, gid)
        return {"job_id": st.request_standup(gid)}

    @app.post("/api/games/{gid}/inbox")
    async def inbox(gid: int, file: UploadFile = File(...)):
        data = await file.read()
        if len(data) > 20_000_000:
            raise HTTPException(413, "file too large (20 MB max)")
        return {"job_id": guard(st.add_inbox_file, gid, file.filename or "upload.txt", data)}

    @app.post("/api/jobs/{jid}/retry")
    def retry(jid: int):
        guard(retry_job, st, jid)
        return {"ok": True}

    @app.post("/api/ledger/{lid}/spent")
    def spent(lid: int):
        guard(st.mark_spent, lid)
        return {"ok": True}

    @app.post("/api/settings")
    def settings(body: dict):
        bad = [k for k in body if k not in EDITABLE]
        if bad:
            raise HTTPException(400, f"unknown or read-only settings: {bad}")
        clean = {k: guard(validate_setting, k, v) for k, v in body.items()}
        for k, v in clean.items():
            st.db.set(k, v)
        if clean:
            st.log("Settings changed: " + ", ".join(sorted(clean)), agent="owner")
        return st.db.settings()

    @app.get("/api/docs/{did}")
    def doc(did: int):
        d = st.db.one("SELECT * FROM docs WHERE id=?", did)
        if not d:
            raise HTTPException(404, "doc not found")
        return d

    @app.get("/api/runs/{rid}")
    def run(rid: int):
        r = st.db.one("SELECT * FROM runs WHERE id=?", rid)
        if not r:
            raise HTTPException(404, "run not found")
        return r

    @app.get("/api/prompts")
    def prompts():
        return {p.stem: p.read_text() for p in sorted(st.paths.prompts.glob("*.md"))}

    return app


def main() -> None:
    import uvicorn
    port = int(os.environ.get("STUDIO_PORT", "8787"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
