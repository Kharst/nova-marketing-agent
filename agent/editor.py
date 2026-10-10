#!/usr/bin/env python3
"""Nova Metrics fact-checking editor.

The writing agents (daily posts, weekly articles) hand every draft to this editor before it can reach
the founder. The editor:
  1. blocks anything on the NEVER list in verified_facts.md (pattern match, no AI involved),
  2. lists every regulatory, technical and financial claim and checks it against exact quotes:
       - regulatory claims need a VERIFIED line in verified_facts.md,
       - technical, financial and product claims need a quote from the product facts or the sources,
  3. researches unproven claims on official South African websites (if SEARCH_API_KEY is set),
  4. returns what is still open, so the writer can fix it, push back, or hand it to the founder.

The model's own verdict is never trusted: the code re-checks every quote.
"""
import json
import os
import pathlib
import re
import sys
import time
from urllib.parse import urlparse

import requests

AGENT = pathlib.Path(__file__).resolve().parent
LEDGER = AGENT / "verified_facts.md"
BRAND = AGENT / "brand.md"

OK = ("ok", "researched_ok")
OFFICIAL = ("nersa.org.za", "eskom.co.za", "sabs.co.za", "gov.za", "energy.gov.za", "sars.gov.za",
            "capetown.gov.za", "joburg.org.za", "tshwane.gov.za", "sapvia.co.za", "saiee.org.za",
            "ewseta.org.za", "iec.ch")

REG = re.compile(r"\b(NRS|SANS|NERSA|Eskom|IEC|SARS|POPIA|SABS|SSEG|Section\s*12B|municipal\w*|by-?laws?|"
                 r"regulat\w*|standards?|complian\w*|compliant|legislat\w*|legal\w*|licen[cs]\w*|"
                 r"registration|registered|approv\w*|mandat\w*|permitted|allowed)\b", re.I)
TECH = re.compile(r"\d\s?(kW|kWh|kWp|kVA|%|V|A)\b|ratio|depth of discharge|payback|tariff|escalat|yield|"
                  r"degrad|NPV|IRR|autonomy|headroom", re.I)


def env(key, default=""):
    return os.environ.get(key) or default


def log(*a):
    print(*a, file=sys.stderr)


# ------------------------------------------------------------------ ledger
def ledger():
    txt = LEDGER.read_text() if LEDGER.exists() else ""
    verified, never = [], []
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("PENDING:"):
            continue
        if line.startswith("VERIFIED:"):
            verified.append(line[len("VERIFIED:"):].strip())
        elif line.startswith("NEVER:"):
            desc, _, rx = line[len("NEVER:"):].partition("||")
            never.append((desc.strip(), rx.strip()))
    return verified, never


def pending():
    txt = LEDGER.read_text() if LEDGER.exists() else ""
    return [l.strip()[len("PENDING:"):].strip() for l in txt.splitlines() if l.strip().startswith("PENDING:")]


def ledger_lines():
    """What the writers are shown so they know what they may say."""
    verified, never = ledger()
    return {"verified": verified, "never_say": [d for d, _ in never],
            "not_yet_verified_describe_only_as_what_Solar_Intelligence_assumes": pending()}


def never_hits(text):
    """Pattern-based block list: no AI, always on."""
    hits = []
    for desc, rx in ledger()[1]:
        if not rx:
            continue
        try:
            if re.search(rx, text, re.I | re.S):
                hits.append("never-say list: " + desc)
        except re.error:
            log("bad pattern in verified_facts.md:", rx)
    return hits


def needs_review(text):
    return bool(REG.search(text) or TECH.search(text))


def has_regulatory(text):
    return bool(REG.search(text))


def must_check_sentences(text, limit=12):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if REG.search(p) and len(p.strip()) > 15][:limit]


def product_facts():
    try:
        t = BRAND.read_text()
        m = re.search(r"## The product.*?\n(.*?)\n## ", t, re.S)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


# --------------------------------------------------------------- model use
def chat_json(msgs, writer_model=""):
    """Ask the editor model for JSON (shared client: waits when the free tier is busy, retries broken replies)."""
    import llmclient
    try:
        return llmclient.chat_json(msgs, role="editor")
    except Exception as e:
        log("editor model problem:", e)
        raise RuntimeError("editor model unavailable")


