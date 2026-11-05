"""autoloan-api: auto-loan quote service."""

from fastapi import FastAPI, Request, Response

from app.routes import financing

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

# Interactive docs are off: their inline scripts would need a looser CSP.
# The spec is still served at /openapi.json.
app = FastAPI(title="autoloan-api", version="1.1.0", docs_url=None, redoc_url=None)
app.include_router(financing.router)


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
