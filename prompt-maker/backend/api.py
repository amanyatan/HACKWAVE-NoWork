"""HTTP API for prompt history, code projects and zip download. Everything is keyed by a random client_id kept in the browser."""
import datetime
import io
import time
import uuid
import zipfile

from aiohttp import web

import codegen
import docgen
from db import DbError

# shortcut: client_id is a random id in the browser, not a login; anyone holding it can read that history. Upgrade to Supabase Auth with real row level security when accounts are added.


def err(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


def limited(request, bucket: str, limit: int, window: int) -> bool:
    """Per-IP sliding window, one counter per bucket."""
    hits = request.app["limits"].setdefault((bucket, request.remote), [])
    now = time.monotonic()
    hits[:] = [t for t in hits if now - t < window]
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


def as_uuid(value) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise ValueError("client_id must be a UUID") from None


def text(value, max_len: int) -> str:
    return value.strip()[:max_len] if isinstance(value, str) else ""


async def body_of(request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise ValueError("body must be JSON") from None
    if not isinstance(data, dict):
        raise ValueError("body must be an object")
    return data


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def health(request):
    db = request.app["db"]
    if not db.configured:
        return web.json_response({"db": False, "reason": "not configured"})
    try:
        await db.select("prompt_sets", {"select": "id", "limit": "1"})
    except DbError as e:
        return web.json_response({"db": False, "reason": str(e)})
    return web.json_response({"db": True})


async def create_set(request):
    if limited(request, "rw", 60, 60):
        return err(429, "rate limited")
    try:
        data = await body_of(request)
        client_id = as_uuid(data.get("client_id"))
        ai_tool, steps = docgen.validate(data)
    except ValueError as e:
        return err(400, str(e))
    row = {
        "client_id": client_id,
        "title": text(data.get("title"), 120) or steps[0]["title"],
        "summary": text(data.get("summary"), 1000),
        "ai_tool": ai_tool,
        "wants_code": data.get("wants_code") is True,
    }
    db = request.app["db"]
    try:
        [created] = await db.insert("prompt_sets", [row])
        rows = await db.insert("prompt_steps", [{"set_id": created["id"], "position": i + 1, **s} for i, s in enumerate(steps)])
    except DbError as e:
        return err(503, str(e))
    return web.json_response({"id": created["id"], "steps": [{"id": r["id"], "position": r["position"]} for r in rows]})


async def list_sets(request):
    if limited(request, "rw", 60, 60):
        return err(429, "rate limited")
    try:
        client_id = as_uuid(request.query.get("client_id"))
    except ValueError as e:
        return err(400, str(e))
    db = request.app["db"]
    try:
        sets = await db.select("prompt_sets", {"client_id": f"eq.{client_id}", "order": "created_at.desc", "limit": "20", "select": "*"})
        steps = []
        if sets:
            ids = ",".join(s["id"] for s in sets)
            steps = await db.select("prompt_steps", {"set_id": f"in.({ids})", "order": "position.asc", "select": "id,set_id,position,title,prompt,downloaded_at"})
    except DbError as e:
        return err(503, str(e))
    for s in sets:
        s["steps"] = [st for st in steps if st["set_id"] == s["id"]]
    return web.json_response({"sets": sets})


async def mark_downloaded(request):
    if limited(request, "rw", 60, 60):
        return err(429, "rate limited")
    try:
        client_id = as_uuid((await body_of(request)).get("client_id"))
        step_id = as_uuid(request.match_info["step_id"])
    except ValueError as e:
        return err(400, str(e))
    db = request.app["db"]
    try:
        step = await db.select("prompt_steps", {"id": f"eq.{step_id}", "select": "id,set_id"})
        owner = await db.select("prompt_sets", {"id": f"eq.{step[0]['set_id']}", "client_id": f"eq.{client_id}", "select": "id"}) if step else []
        if not owner:
            return err(404, "step not found")
        set_id = step[0]["set_id"]
        await db.update("prompt_steps", {"id": f"eq.{step_id}"}, {"downloaded_at": now_iso()})
        left = await db.select("prompt_steps", {"set_id": f"eq.{set_id}", "downloaded_at": "is.null", "select": "id"})
        if not left:
            await db.update("prompt_sets", {"id": f"eq.{set_id}"}, {"completed_at": now_iso()})
    except DbError as e:
        return err(503, str(e))
    return web.json_response({"completed": not left})


async def create_code(request):
    if limited(request, "code", 4, 600):  # each call is a paid model request
        return err(429, "too many code requests, try again in a few minutes")
    try:
        data = await body_of(request)
        client_id = as_uuid(data.get("client_id"))
        set_id = as_uuid(data["set_id"]) if data.get("set_id") else None
        _, steps = docgen.validate(data)
    except ValueError as e:
        return err(400, str(e))
    client = request.app["client"]
    if client is None:
        return err(503, "GEMINI_API_KEY is not set on the server")
    title = text(data.get("title"), 120) or "My project"
    try:
        files = await codegen.generate(client, title, text(data.get("summary"), 1000), steps)
    except Exception as e:  # model error, timeout or invalid output; the caller can retry
        print(f"code generation failed: {e!r}")
        return err(502, "code generation failed, please try again")
    project_id = None
    try:
        [saved] = await request.app["db"].insert("code_projects", [{"client_id": client_id, "set_id": set_id, "title": title, "files": files}])
        project_id = saved["id"]
    except DbError:
        pass  # the files are still returned; they just won't be in history
    return web.json_response({"id": project_id, "title": title, "files": files, "saved": project_id is not None})


async def latest_code(request):
    if limited(request, "rw", 60, 60):
        return err(429, "rate limited")
    try:
        client_id = as_uuid(request.query.get("client_id"))
    except ValueError as e:
        return err(400, str(e))
    try:
        rows = await request.app["db"].select("code_projects", {"client_id": f"eq.{client_id}", "order": "created_at.desc", "limit": "1", "select": "*"})
    except DbError as e:
        return err(503, str(e))
    return web.json_response({"project": rows[0] if rows else None})


async def make_zip(request):
    if limited(request, "rw", 60, 60):
        return err(429, "rate limited")
    try:
        files = codegen.validate_files((await body_of(request)).get("files"))
    except ValueError as e:
        return err(400, str(e))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.writestr(f["path"], f["content"])
    return web.Response(body=out.getvalue(), content_type="application/zip", headers={"Content-Disposition": 'attachment; filename="nowork-project.zip"'})


def add_routes(app: web.Application) -> None:
    app["limits"] = {}
    app.router.add_get("/api/health", health)
    app.router.add_post("/api/prompt-sets", create_set)
    app.router.add_get("/api/prompt-sets", list_sets)
    app.router.add_post("/api/prompt-steps/{step_id}/downloaded", mark_downloaded)
    app.router.add_post("/api/code", create_code)
    app.router.add_get("/api/code", latest_code)
    app.router.add_post("/api/zip", make_zip)
