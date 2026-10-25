"""
Vercel entrypoint. Vercel's Python runtime looks for a top-level `app` (ASGI or WSGI) in app.py / index.py / server.py ... at the
repository root; the real code lives in prompt-maker/backend, so this file only puts it on the path and exposes the app.

Locally nothing changes: `python server.py` inside prompt-maker/backend still runs the same app with aiohttp's own server.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt-maker", "backend"))

import aio_asgi  # noqa: E402
import server  # noqa: E402

# The aiohttp handlers, served over ASGI. Static files (../frontend) are served by the same app.
app = aio_asgi.wrap(server.make_app())
