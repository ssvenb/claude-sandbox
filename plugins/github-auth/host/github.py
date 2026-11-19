#!/usr/bin/env python3
"""The GitHub API calls web.sh makes, as the token in $GH_TOKEN, on the repo of $REPO_URL:

    github.py list               {"open": [...], "merged": [...], "issues": [...]}, each entry in
                                 the shape `gh <pr|issue> list --json` gives (statusCheckRollup a list)
    github.py close <n> <text>   comment <text> on pull request <n>, then close it

One GraphQL query a list, so the page polling every minute costs one request. A failure is one
line on stderr and exit status 1.
"""
import json
import os
import re
import sys

import requests

GH_HOST = os.environ.get("GH_HOST") or "github.com"
# GITHUB_API_URL as in GitHub Actions; GitHub Enterprise Server's REST API is under /api/v3, its GraphQL /api/graphql.
API = os.environ.get("GITHUB_API_URL") or ("https://api.github.com" if GH_HOST == "github.com" else f"https://{GH_HOST}/api/v3")
GRAPHQL = API.removesuffix("/v3") + "/graphql"

LIST = """query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) {
  open: pullRequests(states: OPEN, first: 50, orderBy: {field: CREATED_AT, direction: DESC}) { nodes {
    number title url headRefName headRefOid isDraft
    commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) { nodes {
      __typename ... on CheckRun { status conclusion } ... on StatusContext { state } } } } } } } } }
  merged: pullRequests(states: MERGED, first: 50, orderBy: {field: CREATED_AT, direction: DESC}) { nodes {
    number title url headRefName } }
  issues(states: OPEN, first: 50, orderBy: {field: CREATED_AT, direction: DESC}) { nodes { number title url } }
} }"""


def call(method: str, url: str, **kw):
    try:
        r = requests.request(method, url, timeout=20, **kw, headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"})
    except requests.RequestException as e:
        sys.exit(f"{method} {url}: {e}")
    body = r.json() if r.content else {}
    if not r.ok or body.get("errors"):
        sys.exit(f"{method} {url}: HTTP {r.status_code} {body.get('message') or body.get('errors')}")
    return body


def main(argv):
    repo = re.search(r"[/:]([^/:]+)/([^/]+?)(?:\.git)?/?$", os.environ.get("REPO_URL", ""))
    if not repo:
        sys.exit(f"not a GitHub repository URL: {os.environ.get('REPO_URL', '')!r}")
    owner, name = repo[1], repo[2]
    if argv[:1] == ["list"]:
        data = call("POST", GRAPHQL, json={"query": LIST, "variables": {"owner": owner, "name": name}})["data"]["repository"]
        prs = data["open"]["nodes"]
        for pr in prs:
            commits = pr.pop("commits")["nodes"]
            rollup = commits and commits[0]["commit"]["statusCheckRollup"]
            pr["statusCheckRollup"] = rollup["contexts"]["nodes"] if rollup else []
        print(json.dumps({"open": prs, "merged": data["merged"]["nodes"], "issues": data["issues"]["nodes"]}))
    elif argv[:1] == ["close"] and len(argv) == 3 and argv[1].isdigit():
        call("POST", f"{API}/repos/{owner}/{name}/issues/{argv[1]}/comments", json={"body": argv[2]})
        call("PATCH", f"{API}/repos/{owner}/{name}/pulls/{argv[1]}", json={"state": "closed"})
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
