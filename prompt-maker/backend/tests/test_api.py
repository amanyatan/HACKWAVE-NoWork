import io
import json
import types
import uuid
import zipfile

import pytest

import server
from db import DbError

CLIENT = str(uuid.uuid4())
OTHER = str(uuid.uuid4())


class FakeDb:
    """In-memory stand-in for Supabase: supports eq., in.(...), is.null, order and limit."""

    configured = True

    def __init__(self, fail=False):
        self.tables = {"prompt_sets": [], "prompt_steps": [], "code_projects": []}
        self.fail = fail
        self.n = 0

    def _check(self):
        if self.fail:
            raise DbError("boom")

    def _match(self, row, params):
        for key, expr in params.items():
            if key in ("select", "order", "limit"):
                continue
            op, _, val = expr.partition(".")
            if op == "eq" and str(row.get(key)) != val:
                return False
            if op == "in" and str(row.get(key)) not in val.strip("()").split(","):
                return False
            if op == "is" and val == "null" and row.get(key) is not None:
                return False
        return True

    async def insert(self, table, rows):
        self._check()
        out = []
        for r in rows:
            self.n += 1
            row = {"id": str(uuid.uuid4()), "created_at": f"{self.n:06d}", "completed_at": None, "downloaded_at": None, **r}
            self.tables[table].append(row)
            out.append(dict(row))
        return out

    async def select(self, table, params):
        self._check()
        rows = [dict(r) for r in self.tables[table] if self._match(r, params)]
        if "order" in params:
            col, _, direction = params["order"].partition(".")
            rows.sort(key=lambda r: r[col], reverse=direction == "desc")
        return rows[: int(params["limit"])] if "limit" in params else rows

    async def update(self, table, params, values):
        self._check()
        hit = [r for r in self.tables[table] if self._match(r, params)]
        for r in hit:
            r.update(values)
        return [dict(r) for r in hit]

    async def close(self):
        pass


class FakeGemini:
    def __init__(self, text):
        self.auth_tokens = None
        self.aio = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=self._gen))
        self._text = text

    async def _gen(self, **kwargs):
        return types.SimpleNamespace(text=self._text)


GOOD_CODE = json.dumps({"files": [
    {"path": "index.html", "content": "<link rel=stylesheet href=style.css><script src=script.js></script>"},
    {"path": "style.css", "content": "body{}"},
    {"path": "script.js", "content": "console.log(1)"},
]})
STEPS = [{"title": f"Step {i + 1}", "prompt": f"Prompt text {i + 1}"} for i in range(6)]


async def client_for(aiohttp_client, db=None, gemini=None):
    return await aiohttp_client(server.make_app(gemini, db or FakeDb()))


async def make_set(c, client_id=CLIENT, steps=STEPS):
    r = await c.post("/api/prompt-sets", json={"client_id": client_id, "title": "Todo", "summary": "s", "ai_tool": "Cursor", "wants_code": True, "steps": steps})
    return r.status, await r.json()


async def test_create_and_list_sets(aiohttp_client):
    c = await client_for(aiohttp_client)
    status, made = await make_set(c)
    assert status == 200 and len(made["steps"]) == 6
    listed = await (await c.get("/api/prompt-sets", params={"client_id": CLIENT})).json()
    assert [s["title"] for s in listed["sets"]] == ["Todo"]
    assert [st["position"] for st in listed["sets"][0]["steps"]] == [1, 2, 3, 4, 5, 6]
    assert listed["sets"][0]["wants_code"] is True
    other = await (await c.get("/api/prompt-sets", params={"client_id": OTHER})).json()
    assert other["sets"] == []  # history is per client


async def test_newest_set_first(aiohttp_client):
    c = await client_for(aiohttp_client)
    await c.post("/api/prompt-sets", json={"client_id": CLIENT, "title": "First", "steps": STEPS})
    await c.post("/api/prompt-sets", json={"client_id": CLIENT, "title": "Second", "steps": STEPS})
    listed = await (await c.get("/api/prompt-sets", params={"client_id": CLIENT})).json()
    assert [s["title"] for s in listed["sets"]] == ["Second", "First"]


async def test_downloading_every_step_completes_the_set(aiohttp_client):
    c = await client_for(aiohttp_client)
    _, made = await make_set(c, steps=STEPS[:2])
    first, second = made["steps"]
    r1 = await (await c.post(f"/api/prompt-steps/{first['id']}/downloaded", json={"client_id": CLIENT})).json()
    assert r1 == {"completed": False}
    r2 = await (await c.post(f"/api/prompt-steps/{second['id']}/downloaded", json={"client_id": CLIENT})).json()
    assert r2 == {"completed": True}
    listed = await (await c.get("/api/prompt-sets", params={"client_id": CLIENT})).json()
    assert listed["sets"][0]["completed_at"] is not None
    assert all(st["downloaded_at"] for st in listed["sets"][0]["steps"])


async def test_cannot_mark_someone_elses_step(aiohttp_client):
    c = await client_for(aiohttp_client)
    _, made = await make_set(c)
    r = await c.post(f"/api/prompt-steps/{made['steps'][0]['id']}/downloaded", json={"client_id": OTHER})
    assert r.status == 404
    assert (await c.post(f"/api/prompt-steps/{uuid.uuid4()}/downloaded", json={"client_id": CLIENT})).status == 404


