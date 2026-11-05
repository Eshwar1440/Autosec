"""autosec: auto finance and vehicle-safety API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.nhtsa import NhtsaClient, UpstreamError, VinNotFound
from app.routes import financing, vehicle

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(
        timeout=5.0,
        transport=httpx.AsyncHTTPTransport(retries=2),
        headers={"User-Agent": "autosec (+https://github.com/Eshwar1440/autosec)"},
    ) as http:
        app.state.nhtsa = NhtsaClient(http)
        yield


# Interactive docs are off: their inline scripts would need a looser CSP.
# The spec is still served at /openapi.json.
app = FastAPI(title="autosec", version="1.2.0", docs_url=None, redoc_url=None, lifespan=lifespan)
app.include_router(financing.router)
app.include_router(vehicle.router)


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


@app.exception_handler(VinNotFound)
async def vin_not_found(request: Request, exc: VinNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "NHTSA has no make, model and year for this VIN"})


@app.exception_handler(UpstreamError)
async def upstream_error(request: Request, exc: UpstreamError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
