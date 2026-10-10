#!/usr/bin/env python3
"""Nova Metrics marketing agent.

python agent/run.py generate   -> research, write, validate, render image (writes out/pending.json)
python agent/run.py publish    -> send pending post to the Make webhook, record it in history
"""
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests

import editor

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT = ROOT / "agent"
OUT = ROOT / "out"
HIST = ROOT / "data" / "history.json"
PENDING = OUT / "pending.json"
SAST = dt.timezone(dt.timedelta(hours=2))
TODAY = dt.datetime.now(SAST).date()
TYPES = ["educator", "industry_observer", "product_demonstration",
         "conversation_starter", "founder_voice"]
LOGO = ("https://zloxcqrhkcohheeixfns.supabase.co/storage/v1/object/public/"
        "pdf_proposals/logo%20storage/Nova%20Metrics%20Logo.png")

SCHEMA = """

Return ONLY a JSON object with exactly these keys:
{"type": "<one of educator|industry_observer|product_demonstration|conversation_starter|founder_voice|event>",
 "topic": "<5-10 word topic>", "linkedin": "<post>", "facebook": "<post>",
 "headline": "<image headline>", "subline": "<image subline>",
 "visual": "card" or "demo_screenshot", "founder_attention": null or "<short sentence>"}
You are also given verified_facts. Never state what a law, regulator or standard requires unless it is
listed there. If an editor note later asks you to fix a claim and you are sure it is right, you may add a
key "pushback": [{"claim": "...", "reason": "...", "quote": "exact words from the source material"}]."""


def env(key, default=""):
    return os.environ.get(key) or default


def log(*a):
    print(*a, file=sys.stderr)


def load_history():
    try:
        return json.loads(HIST.read_text())
    except Exception:
        return []


# ---------------------------------------------------------------- research
def page_text(url, limit=5000):
    h = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).text
    h = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", h)
    t = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()[:limit]


def gather():
    facts = {"recent_product_changes": [], "live_site_text": {}, "industry_headlines": []}
    site = env("SITE_URL", "https://www.novametricsgroup.com").rstrip("/")
    repo = env("SITE_REPO", "Kharst/novametricsgroup.github.io")
    since = (dt.datetime.utcnow() - dt.timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    hdr = {"Accept": "application/vnd.github+json"}
    if env("SITE_REPO_TOKEN"):
        hdr["Authorization"] = "Bearer " + env("SITE_REPO_TOKEN")
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/commits",
                         params={"since": since, "per_page": 50}, headers=hdr, timeout=30)
        r.raise_for_status()
        facts["recent_product_changes"] = [
            c["commit"]["message"].split("\n")[0][:140] for c in r.json()]
    except Exception as e:
        log("commits unavailable:", e)
    for path in ("/", "/faq"):
        try:
            facts["live_site_text"][path] = page_text(site + path)
        except Exception as e:
            log("site page unavailable:", path, e)
    try:
        q = "South Africa solar installers OR SSEG OR NERSA OR Eskom rooftop solar when:14d"
        r = requests.get("https://news.google.com/rss/search", timeout=30,
                         params={"q": q, "hl": "en-ZA", "gl": "ZA", "ceid": "ZA:en"})
        root = ET.fromstring(r.content)
        facts["industry_headlines"] = [i.findtext("title") for i in root.iter("item")][:10]
    except Exception as e:
        log("news unavailable:", e)
    return facts


def events():
    out = []
    for e in json.loads((AGENT / "events.json").read_text()):
        start = dt.date.fromisoformat(e["start"])
        end = dt.date.fromisoformat(e["end"])
        if (end - TODAY).days >= -3:
            e = dict(e)
            e["days_to_event"] = (start - TODAY).days
            e["days_since_end"] = (TODAY - end).days
            out.append(e)
    return out


# --------------------------------------------------------------------- LLM
def pick_model(base, hdr):
    """Kept for the article agent; the shared client in llmclient.py now does the real work."""
    import llmclient
    return llmclient.pick("writer")


def llm(messages):
    import llmclient
    return llmclient.chat_json(messages, role="writer")


# -------------------------------------------------------------- guardrails
BANNED = re.compile(
    r"guarantee|number one|#1\b|100\s?%|\bbugs?\b|\bfix(ed|es)?\b|\bpatch|edge function|"
    r"supabase|\bRLS\b|migration|api key|\bR\s?\d", re.I)


