"""Shared client for the free Groq models: picks models, waits when busy, retries broken replies.

Roles:
  writer  - writes posts and articles
  editor  - fact-checks them (a different model from the writer when the account offers one)
"""
import json
import os
import re
import sys
import time

import requests


def env(key, default=""):
    return os.environ.get(key) or default


def log(*a):
    print(*a, file=sys.stderr)


WAIT_BUDGET = int(env("LLM_WAIT_BUDGET", "420"))
_waited = 0
_ids = None
_picked = {}
SKIP = re.compile(r"whisper|guard|tts|embed|vision|distil|preview|safeguard|compound|orpheus|allam", re.I)


def base_url():
    return env("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")


def headers():
    return {"Authorization": "Bearer " + env("LLM_API_KEY")}


def model_ids():
    global _ids
    if _ids is None:
        r = requests.get(base_url() + "/models", headers=headers(), timeout=30)
        r.raise_for_status()
        _ids = [m["id"] for m in r.json()["data"] if not SKIP.search(m["id"])]
        log("models available:", ", ".join(_ids))
    return _ids


def _first(ids, prefs, avoid=None):
    for pat in prefs:
        for i in ids:
            if pat in i and i != avoid:
                return i
    return None


def pick(role):
    if role in _picked:
        return _picked[role]
    ids = model_ids()
    if role == "writer":
        m = (env("ARTICLE_MODEL") or env("LLM_MODEL")
             or _first(ids, ("llama-3.3-70b", "llama-3.1-70b", "70b", "gpt-oss-120b", "gpt-oss", "llama"))
             or ids[0])
    else:
        w = pick("writer")
        m = (env("EDITOR_MODEL")
             or _first(ids, ("gpt-oss-20b", "llama-3.3-70b", "llama-4", "qwen", "gpt-oss-120b", "llama"), avoid=w)
             or w)
    _picked[role] = m
    log(f"{role} model:", m)
    return m


def chat_json(msgs, role="writer"):
    """One JSON answer from the model. Waits when the free tier is busy; retries broken replies."""
    global _waited
    broken = 0
    for attempt in range(10):
        model = pick(role)
        body = {"model": model, "messages": msgs, "temperature": 0.2 if role == "editor" else 0.6,
                "response_format": {"type": "json_object"}}
        if "gpt-oss" in model:
            body["reasoning_effort"] = "low"   # these models otherwise spend the whole budget thinking
        kind, code, resp = None, 0, None
        try:
            resp = requests.post(base_url() + "/chat/completions", headers=headers(), json=body, timeout=180)
            if resp.ok:
                return json.loads(resp.json()["choices"][0]["message"]["content"])
            code = resp.status_code
            log(f"model said HTTP {code} ({model}):", resp.text[:600])
            text = resp.text.lower()
            if code == 400 and ("json" in text or "generate" in text):
                kind = "broken"
            elif code in (429, 500, 502, 503, 504):
                kind = "busy"
            else:
                resp.raise_for_status()
        except (json.JSONDecodeError, KeyError, IndexError):
            kind = "broken"
        if kind == "broken":
            broken += 1
            if broken > 3:
                raise RuntimeError("The model keeps returning a broken reply; try again later.")
            log(f"broken reply from the model; trying again ({broken}/3)")
            time.sleep(8)
            continue
        try:
            wait = float(resp.headers.get("retry-after")) + 3
        except Exception:
            wait = 25 * (attempt + 1)
        wait = min(wait, 90)
        if _waited + wait > WAIT_BUDGET:
            raise RuntimeError("The free model stayed busy too long; try again in a few minutes.")
        _waited += wait
        log(f"model busy (HTTP {code}); waiting {wait:.0f}s before trying again")
        time.sleep(wait)
    raise RuntimeError("The model did not answer.")
