"""The pages: one React app (web/dist), its index.html for each."""
from api.common import Route
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse

import server as core

router = APIRouter(route_class=Route)


PAGE = {"response_class": HTMLResponse, "include_in_schema": False}


@router.get("/", **PAGE)
@router.get("/chat", **PAGE)
def page():
    """The pages are one React app: its index.html for each (it picks the page by its path)."""
    try:
        return HTMLResponse((core.DIST / "index.html").read_bytes())
    except OSError:
        return PlainTextResponse(core.UNBUILT, 503)