def validate(p, corpus, stand):
    errs = []
    for k in ("type", "topic", "linkedin", "facebook", "headline", "subline"):
        if not isinstance(p.get(k), str) or not p[k].strip():
            errs.append(f"missing {k}")
    if errs:
        return errs
    text = " ".join([p["linkedin"], p["facebook"], p["headline"], p["subline"]])
    if not 300 <= len(p["linkedin"]) <= 1300:
        errs.append("linkedin must be 450-1100 characters")
    if not 100 <= len(p["facebook"]) <= 600:
        errs.append("facebook must be 150-450 characters")
    if len(p["headline"]) > 70 or len(p["subline"]) > 110:
        errs.append("headline max 70 chars, subline max 110 chars")
    if re.search(r"[\[\]{}]", text):
        errs.append("remove brackets and placeholders")
    if BANNED.search(text):
        errs.append("contains a banned word, claim or price")
    if not stand and re.search(r"\bstand\b", text, re.I):
        errs.append("no stand number was provided; do not mention a stand")
    pages = " ".join([p["linkedin"], p["facebook"], p["headline"], p["subline"]])
    if re.search(r"\bI(['\u2019](m|ve|d|ll))?\b", pages) or re.search(r"\b(me|my|myself|mine)\b", pages, re.I):
        errs.append("company page voice: never write in the first person (no I, me, my); use we, our or Nova Metrics")
    if len(re.findall(r"#\w+", p["linkedin"])) > 3:
        errs.append("max 3 hashtags")
    for n in re.findall(r"\d[\d,.]*\d|\d", text):
        plain = n.replace(",", "")
        if plain.isdigit() and int(plain) <= 31:
            continue
        if n not in corpus and plain not in corpus:
            errs.append(f"number '{n}' is not in the source facts; remove it")
    return errs


# ------------------------------------------------------------------- image
def render(p, path, tag):
    from playwright.sync_api import sync_playwright
    tpl = (AGENT / "card.html").read_text()
    shot_html = ""
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        if env("USE_DEMO_SCREENSHOTS") == "1" and p.get("visual") == "demo_screenshot":
            try:
                import base64
                pg = b.new_page(viewport={"width": 1280, "height": 800})
                pg.goto(env("SITE_URL", "https://www.novametricsgroup.com").rstrip("/")
                        + "/solar-intelligence?demo=1", wait_until="networkidle")
                pg.wait_for_timeout(3000)
                data = base64.b64encode(pg.screenshot()).decode()
                shot_html = f'<img class="shot" src="data:image/png;base64,{data}">'
            except Exception as e:
                log("demo screenshot failed, using plain card:", e)
        page = (tpl.replace("{{LOGO}}", LOGO).replace("{{TAG}}", html.escape(tag))
                .replace("{{HEADLINE}}", html.escape(p["headline"]))
                .replace("{{SUBLINE}}", html.escape(p["subline"]))
                .replace("{{SHOT}}", shot_html))
        pg = b.new_page(viewport={"width": 1080, "height": 1080})
        pg.set_content(page, wait_until="networkidle")
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(path), type="jpeg", quality=92)
        b.close()


# ------------------------------------------------------------------- stages
def post_text(p):
    return (f"LINKEDIN:\n{p.get('linkedin', '')}\n\nFACEBOOK:\n{p.get('facebook', '')}\n\n"
            f"IMAGE HEADLINE: {p.get('headline', '')}\nIMAGE SUBLINE: {p.get('subline', '')}")


