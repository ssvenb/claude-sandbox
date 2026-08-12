#!/usr/bin/env python3
"""Deep-merge Claude Code settings fragments into one policy file on stdout.

Objects merge key-by-key and lists concatenate, so several plugins can each contribute an
entry to the same hooks array. Later files win on scalar conflicts.
"""
import json
import sys


def merge(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for key, value in b.items():
            out[key] = merge(a[key], value) if key in a else value
        return out
    if isinstance(a, list) and isinstance(b, list):
        return a + b
    return b


result = {}
for path in sys.argv[1:]:
    with open(path) as fh:
        result = merge(result, json.load(fh))

json.dump(result, sys.stdout, indent=2)
print()
