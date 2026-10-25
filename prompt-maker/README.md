# NoWork

Talk to the AI by voice only, in your language, about what you want to build. It asks questions out loud and, when you confirm, sends 6 detailed prompts (design, architecture, UI/UX, frontend, backend, database) to the **Prompt** page as a roadmap: download each step as a Word document and watch the traveler drive to the next stop. Finished roadmaps are kept in History. If you also asked for code, the **Code** page has a ready HTML/CSS/JavaScript project with an editor, live preview and ZIP download.

Three pages: **Agents** (voice), **Prompt** (roadmap and history), **Code** (starter project). Built on Google's Gemini Live API (`gemini-live-api-examples`, ephemeral-token example).

## Structure

```
prompt-maker/
├── backend/                 Python (aiohttp)
│   ├── server.py            token endpoint, /api/rag, /api/doc (all rate limited), serves ../frontend
│   ├── api.py               history (/api/prompt-sets), /api/code, /api/zip, /api/health, live sites (/api/preview, /p/<token>/)
│   ├── db.py                tiny Supabase REST client (service role key, server side only)
│   ├── codegen.py           writes the HTML/CSS/JS project with a Gemini text model
│   ├── supabase/schema.sql  tables: run once in the Supabase SQL Editor
│   ├── docgen.py            builds the .docx from the six prompts (python-docx)
│   ├── rag.py               knowledge retrieval
│   ├── knowledge/*.md       trusted facts the AI must answer from
│   ├── tests/               pytest
│   ├── .env                 GEMINI_API_KEY (never commit)
│   └── requirements*.txt
├── frontend/                static site (vanilla JS)
│   ├── index.html, script.js (system prompt + wiring), tools.js
│   └── geminilive.js, mediaUtils.js, audio-processors/   (unmodified from the example)
└── tests/frontend/          node tests for tools.js
```

## Run

```bash
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt   # Windows
copy .env.example .env      # then put your key in GEMINI_API_KEY=
.venv\Scripts\python server.py
```

Open http://localhost:8000 in Chrome/Edge and tap the orb (mic needs localhost or https).

## Tests

```bash
cd backend && .venv\Scripts\python -m pytest tests -q
cd .. && node tests/frontend/tools.test.js
```

## Accuracy (RAG)

The model must call `lookup_knowledge` before stating facts. It searches `backend/knowledge/*.md` and answers only from the results, or says it is unsure. To make it smarter, add `## Section` blocks to those files.

## Database setup (Supabase)

1. Put these in `backend/.env` (never in the frontend; the service role key bypasses row level security):
   `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
2. Open the Supabase dashboard, SQL Editor, paste `backend/supabase/schema.sql` and run it once.
3. `GET /api/health` returns `{"db": true}` when it works. Until then the Prompt page keeps history in this browser only.

Row level security is on with no policies, so the public (anon) key can read nothing; only the backend reads and writes. History belongs to a random id stored in the browser, not to a login (add Supabase Auth for real accounts).

`CODE_MODEL` (env, default `gemini-3.5-flash`) picks the model that writes the Code page project. Model availability changes: if code generation fails with 404, set a model your key can use.

## Live site for generated code

The Code page publishes the project as a real site at `http://127.0.0.1:<port>/p/<token>/` (kept in server memory, newest 50, lost on restart; press Run on the Code page to recreate it). Open it in a new tab, or copy the link. It is served from the *other* loopback name (`localhost` <-> `127.0.0.1`), so it is a different origin from the app and cannot read the app's storage. On any other host the page is served with a CSP sandbox instead.
