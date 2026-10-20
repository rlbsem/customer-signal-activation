"""Local authenticated workbench; no model or enterprise token enters page source."""

import json
import secrets
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .contracts import digest
from .salesforce_contract import DeliveryError
from .store import Refused


def app(workbench, operator_token, destination_url, destination_token, root=None, dispatcher=None,
        destination_label="Salesforce synthetic review record"):
    root = Path(root or Path(__file__).resolve().parents[2])
    api = FastAPI(title="Customer Signal — Seller Workbench")
    sessions = set()

    def same_origin(request):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "origin_refused")

    def authenticated(request):
        supplied = request.headers.get("authorization", "")
        cookie = request.cookies.get("seller_session", "")
        if not (secrets.compare_digest(supplied, "Bearer " + operator_token) or cookie in sessions):
            raise HTTPException(401, "operator_login_required")
        if request.method != "GET":
            same_origin(request)

    @api.exception_handler(Refused)
    async def refused(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @api.exception_handler(DeliveryError)
    async def delivery_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=503 if exc.retryable else 409)

    @api.exception_handler(ValidationError)
    async def validation(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "invalid_request_contract"}, status_code=422)

    async def body(request):
        raw = await request.body()
        if len(raw) > 32000:
            raise HTTPException(413, "request_too_large")
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise HTTPException(422, "json_object_required")
            return value
        except ValueError as exc:
            raise HTTPException(422, "invalid_json") from exc

    @api.get("/health")
    def health():
        return {"ready": True}

    @api.post("/api/login")
    async def login(request: Request, response: Response):
        same_origin(request)
        supplied = (await body(request)).get("token", "")
        if not isinstance(supplied, str) or not secrets.compare_digest(supplied, operator_token):
            raise HTTPException(401, "invalid_operator_token")
        session = secrets.token_urlsafe(32)
        sessions.add(session)
        response.set_cookie("seller_session", session, httponly=True, samesite="strict", max_age=3600)
        return {"authenticated": True}

    @api.post("/api/logout")
    def logout(request: Request, response: Response):
        authenticated(request)
        sessions.discard(request.cookies.get("seller_session", ""))
        response.delete_cookie("seller_session")
        return {"authenticated": False}

    @api.get("/api/overview")
    def overview(request: Request):
        authenticated(request)
        value = workbench.overview()
        if dispatcher:
            value["destination_label"] = destination_label
            for action in value["actions"]:
                status = dispatcher.status(action["id"])
                if status:
                    action["delivery_state"] = status["state"]
        value["run_hashes"] = {r["id"]: digest(r) for r in value["runs"]}
        return value

    @api.get("/api/context/{brand}/{account}")
    def context(brand: str, account: str, request: Request):
        authenticated(request)
        return workbench.context(brand, account)

    @api.post("/api/generate/{brand}/{account}")
    def generate(brand: str, account: str, request: Request):
        authenticated(request)
        run = workbench.generate(brand, account)
        return {"run": run, "review_hash": digest(dict(run, cached=False))}

    @api.post("/api/documents")
    async def document(request: Request):
        authenticated(request)
        return workbench.document(await body(request))

    @api.post("/api/approve/{run_id}")
    async def approve(run_id: str, request: Request):
        authenticated(request)
        value = await body(request)
        return workbench.approve(run_id, value.get("proposal"), value.get("review_hash"),
                                 authority_ids=value.get("authority_ids", []))

    @api.post("/api/prepare/{run_id}")
    async def prepare(run_id: str, request: Request):
        authenticated(request)
        value = await body(request)
        return workbench.prepare(run_id, value.get("review_hash"), value.get("proposal"),
                                 value.get("authority_ids", []))

    @api.post("/api/reject/{run_id}")
    def reject(run_id: str, request: Request):
        authenticated(request)
        return workbench.reject(run_id)

    @api.post("/api/deliver/{key}")
    def deliver(key: str, request: Request):
        authenticated(request)
        if dispatcher:
            result = dispatcher.step(key)
            return json.loads(result["receipt"]) if result["state"] == "delivered" else {
                k: result[k] for k in ("state", "attempts", "detail", "next_at")}
        return workbench.deliver(key, destination_url, destination_token)

    @api.post("/api/reconcile/{key}")
    def reconcile(key: str, request: Request):
        authenticated(request)
        if not dispatcher:
            raise HTTPException(409, "salesforce_dispatcher_not_configured")
        result = dispatcher.reconcile_once(key)
        return json.loads(result["receipt"]) if result["state"] == "delivered" else result

    @api.get("/api/evaluation")
    def evaluation(request: Request):
        authenticated(request)
        path = root / "docs/evidence/seller/evaluation.json"
        return json.loads(path.read_text()) if path.exists() else {"status": "not_executed"}

    @api.get("/api/traces/{trace_id}")
    def trace(trace_id: str, request: Request):
        authenticated(request)
        folder = root / "docs/evidence/seller"
        result = json.loads((folder / "evaluation.json").read_text())
        if trace_id not in result["trace_hashes"]:
            raise HTTPException(404, "unknown_trace")
        value = json.loads((folder / "traces" / (trace_id + ".json")).read_text())
        if digest(value) != result["trace_hashes"][trace_id]:
            raise HTTPException(409, "recorded_trace_integrity_failure")
        return value

    @api.get("/api/recorded-application")
    def recorded_application(request: Request):
        authenticated(request)
        path = root / "docs/evidence/seller/application.json"
        return json.loads(path.read_text()) if path.exists() else {"status": "not_executed"}

    @api.get("/")
    def index():
        return FileResponse(root / "web/seller.html", headers={
            "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff"})

    @api.get("/seller.js")
    def javascript():
        return FileResponse(root / "web/seller.js", media_type="text/javascript")

    return api
