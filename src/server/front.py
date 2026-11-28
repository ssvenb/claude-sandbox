"""What comes before the API: the guard, a plugin's server under /plugins/<name>/, a run's demo
subdomain, and what a page loads."""
import re
import socket
import sys

from fastapi.responses import FileResponse, JSONResponse
from proxy import relay
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers

import server as core


def guard(c, headers):
    """This server drives agents on your machine. Any web page you visit can aim requests at
    localhost, so only our own page gets through: the Host check stops DNS rebinding, the Origin
    check stops cross-site requests. Any port: a proxy (a sandbox's published port) may put this
    server on another, and the name is what rebinding forges."""
    host = headers.get("host", "")
    origin = headers.get("origin")
    # https too: behind a TLS proxy (serve-oauth.sh) the page is https://<Host>, the same site.
    if allowed(c.hosts, host.rsplit(":", 1)[0]) and origin in (None, f"http://{host}", f"https://{host}"):
        core.page_origin = origin or f"{headers.get('x-forwarded-proto', 'http')}://{host}"
        return True
    return False


class Front:
    """What comes before the API, as ASGI: a demo subdomain relayed (behind whatever sign-in is in
    front of us, serve-oauth.sh, not our guard: the page is the sandbox's, on an origin of its own),
    then our guard, a plugin's server under /plugins/<name>/, and what a page loads."""

    def __init__(self, app, c):
        self.app, self.c = app, c

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        scope["sandbox"] = self.c
        h = Headers(scope=scope)
        # Only the server serve-oauth.sh starts relays subdomains: any other (this server as a run's
        # demo, behind that one's relay, which passes the Host header through) serves them itself.
        if self.c.subdomains and (sub := core.PORT_HOST.fullmatch(h.get("host", "").rsplit(":", 1)[0])) and sub[3] in self.c.hosts:
            def open_port(ws=False, run_id=sub[1], port=int(sub[2])):
                where = core.published(run_id, port)
                return socket.create_connection(where, timeout=10) if ws else where
            return await relay(scope, receive, send, open_port, drop_cookies=True)
        if not guard(self.c, h):
            print(f"forbidden: Host={h.get('host')!r} Origin={h.get('origin')!r} {scope.get('method', 'WS')} {scope['path']}",
                  file=sys.stderr, flush=True)
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse({"error": "forbidden"}, 403)(scope, receive, send)
        if m := re.match(r"/plugins/([\w-]+)(?:/|$)", scope["path"]):  # started on first use
            try:
                path = await run_in_threadpool(core.plugin_server, m[1])
            except (ValueError, OSError) as e:
                if scope["type"] == "websocket":
                    return await send({"type": "websocket.close", "code": 1011})
                return await JSONResponse({"error": str(e)}, 502)(scope, receive, send)
            return await relay(scope, receive, send, lambda ws=False: core.connect(path), uds=path)
        if scope["type"] == "http" and scope["method"] in ("GET", "HEAD") and (asset := core.static(scope["path"])):
            return await FileResponse(asset, media_type=core.STATIC[asset.suffix])(scope, receive, send)
        await self.app(scope, receive, send)


def allowed(hosts, name):
    """A name of ours: listed, under a listed `.domain`, or a demo subdomain <RUN_ID>-<port>.<a listed
    name> (this server as a run's demo, behind another's relay, which passes the Host header through:
    whoever owns the listed name owns that one too, so it stops DNS rebinding as well)."""
    if (sub := core.PORT_HOST.fullmatch(name)) and sub[3] in hosts:
        return True
    return name in hosts or any(h.startswith(".") and name.endswith(h) for h in hosts)
