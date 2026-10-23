"""MCP server (Streamable HTTP) exposing Tripwire to Alexa+ or any MCP host."""

from __future__ import annotations

import hmac
import logging
import os
from typing import Annotated, Any, Literal

import anyio
import anyio.to_thread
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse, Response

from .service import Tripwire
from .simulator import Simulator
from .store import make_store

log = logging.getLogger("tripwire")
BUSY = "I'm having trouble reaching my memory right now. Please try again in a moment."

INSTRUCTIONS = """\
Tripwire remembers household decisions together with the conditions ('tripwires') that would change them.

- When the user states a decision, call record_decision with their words verbatim; do not paraphrase numbers.
- When the user mentions ANY new fact that might matter ('the provider raised the price to 55', 'we had three
  outages'), call report_fact with their words, even if they didn't ask. This is how tripwires fire.
- 'Why did we choose X?' -> why_did_we. 'What should I look at?' -> whats_on_watch.
- After a tripwire fires, ask whether to keep, change, or close the decision, then call resolve_decision.
Every result has a short `spoken` field that is safe to read aloud verbatim.
"""

TOPIC = Annotated[str, Field(description="Spoken topic, e.g. 'internet plan' or 'the couch'")]


def default_service() -> Tripwire:
    return Tripwire(make_store(), household=os.environ.get("TRIPWIRE_HOUSEHOLD", "home"))


def call(fn, *args) -> dict[str, Any]:
    """Run a service method; any failure (DynamoDB down, timeout, lost race...) becomes a speakable
    sentence for the user and a logged stack trace for the operator. Internals are never leaked to the caller."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        log.exception("tool call failed: %s", getattr(fn, "__name__", fn))
        return {"ok": False, "error": "temporarily_unavailable", "spoken": BUSY}


def build_server(service: Tripwire | None = None) -> MCPServer:
    svc = service or default_service()
    mcp = MCPServer("Tripwire", instructions=INSTRUCTIONS, version="0.1.0")
    ro = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
    rw = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    @mcp.tool(annotations=rw)
    def record_decision(what_was_said: Annotated[str, Field(description="The user's own words describing the decision, why, and what would change their mind", max_length=1500)]) -> dict[str, Any]:
        """Remember a decision and the tripwires (conditions that would make the user reconsider). Pass the user's words as spoken."""
        return call(svc.record_decision, what_was_said)

    @mcp.tool(annotations=rw)
    def report_fact(statement: Annotated[str, Field(description="A new fact the user mentioned, as spoken", max_length=500)]) -> dict[str, Any]:
        """Check a new fact against every armed tripwire. Numeric thresholds are compared server-side. Call this whenever the user mentions news that could affect a past decision."""
        return call(svc.report_fact, statement)

    @mcp.tool(annotations=ro)
    def whats_on_watch() -> dict[str, Any]:
        """List live decisions, highlighting any that tripped or whose check-in date has arrived."""
        return call(svc.whats_on_watch)

    @mcp.tool(annotations=ro)
    def why_did_we(topic: TOPIC) -> dict[str, Any]:
        """Recall why a decision was made, what was considered, its tripwires and what has happened since."""
        return call(svc.why_did_we, topic)

    @mcp.tool(annotations=rw)
    def confirm_tripwire(topic: TOPIC, number: Annotated[int, Field(ge=1, le=20)], tripped: bool) -> dict[str, Any]:
        """Answer 'did that trip it?' for a possible match (qualitative tripwires need a human yes/no)."""
        return call(svc.confirm_tripwire, topic, number, tripped)

    @mcp.tool(annotations=rw)
    def resolve_decision(topic: TOPIC, outcome: Literal["keep", "change", "close"], note: str | None = None,
                         new_limit: float | None = None, tripwire_number: Annotated[int | None, Field(ge=1, le=20)] = None) -> dict[str, Any]:
        """Finish a revisit: 'keep' (optionally moving a numeric limit to new_limit), 'change', or 'close'. If several limits tripped, pass tripwire_number."""
        return call(svc.resolve_decision, topic, outcome, note, new_limit, tripwire_number)

    @mcp.tool(annotations=rw)
    def add_tripwire(topic: TOPIC, condition: Annotated[str, Field(description="e.g. 'the price goes above 60'", max_length=300)]) -> dict[str, Any]:
        """Add another condition that would make the user reconsider an existing decision."""
        return call(svc.add_tripwire, topic, condition)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
    def remove_tripwire(topic: TOPIC, number: Annotated[int, Field(ge=1, le=20)]) -> dict[str, Any]:
        """Stop watching one tripwire (numbered as read back when the decision was recorded)."""
        return call(svc.remove_tripwire, topic, number)

    return mcp