def generate():
    hist = load_history()
    force = env("FORCE") == "true"
    if hist and not force:
        last = dt.date.fromisoformat(hist[-1]["date"])
        if (TODAY - last).days < int(env("MIN_DAYS", "1")):
            log("Posted recently; nothing to do today.")
            return
    brand = (AGENT / "brand.md").read_text()
    facts = gather()
    evs = events()
    stand = env("STAND_NO")
    ctx = {
        "today": TODAY.isoformat(),
        "suggested_type": TYPES[len(hist) % len(TYPES)],
        "stand_number": stand or None,
        "events": evs,
        "recent_posts": [{"date": h["date"], "type": h["type"], "topic": h["topic"],
                          "opening": h["opening"]} for h in hist[-12:]],
        "verified_facts": editor.ledger_lines(),
        **facts,
    }
    corpus = brand + json.dumps(evs) + stand + json.dumps(facts["live_site_text"]) + json.dumps(editor.ledger_lines())
    msgs = [{"role": "system", "content": brand + SCHEMA},
            {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}]
    p, held, reviews = None, None, 0
    for _ in range(7):
        p = llm(msgs)
        errs = validate(p, corpus, stand)
        text = post_text(p)
        errs += editor.never_hits(text)
        if not errs and editor.needs_review(text):
            reviews += 1
            time.sleep(15)  # free-tier rate limit
            rev = editor.review(text, json.dumps(facts["live_site_text"]), p.get("pushback"), kind="post")
            if rev["unavailable"]:
                if editor.has_regulatory(text):
                    held = {"open": [], "why": "The editor could not be reached and the draft makes regulatory claims."}
                    break
            elif not rev["ok"]:
                log("editor open claims:", [c["text"] for c in rev["open"]])
                if reviews >= 3:
                    held = {"open": rev["open"], "why": "The writer and the editor could not settle these claims."}
                    break
                msgs += [{"role": "assistant", "content": json.dumps(p)},
                         {"role": "user", "content": editor.feedback(rev["open"])}]
                continue
        if not errs:
            break
        log("rejected:", errs)
        msgs += [{"role": "assistant", "content": json.dumps(p)},
                 {"role": "user", "content": "Rejected: " + "; ".join(errs)
                  + ". Rewrite and return the full JSON again."}]
    else:
        sys.exit("The agent could not produce a compliant post today: " + "; ".join(errs))

    if held:
        body = (held["why"] + "\n\n### Draft that was held\n\n" + post_text(p)
                + "\n\n### Claims in dispute\n\n" + (editor.dispute_markdown(held["open"], p.get("pushback")) or "(none listed)")
                + "\n\n### What to do\n\nCheck the claim against the real standard or regulator. If it is right, "
                "add a line starting VERIFIED: to agent/verified_facts.md. If it is wrong, add a NEVER: line. "
                "Nothing was posted today. Tomorrow's run starts fresh.")
        editor.open_issue("Post held: needs your decision (" + str(p.get("topic", "")) + ")", body)
        hist.append({"date": TODAY.isoformat(), "type": str(p.get("type", "held")), "topic": str(p.get("topic", "")),
                     "opening": str(p.get("linkedin", "")).strip().split("\n")[0][:90], "mode": "held"})
        HIST.write_text(json.dumps(hist, indent=2, ensure_ascii=False))
        log("Post held for the founder.")
        return

    mentions_event = bool(re.search(r"cape town|solar & storage", p["linkedin"] + p["facebook"], re.I))
    tag = evs[0]["tag"] if (evs and mentions_event) else "NOVA METRICS · SOLAR INTELLIGENCE"
    stamp = dt.datetime.now(SAST).strftime("%H%M%S")
    post_id = f"{TODAY.isoformat()}-{stamp}"
    name = f"{post_id}.jpg"
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    render(p, OUT / "images" / name, tag)
    branch = env("GITHUB_REF_NAME", "main")
    repo = env("GITHUB_REPOSITORY", "OWNER/REPO")
    p["image_url"] = f"https://raw.githubusercontent.com/{repo}/{branch}/out/images/{name}"
    p["date"] = TODAY.isoformat()
    p["post_id"] = post_id
    PENDING.write_text(json.dumps(p, indent=2, ensure_ascii=False))
    log("Generated:", p["topic"])


def publish():
    if not PENDING.exists():
        log("Nothing pending.")
        return
    p = json.loads(PENDING.read_text())
    # Make keys its stored post and Approve link on "date", so send the unique id there
    payload = dict(p, date=p.get("post_id", p["date"]), mode=env("MODE", "review"))
    payload.pop("post_id", None)
    r = requests.post(env("MAKE_WEBHOOK_URL"), json=payload, timeout=60)
    r.raise_for_status()
    hist = load_history()
    hist.append({"date": p["date"], "type": p["type"], "topic": p["topic"],
                 "opening": p["linkedin"].strip().split("\n")[0][:90], "mode": payload["mode"]})
    HIST.write_text(json.dumps(hist, indent=2, ensure_ascii=False))
    PENDING.unlink()
    log("Sent to Make in", payload["mode"], "mode.")


if __name__ == "__main__":
    {"generate": generate, "publish": publish}[sys.argv[1]]()
