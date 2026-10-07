import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .contracts import Event
from .store import Refused, Store


def app(store, tokens, web_root=None):
    api = FastAPI(title="Customer Signal & Activation", version="2.0.0")
    web_root = Path(web_root or Path(__file__).resolve().parents[2] / "web")

    @api.get("/health")
    def health():
        return {"ready": True}

    async def admit(request, actor):
        body = await request.body()
        if len(body) > 8192:
            raise HTTPException(413, "event_too_large")
        try:
            return store.ingest(Event.model_validate_json(body).model_dump(), actor)
        except (ValidationError, Refused) as exc:
            raise HTTPException(422, str(exc)) from exc

    @api.post("/collect")
    async def collect(request: Request):
        # Public browser data has no credential granting enterprise authority.
        return await admit(request, "browser")

    @api.post("/events")
    async def events(request: Request, authorization: str = Header(default="")):
        actor = tokens.get(authorization.removeprefix("Bearer "))
        if not actor:
            raise HTTPException(401)
        return await admit(request, actor)

    @api.get("/status")
    def status(authorization: str = Header(default="")):
        if tokens.get(authorization.removeprefix("Bearer ")) != "operator":
            raise HTTPException(401)
        return store.status()

    @api.get("/")
    def index():
        return FileResponse(web_root / "index.html")

    @api.get("/instrumentation.js")
    def javascript():
        return FileResponse(web_root / "instrumentation.js", media_type="text/javascript")

    return api


def configured():
    import json

    return app(Store(os.environ["SIGNALS_DB"]), json.loads(os.environ.get("SIGNALS_TOKENS", "{}")))