class BearerAuth:
    """Minimal ASGI guard. If TRIPWIRE_TOKEN is set, every request except /healthz needs it."""

    def __init__(self, app, token: str):
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] not in ("/healthz", "/readyz"):
            auth = dict(scope["headers"]).get(b"authorization", b"")
            if not (auth.lower().startswith(b"bearer ") and hmac.compare_digest(auth[7:], self.token)):
                resp = JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
                return await resp(scope, receive, send)
        return await self.app(scope, receive, send)


def _add_sim_routes(app, svc: Tripwire, sim: Simulator) -> None:
    """Simulated Alexa+ web UI (opt-in via TRIPWIRE_SIM=1; meant for local demos, not public deployments)."""
    from starlette.responses import HTMLResponse

    from .simhtml import SIM_HTML

    async def page(_r) -> Response:
        return HTMLResponse(SIM_HTML)

    async def body(request):
        # Require JSON: browsers can't send it cross-site without a CORS preflight, which blocks drive-by requests.
        if "application/json" not in request.headers.get("content-type", ""):
            return None
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return None
        return data if isinstance(data, dict) else None

    async def say(request) -> Response:
        data = await body(request)
        text = data.get("utterance") if data else None
        if not isinstance(text, str) or not text.strip():
            return JSONResponse({"ok": False, "spoken": "Say something and I'll pass it to Tripwire."}, status_code=400 if data is not None else 415)
        out = await anyio.to_thread.run_sync(lambda: call(sim.say, svc, text[:1500]))
        out.setdefault("tool", None)
        return JSONResponse(out)

    async def advance(request) -> Response:
        data = await body(request)
        days = data.get("days") if data else None
        if not isinstance(days, int) or isinstance(days, bool):
            return JSONResponse({"ok": False}, status_code=400 if data is not None else 415)
        return JSONResponse({"ok": True, "skipped_days": sim.advance(days)})

    async def state(_r) -> Response:
        return JSONResponse(await anyio.to_thread.run_sync(lambda: call(sim.state, svc)))

    app.add_route("/sim", page)
    app.add_route("/sim/say", say, methods=["POST"])
    app.add_route("/sim/advance", advance, methods=["POST"])
    app.add_route("/sim/state", state)


def create_app(service: Tripwire | None = None, simulator: Simulator | None = None):
    sim = simulator or (Simulator() if os.environ.get("TRIPWIRE_SIM") == "1" else None)
    if service is None:
        svc = default_service()
        if sim is not None:  # simulated clock so the UI can "skip days"
            svc.today = sim.today
            svc._today = sim.today
    else:
        svc = service
    mcp = build_server(svc)
    hosts = [h.strip() for h in os.environ.get("TRIPWIRE_ALLOWED_HOSTS", "").split(",") if h.strip()]
    # Keep loopback allowed so local health checks and clients still work when a public hostname is configured.
    security = (TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                          allowed_hosts=hosts + ["127.0.0.1:*", "localhost:*", "[::1]:*"]) if hosts else None)
    app = mcp.streamable_http_app(stateless_http=True, transport_security=security,
                                  host=os.environ.get("TRIPWIRE_HOST", "127.0.0.1"))

    async def healthz(_request) -> Response:
        return JSONResponse({"status": "ok"})

    async def readyz(_request) -> Response:
        """Readiness: can we actually reach the database? (/healthz only says the process is up.)"""
        try:
            await anyio.to_thread.run_sync(svc.s.ping)
        except Exception:  # noqa: BLE001
            log.exception("readiness check failed")
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    if sim is not None:
        _add_sim_routes(app, svc, sim)

    app.add_route("/healthz", healthz)
    app.add_route("/readyz", readyz)
    token = os.environ.get("TRIPWIRE_TOKEN")
    return BearerAuth(app, token) if token else app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=os.environ.get("TRIPWIRE_LOG", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host = os.environ.get("TRIPWIRE_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", os.environ.get("TRIPWIRE_PORT", "8000")))
    if host not in ("127.0.0.1", "localhost", "::1"):
        if not os.environ.get("TRIPWIRE_ALLOWED_HOSTS"):
            log.warning("Listening on %s but TRIPWIRE_ALLOWED_HOSTS is unset: requests addressed to your public domain "
                        "will be rejected with HTTP 421. Set it to your hostname.", host)
        if not os.environ.get("TRIPWIRE_TOKEN"):
            log.warning("TRIPWIRE_TOKEN is unset: anyone who can reach this endpoint can read and change your decisions.")
    if os.environ.get("TRIPWIRE_AI", "auto").lower() != "offline" and not os.environ.get("BEDROCK_MODEL_ID"):
        log.warning("BEDROCK_MODEL_ID is unset: Bedrock is unavailable, so %s.",
                    "every request will fail" if os.environ.get("TRIPWIRE_AI", "auto").lower() == "bedrock" else "the offline fallback parser will be used")
    uvicorn.run(create_app(), host=host, port=port, timeout_keep_alive=5)


if __name__ == "__main__":
    main()
