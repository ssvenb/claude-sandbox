"""The API as one FastAPI app: its routers (api/*.py), and how an error a route raises becomes its answer."""
from api import agents, auth, chat, pages, projects, sessions, system
from api.common import Route
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import server as core

# One schema per shape, not an input and an output one: an optional field is optional both ways.
app = FastAPI(title="claude-sandbox", description="The sandboxes' web UI: its projects, sessions and their chats.", docs_url="/api/docs",
              openapi_url="/api/openapi.json", redoc_url=None, separate_input_output_schemas=False)

app.router.route_class = Route
for part in (pages, system, projects, sessions, chat, auth, agents):
    app.include_router(part.router)


def _error(status):
    return lambda request, e: JSONResponse({"error": str(e)}, status)


# An error a route raises is its answer: NotFound 404, Conflict 409, any other ValueError (or a
# KeyError, a field missing) 400, an OSError 500; and FastAPI's own (405, a body that is not what
# the route takes) as {"error": …} too.
for kind, status in ((core.NotFound, 404), (core.Conflict, 409), (ValueError, 400), (KeyError, 400), (OSError, 500)):
    app.add_exception_handler(kind, _error(status))


@app.exception_handler(StarletteHTTPException)
def _http_error(request, e):
    return JSONResponse({"error": str(e.detail)}, e.status_code, headers=getattr(e, "headers", None))


@app.exception_handler(RequestValidationError)
def _invalid(request, e):
    return JSONResponse({"error": "; ".join(f"{'.'.join(map(str, x['loc'][1:])) or 'body'}: {x['msg']}" for x in e.errors())}, 400)
