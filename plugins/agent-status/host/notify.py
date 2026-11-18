#!/usr/bin/env python3
"""web_on_status command (web.sh): on this machine, the web server runs it each time a session's
status changes as its page shows it, with the change as JSON on stdin (src/contract/host/plugins.sh).
It POSTs to the webhook when the session turns idle or needs you, but not for the boot that ends in
idle. The server only says idle when nothing runs in the background any more.

    notify.py <webhook-url> [generic|google-chat]

generic: {text, content, project, run_id, status, url}, which Slack, Mattermost and Discord show.
google-chat: {text} alone, as Google's API refuses fields it does not know.
"""
import json
import os
import sys
import urllib.request

SAY = {"idle": "idle, waiting for its next task", "question": "needs you"}


def message(event, kind="generic"):
    """The body to POST for a change of status, or None when there is nothing to say."""
    status = event.get("status")
    if status not in SAY or event.get("before") == "starting":
        return None
    name, run, page = os.path.basename(str(event.get("project") or "")) or "sandbox", event.get("run_id") or "", event.get("url") or ""
    text = f"{name} ({run}): {SAY[status]}" if run else f"{name}: {SAY[status]}"
    text += f"\n{page}" if page else ""  # a bare URL: Slack, Discord and Google Chat all link it
    if kind == "google-chat":
        return {"text": text}
    return {"text": text, "content": text, "project": name, "run_id": run, "status": status, "url": page}


def main():
    url, kind = sys.argv[1], (sys.argv[2:] or ["generic"])[0]
    body = message(json.load(sys.stdin), kind)
    if body:
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).close()


if __name__ == "__main__":
    main()