@pytest.mark.parametrize("body", [{}, {"client_id": "nope", "steps": STEPS}, {"client_id": CLIENT, "steps": []}, {"client_id": CLIENT, "steps": [{"title": "x"}]}])
async def test_create_set_rejects_bad_input(aiohttp_client, body):
    c = await client_for(aiohttp_client)
    assert (await c.post("/api/prompt-sets", json=body)).status == 400


async def test_bad_ids_and_non_json(aiohttp_client):
    c = await client_for(aiohttp_client)
    assert (await c.get("/api/prompt-sets", params={"client_id": "x"})).status == 400
    assert (await c.get("/api/prompt-sets")).status == 400
    assert (await c.post("/api/prompt-sets", data="not json")).status == 400
    assert (await c.post("/api/prompt-steps/not-a-uuid/downloaded", json={"client_id": CLIENT})).status == 400


async def test_database_failure_is_503_not_a_crash(aiohttp_client):
    c = await client_for(aiohttp_client, db=FakeDb(fail=True))
    assert (await make_set(c))[0] == 503
    assert (await c.get("/api/prompt-sets", params={"client_id": CLIENT})).status == 503
    assert (await c.get("/api/code", params={"client_id": CLIENT})).status == 503
    assert (await (await c.get("/api/health")).json())["db"] is False


async def test_health_ok(aiohttp_client):
    c = await client_for(aiohttp_client)
    assert await (await c.get("/api/health")).json() == {"db": True}


CODE_BODY = {"client_id": CLIENT, "title": "Todo app", "summary": "A to-do list", "steps": STEPS}


async def test_code_generation_saves_and_returns_files(aiohttp_client):
    db = FakeDb()
    c = await client_for(aiohttp_client, db=db, gemini=FakeGemini(GOOD_CODE))
    r = await c.post("/api/code", json=CODE_BODY)
    body = await r.json()
    assert r.status == 200 and body["saved"] is True
    assert {f["path"] for f in body["files"]} == {"index.html", "style.css", "script.js"}
    latest = await (await c.get("/api/code", params={"client_id": CLIENT})).json()
    assert latest["project"]["title"] == "Todo app" and len(latest["project"]["files"]) == 3
    assert (await (await c.get("/api/code", params={"client_id": OTHER})).json())["project"] is None


async def test_code_generation_still_returns_files_when_db_is_down(aiohttp_client):
    c = await client_for(aiohttp_client, db=FakeDb(fail=True), gemini=FakeGemini(GOOD_CODE))
    body = await (await c.post("/api/code", json=CODE_BODY)).json()
    assert body["saved"] is False and len(body["files"]) == 3


@pytest.mark.parametrize(
    "output",
    [
        "not json at all",
        json.dumps({"files": []}),
        json.dumps({"files": [{"path": "style.css", "content": "x"}]}),  # no index.html
        json.dumps({"files": [{"path": "../evil.html", "content": "x"}, {"path": "index.html", "content": "x"}]}),
        json.dumps({"files": [{"path": "index.html", "content": "x" * 130_000}]}),
    ],
    ids=["not-json", "empty", "no-index", "path-traversal", "file-too-large"],
)
async def test_bad_model_output_is_502(aiohttp_client, output):
    c = await client_for(aiohttp_client, gemini=FakeGemini(output))
    assert (await c.post("/api/code", json=CODE_BODY)).status == 502


async def test_code_requires_gemini_key_and_valid_body(aiohttp_client):
    app = server.make_app(None, FakeDb())
    app["client"] = None  # no GEMINI_API_KEY on the server
    c = await aiohttp_client(app)
    assert (await c.post("/api/code", json=CODE_BODY)).status == 503
    assert (await c.post("/api/code", json={"client_id": CLIENT})).status == 400


async def test_code_endpoint_is_rate_limited(aiohttp_client):
    c = await client_for(aiohttp_client, gemini=FakeGemini(GOOD_CODE))
    for _ in range(4):
        assert (await c.post("/api/code", json=CODE_BODY)).status == 200
    assert (await c.post("/api/code", json=CODE_BODY)).status == 429


async def test_zip_contains_files(aiohttp_client):
    c = await client_for(aiohttp_client)
    files = [{"path": "index.html", "content": "<h1>hi</h1>"}, {"path": "css/style.css", "content": "body{}"}]
    r = await c.post("/api/zip", json={"files": files})
    assert r.status == 200 and r.headers["Content-Type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(await r.read()))
    assert sorted(z.namelist()) == ["css/style.css", "index.html"]
    assert z.read("index.html") == b"<h1>hi</h1>"


@pytest.mark.parametrize("path", ["../x.html", "/abs.html", "a//b.html", "a\\b.html", "dir/", "", "x" * 90])
async def test_zip_rejects_unsafe_paths(aiohttp_client, path):
    c = await client_for(aiohttp_client)
    assert (await c.post("/api/zip", json={"files": [{"path": path, "content": "x"}]})).status == 400


async def test_zip_rejects_duplicates_and_empty(aiohttp_client):
    c = await client_for(aiohttp_client)
    dup = [{"path": "a.html", "content": "1"}, {"path": "a.html", "content": "2"}]
    assert (await c.post("/api/zip", json={"files": dup})).status == 400
    assert (await c.post("/api/zip", json={"files": []})).status == 400
    assert (await c.post("/api/zip", json={})).status == 400
