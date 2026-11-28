"""One request, or a WebSocket, to another server and its answer back: a plugin's, on its unix
socket, or a run's published port."""
import asyncio
import os

import httpx
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import WebSocketException

import server as core

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}


def _target(scope):
    path = scope.get("raw_path") or scope["path"].encode()
    return (path + (b"?" + scope["query_string"] if scope.get("query_string") else b"")).decode("latin-1")


async def relay(scope, receive, send, open_socket, uds=None, drop_cookies=False):
    """One request (or a WebSocket) to another server, and its answer back: a plugin's on its unix
    socket (`uds`, reached as connect() reaches it, never through a link planted there), or a run's
    published port. Its headers go as they came, Host too, but for those of this hop alone."""
    headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in scope["headers"]
               if k.decode("latin-1").lower() not in HOP]
    if drop_cookies:  # our sign-in's: the demo would sign in as you with them
        kept = "; ".join(c.strip() for k, v in headers if k.lower() == "cookie" for c in v.split(";")
                         if c.strip() and not c.strip().startswith(core.AUTH_COOKIE))
        headers = [(k, v) for k, v in headers if k.lower() != "cookie"] + ([("Cookie", kept)] if kept else [])
    host = next((v for k, v in headers if k.lower() == "host"), "upstream")
    if scope["type"] == "websocket":
        return await _relay_ws(scope, receive, send, open_socket, host, headers)
    async def upload():  # passed on as it comes, never held whole
        while True:
            m = await receive()
            if m["type"] == "http.disconnect":
                return
            if m.get("body"):
                yield m["body"]
            if not m.get("more_body"):
                return
    # A request without a body (a GET) goes without one, not as an empty chunked stream; one sent
    # chunked goes on chunked (httpx's), one with a Content-Length with that.
    sent = {k.decode("latin-1").lower() for k, _ in scope["headers"]}
    body = upload() if sent & {"content-length", "transfer-encoding"} else b""
    try:
        if uds:  # a descriptor of the socket file itself, so the path is never followed again
            fd = await run_in_threadpool(core._socket_fd, uds)
            transport = httpx.AsyncHTTPTransport(uds=f"/proc/self/fd/{fd}")
            base = "http://plugin"
        else:
            fd, (h, p) = None, await run_in_threadpool(open_socket)
            transport, base = httpx.AsyncHTTPTransport(), f"http://{h}:{p}"
    except (ValueError, OSError) as e:
        return await JSONResponse({"error": str(e)}, 502)(scope, receive, send)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=None) as client:
            try:
                resp = await client.send(client.build_request(scope["method"], base + _target(scope), headers=headers,
                                                              content=body), stream=True)
            except httpx.HTTPError as e:
                return await JSONResponse({"error": str(e) or type(e).__name__}, 502)(scope, receive, send)
            try:
                await send({"type": "http.response.start", "status": resp.status_code,
                            "headers": [(k, v) for k, v in resp.headers.raw if k.decode("latin-1").lower() not in HOP]})
                async for chunk in resp.aiter_raw():
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
                await send({"type": "http.response.body", "body": b""})
            finally:
                await resp.aclose()
    finally:
        if fd is not None:
            os.close(fd)


async def _relay_ws(scope, receive, send, open_socket, host, headers):
    await receive()  # websocket.connect
    # The browser's Host in the URI, its other headers added: the server sees what the browser sent.
    extra = [(k, v) for k, v in headers if k.lower() != "host" and not k.lower().startswith("sec-websocket")]
    try:
        sock = await run_in_threadpool(open_socket, True)
        up = await ws_connect(f"ws://{host}{_target(scope)}", sock=sock, additional_headers=extra,
                              subprotocols=scope.get("subprotocols") or None, max_size=None, ping_interval=None,
                              user_agent_header=None, compression=None)
    except (ValueError, OSError, WebSocketException):
        return await send({"type": "websocket.close", "code": 1011})  # refused: the browser is told 403
    async with up:
        await send({"type": "websocket.accept", "subprotocol": up.subprotocol})

        async def down():
            try:
                async for m in up:
                    await send({"type": "websocket.send", **({"bytes": m} if isinstance(m, bytes) else {"text": m})})
            except WebSocketException:
                pass
            await send({"type": "websocket.close", "code": up.close_code or 1000})

        async def upward():
            while (m := await receive())["type"] != "websocket.disconnect":
                await up.send(m["bytes"] if m.get("bytes") is not None else m["text"])
            await up.close()

        tasks = [asyncio.ensure_future(down()), asyncio.ensure_future(upward())]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
