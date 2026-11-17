"""Measures the browser's per-frame cost for REQ-03: the frontend's own `detect()` without and with eye centres.

    venv/bin/python -m benchmark.browser_timing
    # open http://localhost:8766 in the browser and machine the client will use, enable the camera, start

The page needs a real face in view, because the cost depends on it. It runs the frontend's `detect()` at the
frontend's frame rate cap, alternating frames without and with eye centres so drift hits both equally, and posts
a summary of timings (numbers only) to this server, which prints it as one JSON line. Nothing else is sent,
stored or logged: no landmarks, no images, no frames. Listens on 127.0.0.1 only. Dev tool, not part of the service.
"""

import argparse
import json
import math
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from benchmark.record import serve_frontend

PAGE_DIRECTORY = Path(__file__).parent / "timing_page"
GROUPS = ("without_centres", "with_centres")
FIELDS = ("n", "median_ms", "p95_ms", "mean_ms")
MAX_BODY_BYTES = 16 * 1024


def validate_summary(data):
    """The summary the page posts, checked to be only numbers and short strings. Raises ValueError otherwise."""

    if not isinstance(data, dict):
        raise ValueError("summary must be an object")

    for group in GROUPS:
        entry = data.get(group)
        if not isinstance(entry, dict) or set(entry) != set(FIELDS):
            raise ValueError(f"{group} needs exactly {FIELDS}")
        if not all(isinstance(entry[f], (int, float)) and not isinstance(entry[f], bool) and math.isfinite(entry[f])
                   for f in FIELDS):
            raise ValueError(f"{group} must be finite numbers")

    for name in ("no_face", "frames", "achieved_fps"):
        if not isinstance(data.get(name), (int, float)) or isinstance(data.get(name), bool) \
                or not math.isfinite(data[name]):
            raise ValueError(f"{name} must be a finite number")

    for name in ("user_agent", "cores"):
        if name in data and not isinstance(data[name], (str, int)):
            raise ValueError(f"{name} must be a string or number")

    return {**{k: data[k] for k in (*GROUPS, "no_face", "frames", "achieved_fps")},
            "user_agent": str(data.get("user_agent", ""))[:200], "cores": data.get("cores")}


def create_app(frontend, report=print):
    """The timing server. `report` receives each validated summary (it prints a JSON line by default)."""

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/")
    def page():
        return FileResponse(PAGE_DIRECTORY / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/timing.js")
    def script():
        return FileResponse(PAGE_DIRECTORY / "timing.js", headers={"Cache-Control": "no-store"})

    serve_frontend(app, frontend)

    @app.post("/result")
    async def result(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415)
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413)
        try:
            summary = validate_summary(json.loads(body))
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        report(json.dumps({"timing": summary}))
        return {"ok": True}

    return app


def main(argv=None):

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frontend", default=str(Path(__file__).resolve().parents[2] / "ocurate-fe"))
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)

    if not Path(args.frontend, "js", "camera", "face-tracker.js").is_file():
        raise SystemExit(f"--frontend {args.frontend!r} is not the ocurate-fe folder")

    print(f"Open http://localhost:{args.port} in the browser the client will use (a face in view).", flush=True)
    uvicorn.run(create_app(args.frontend, report=lambda line: print(line, flush=True)), host="127.0.0.1",
                port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
