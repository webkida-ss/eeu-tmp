"""Select the administration or learner browser-origin policy by route namespace."""

from urllib.parse import urlsplit

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send


class RouteCorsMiddleware:
    def __init__(self, app: ASGIApp, *, learner_origins: list[str], admin_origin: str) -> None:
        try:
            parsed = urlsplit(admin_origin)
            valid = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname is not None
                and parsed.username is None
                and parsed.password is None
                and "*" not in admin_origin
                and admin_origin == f"{parsed.scheme}://{parsed.netloc}"
                and (parsed.port is None or 1 <= parsed.port <= 65535)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("ADMIN_ALLOWED_ORIGIN must be one exact HTTP origin.")
        self.app = app
        self.learner = CORSMiddleware(
            app,
            allow_origins=learner_origins,
            allow_origin_regex=r"^chrome-extension://[a-z]+$",
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )
        self.admin = CORSMiddleware(
            app,
            allow_origins=[admin_origin],
            allow_credentials=False,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
            expose_headers=["X-Correlation-ID"],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        policy = self.admin if path == "/admin" or path.startswith("/admin/") else self.learner
        await policy(scope, receive, send)
