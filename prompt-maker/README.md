# NoWork

Talk to the AI by voice only, in your language, about what you want to build. It asks questions out loud and, when you confirm, gives you a Word document (.docx) with 6 detailed, ready-to-paste prompts: design, architecture, UI/UX, frontend, backend, database. Built on Google's Gemini Live API (`gemini-live-api-examples`, ephemeral-token example).

## Structure

```
prompt-maker/
├── backend/                 Python (aiohttp)
│   ├── server.py            token endpoint, /api/rag, /api/doc (all rate limited), serves ../frontend
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
