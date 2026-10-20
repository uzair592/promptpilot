"""Acceptance-only transport: exercise real provider adapters against the local fake.

This launcher is used only by Playwright. Production imports the application
directly and never installs this transport or redirects provider traffic.
"""

import os
from types import SimpleNamespace

import httpx
import uvicorn

from promptpilot_backend import provider_gateway

OriginalClient = httpx.Client


def forward(request: httpx.Request) -> httpx.Response:
    path = request.url.raw_path.decode()
    if path.startswith("/api/v1/"):
        path = path.removeprefix("/api")
    with OriginalClient(timeout=5, follow_redirects=False, trust_env=False) as client:
        response = client.request(
            request.method,
            f"http://127.0.0.1:8132{path}",
            content=request.content,
            headers={name: value for name, value in request.headers.items() if name != "host"},
        )
    return httpx.Response(response.status_code, headers=response.headers, content=response.content)


class AcceptanceClient(OriginalClient):
    def __init__(self, **kwargs):
        kwargs["trust_env"] = False
        super().__init__(transport=httpx.MockTransport(forward), **kwargs)


provider_gateway.httpx = SimpleNamespace(
    Client=AcceptanceClient,
    TimeoutException=httpx.TimeoutException,
    TransportError=httpx.TransportError,
)

if __name__ == "__main__":
    uvicorn.run("promptpilot_backend.main:app", host="127.0.0.1", port=int(os.getenv("ACCEPTANCE_BACKEND_PORT", "8130")))