# --------------------------------------------------------------- research
def search(query):
    key = env("SEARCH_API_KEY")
    if not key:
        return []
    try:
        if env("SEARCH_PROVIDER", "tavily").lower() == "brave":
            r = requests.get("https://api.search.brave.com/res/v1/web/search",
                             params={"q": query, "count": 8, "country": "ZA"}, timeout=30,
                             headers={"X-Subscription-Token": key, "Accept": "application/json"})
            r.raise_for_status()
            items = [{"url": x["url"], "title": x.get("title", ""), "snippet": x.get("description", "")}
                     for x in r.json().get("web", {}).get("results", [])]
        else:
            r = requests.post("https://api.tavily.com/search", timeout=40,
                              headers={"Authorization": "Bearer " + key},
                              json={"query": query, "max_results": 8, "search_depth": "basic"})
            r.raise_for_status()
            items = [{"url": x["url"], "title": x.get("title", ""), "snippet": x.get("content", "")}
                     for x in r.json().get("results", [])]
    except Exception as e:
        log("search failed:", e)
        return []
    for it in items:
        host = urlparse(it["url"]).netloc.lower()
        it["official"] = any(host == d or host.endswith("." + d) for d in OFFICIAL)
        it["snippet"] = " ".join(it["snippet"].split())[:900]
    return sorted(items, key=lambda i: not i["official"])[:6]


# ------------------------------------------------------------------ prompts
EDITOR_PROMPT = """You are the fact-checking editor for Nova Metrics, a South African solar software company.
Writers draft posts and articles that go out under the company name. You never write copy. You check claims.

Find every claim in the draft that:
- says what a law, regulator, standard, utility, municipality or industry body requires, allows, defines
  or recommends (kind "regulatory"). Any use of "compliant", "compliance", "approved", "registered",
  "aligned to" or "the standard" counts;
- states an engineering rule or threshold (kind "technical");
- states a savings, tariff, cost or return figure (kind "financial");
- describes what Solar Intelligence does (kind "product").
Also cover every sentence listed in must_check_sentences.

Give each claim a status:
- "ok": backed by an exact quote. A regulatory claim is ok ONLY if a line in verified_facts says it.
  Technical, financial and product claims are ok if product_facts or source_material says it.
  Put the exact quote (10 to 30 words, copied word for word) in "evidence".
- "never": the claim matches something in never_say.
- "unsupported": no such quote exists. The company's own website text (source_material) is NOT proof of
  what a standard, law or regulator says.
If you are unsure, choose "unsupported". Do not give the benefit of the doubt.
For every claim that is not "ok", write "fix": a rewrite of the sentence that says only what is known,
usually by describing what Solar Intelligence checks or flags instead of what a standard requires.
If writer_pushback is present, the writer contests those claims. Weigh its reasons, but the rules above
still apply.

Return ONLY JSON: {"claims":[{"id":"c1","text":"...","kind":"regulatory|technical|financial|product",
"status":"ok|never|unsupported","evidence":"...","fix":"..."}]}"""

RESEARCH_PROMPT = """You verify claims using web search results. For each claim decide:
- "researched_ok": a result marked official=true clearly states it. Give that result's url and an exact
  quote (under 25 words) copied word for word from that result's snippet.
- "researched_contradicted": an official result clearly says the opposite.
- "unverifiable": anything else.
Never invent a url or a quote. Return ONLY JSON:
{"verdicts":[{"id":"c1","status":"researched_ok|researched_contradicted|unverifiable","url":"...","quote":"...","note":"one sentence"}]}"""


# ------------------------------------------------------------------- review
def _enforce(claims, verified, product, source):
    """Re-check every 'ok' against the real text; downgrade anything the model could not quote."""
    v_norm = [norm(x) for x in verified]
    other = norm(product + " " + source)
    out = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        c = {"id": str(c.get("id", "")), "text": str(c.get("text", "")), "kind": str(c.get("kind", "")),
             "status": str(c.get("status", "unsupported")), "evidence": str(c.get("evidence", "")),
             "fix": str(c.get("fix", ""))}
        if c["status"] == "ok":
            q = norm(c["evidence"])
            if len(q) < 15:
                c["status"] = "unsupported"
            elif c["kind"] == "regulatory":
                if not any(q in v for v in v_norm):
                    c["status"] = "unsupported"
            elif q not in other and not any(q in v for v in v_norm):
                c["status"] = "unsupported"
        elif c["status"] not in ("never", "unsupported"):
            c["status"] = "unsupported"
        out.append(c)
    return out


