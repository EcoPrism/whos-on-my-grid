"""Serve the built web app from the same process. Mounted only when the
dist directory exists, so local development (Vite proxying /api) is
unchanged. Hashed assets are immutable; index.html is never cached, and any
path that is not /api and not a file falls back to it for the SPA routes."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response


class ImmutableFiles(StaticFiles):
    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_web(app: FastAPI, dist: Path) -> bool:
    index = dist / "index.html"
    if not index.is_file():
        return False
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", ImmutableFiles(directory=str(assets)), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "not_found")
        # A real file at the dist root (favicon, logo). No traversal: the
        # resolved path must stay inside dist.
        if path:
            candidate = (dist / path).resolve()
            if candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate, headers={"Cache-Control": "public, max-age=3600"})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True