def review(text, source_text="", pushback=None, writer_model="", kind="post"):
    """Check a draft. Returns {ok, claims, open, unavailable}."""
    verified, never = ledger()
    product = product_facts()
    payload = {"draft": text, "verified_facts": verified, "never_say": [d for d, _ in never],
               "product_facts": product, "source_material": source_text[:4500],
               "must_check_sentences": must_check_sentences(text)}
    if pushback:
        payload["writer_pushback"] = pushback
    try:
        res = chat_json([{"role": "system", "content": EDITOR_PROMPT},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], writer_model)
    except RuntimeError as e:
        log(e)
        return {"ok": False, "unavailable": True, "claims": [], "open": []}
    claims = _enforce(res.get("claims", []), verified, product, source_text)

    # research whatever is still unproven (needs a search key; otherwise it stays unproven)
    todo = [c for c in claims if c["status"] == "unsupported" and c["kind"] in
            ("regulatory", "technical", "financial")][:3]
    if todo and env("SEARCH_API_KEY"):
        found = {}
        for c in todo:
            found[c["id"]] = search(re.sub(r"\s+", " ", c["text"])[:180] + " South Africa")
            time.sleep(1)
        if any(found.values()):
            try:
                res2 = chat_json([{"role": "system", "content": RESEARCH_PROMPT},
                                  {"role": "user", "content": json.dumps({
                                      "claims": [{"id": c["id"], "text": c["text"]} for c in todo],
                                      "research": found}, ensure_ascii=False)}], writer_model)
                for v in res2.get("verdicts", []):
                    c = next((x for x in todo if x["id"] == str(v.get("id"))), None)
                    if not c:
                        continue
                    st = str(v.get("status"))
                    hit = next((r for r in found[c["id"]] if r["url"] == v.get("url")), None)
                    if st == "researched_ok":
                        # accept only an official source and a quote that really is in its snippet
                        q = norm(v.get("quote", ""))
                        if hit and hit["official"] and len(q) >= 15 and q in norm(hit["snippet"]):
                            c["status"], c["evidence"] = "researched_ok", f'{hit["url"]} : "{v.get("quote")}"'
                        else:
                            c["status"] = "unverifiable"
                    elif st == "researched_contradicted" and hit and hit["official"]:
                        c["status"], c["evidence"] = "researched_contradicted", f'{hit["url"]} : {v.get("note", "")}'
                    else:
                        c["status"] = "unverifiable"
            except RuntimeError as e:
                log("research step skipped:", e)

    open_claims = [c for c in claims if c["status"] not in OK]
    return {"ok": not open_claims, "claims": claims, "open": open_claims, "unavailable": False}


def feedback(open_claims):
    lines = []
    for c in open_claims:
        lines.append(f'- "{c["text"]}" ({c["kind"]}, {c["status"]}). Rewrite as: {c["fix"] or "say only what Solar Intelligence does"}')
    return ("The editor could not verify these claims:\n" + "\n".join(lines) +
            "\nFix each one. If you are sure a claim is right, keep it and add an entry to a \"pushback\" "
            "list: {\"claim\": \"...\", \"reason\": \"...\", \"quote\": \"exact words from the source "
            "material\"}. Regulatory claims still need a verified_facts line or an official source.")


def dispute_markdown(open_claims, pushback=None):
    out = []
    for c in open_claims:
        out.append(f'- **Claim:** {c["text"]}\n  - Kind: {c["kind"]}, status: {c["status"]}\n'
                   f'  - Editor suggests: {c["fix"] or "remove it"}'
                   + (f'\n  - Evidence found: {c["evidence"]}' if c["evidence"] else ""))
    if pushback:
        out.append("\n**Writer's pushback:**\n" + "\n".join(
            f'- {p.get("claim", "")}: {p.get("reason", "")} (quote: "{p.get("quote", "")}")'
            for p in pushback if isinstance(p, dict)))
    return "\n".join(out)


# ---------------------------------------------------------------- escalate
def open_issue(title, body):
    repo, tok = env("GITHUB_REPOSITORY"), env("GH_TOKEN") or env("GITHUB_TOKEN")
    if not (repo and tok):
        sys.exit("Held for your decision, but no GitHub token to open an issue.\n" + title + "\n" + body)
    r = requests.post(f"https://api.github.com/repos/{repo}/issues", timeout=30,
                      headers={"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json"},
                      json={"title": title, "body": body})
    if not r.ok:
        # fail loudly so the failed run emails the founder
        sys.exit(f"Held for your decision, but the issue could not be opened (HTTP {r.status_code}). "
                 f"Add 'issues: write' to the workflow permissions.\n{title}\n{body}")
    log("Issue opened:", r.json().get("html_url"))
