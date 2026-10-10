#!/usr/bin/env python3
"""Nova Metrics weekly article agent.

python agent/article.py generate   -> write one SEO article from approved sources into articles-queue/
python agent/article.py publish    -> copy approved (merged) articles to the website repo, update the
                                      articles index and the sitemap

Nothing reaches the website until the founder merges the pull request that generate opens.
"""
import base64
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run as base  # noqa: E402  (shared helpers: env, log, llm, events, gather)

ROOT = base.ROOT
AGENT = base.AGENT
OUT = base.OUT
QUEUE = ROOT / "articles-queue"
ARTICLES = ROOT / "data" / "articles.json"
TODAY = base.TODAY
LOGO = base.LOGO
env, log = base.env, base.log

MIN_WORDS, MAX_WORDS = 550, 1300

# Evergreen topics, in the order they are written. Each one is grounded in pages that already
# exist on the website, so the model never has to rely on its own memory for facts.
TOPICS = [
    {"key": "system-sizing",
     "angle": "How solar installers can size a PV and battery system without guesswork: DC/AC ratio, "
              "battery headroom and backup hours",
     "sources": ["resources/system-sizing-guide.html"]},
    {"key": "proposal-numbers",
     "angle": "How to explain the numbers in a solar proposal so clients trust them: production, "
              "savings, tariff escalation and payback",
     "sources": ["resources/solar-intelligence-guide.html"]},
    {"key": "proposal-that-sells",
     "angle": "What a solar proposal needs so the client can say yes the same week",
     "sources": ["resources/proposal-guide.html"]},
    {"key": "compliance",
     "angle": "Technical compliance for small-scale embedded generation: what installers should check "
              "before a system goes in",
     "sources": ["resources/technical-compliance-guide.html"]},
    {"key": "site-visit",
     "angle": "A practical site visit checklist for solar installers: confirm the design against what is "
              "actually on the roof",
     "sources": ["resources/site-visit-checklist.html"]},
    {"key": "closing-the-job",
     "angle": "Turning a solar proposal into a signed job: follow-up that respects the client",
     "sources": ["resources/sales-closing-guide.html"]},
    {"key": "battery-backup",
     "angle": "Sizing batteries for backup: how to check that the battery meets what the client actually "
              "asked for",
     "sources": ["resources/system-sizing-guide.html", "resources/solar-intelligence-guide.html"]},
    {"key": "commercial-solar-12b",
     "angle": "The financial case for commercial solar: cash flow, NPV, IRR and the Section 12B incentive "
              "explained for business clients",
     "sources": ["resources/solar-intelligence-guide.html"]},
]

SCHEMA = """

THIS TASK IS A WEBSITE ARTICLE, NOT A SOCIAL POST. Ignore the Format, Content types and Event rules
sections above. All other rules above still apply (company voice, no invention, no prices, no first person).

Write ONE article for South African solar installers, EPCs and electricians, built only from the source
material in the user message plus the product facts in the brief.

Article rules:
- Total length 650 to 950 words. Short paragraphs, at most 70 words each. 4 or 5 sections.
- Plain-spoken, useful, no hype. Teach first. Mention Solar Intelligence at most twice, only where it
  genuinely fits, as a tool that helps. Never mention prices, plans, trials or discounts.
- Every fact, figure, standard and rule must come from the source material. If a detail is not in the
  sources, leave it out. Use only numbers that appear in the sources.
- Never mention the partner programme, partner portal, partners, commissions or internal documents.
  Address the reader directly as an installer.
- title: at most 65 characters INCLUDING spaces (count them), with the main search phrase used naturally.
- Do not add ANY number that is not written in the source material: no estimates, averages, percentages
  or counts of your own. If you are not sure a number is in the sources, write the sentence without it.
- slug: lowercase words joined by hyphens, at most 60 characters.
- meta_description: 120 to 158 characters. excerpt: at most 180 characters.
- faq: exactly 3 questions an installer might type into Google, each answer 1 to 3 sentences, taken from
  the article or sources. Word the questions without "I", "my" or "me" (for example "What DC/AC ratio
  should installers aim for?").
- closing: one or two sentences inviting the reader to see how Solar Intelligence handles this.
- review_notes: up to 6 short strings. Each names a figure, standard or regulatory statement in the
  article that a human should verify against the source.

Return ONLY a JSON object with exactly these keys:
{"title": "...", "slug": "...", "meta_description": "...", "excerpt": "...", "intro": "...",
 "sections": [{"heading": "...", "paragraphs": ["..."], "bullets": ["..."] }],
 "faq": [{"q": "...", "a": "..."}], "closing": "...", "review_notes": ["..."]}
"bullets" may be an empty list. Use plain text only: no HTML, no markdown, no brackets."""

BANNED = re.compile(
    r"guarantee|number one|#1\b|best-in-class|revolutionary|game.?changer|supabase|\bRLS\b|"
    r"edge function|api key|our (customers|clients)|customers say|clients (tell|told) us|testimonial|"
    r"case study|\bpartner(s|ship)?\b|commission|free trial|discount|per month|/month|\bR\s?\d", re.I)


# ----------------------------------------------------------------- history
def load_articles():
    try:
        return json.loads(ARTICLES.read_text())
    except Exception:
        return []


def save_articles(items):
    ARTICLES.parent.mkdir(parents=True, exist_ok=True)
    ARTICLES.write_text(json.dumps(items, indent=2, ensure_ascii=False))


# ----------------------------------------------------------- site repo I/O
def site_repo():
    return env("SITE_REPO", "Kharst/novametricsgroup.github.io")


def site_headers(raw=False):
    h = {"Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json"}
    if env("SITE_REPO_TOKEN"):
        h["Authorization"] = "Bearer " + env("SITE_REPO_TOKEN")
    return h


def strip_html(h, limit=7000):
    h = re.sub(r"(?is)<(script|style|noscript|head).*?</\1>", " ", h)
    t = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()[:limit]


def read_site_file(path):
    """Read a file from the (private) website repo; fall back to the live site."""
    url = f"https://api.github.com/repos/{site_repo()}/contents/{path}"
    try:
        r = requests.get(url, headers=site_headers(raw=True), timeout=30)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log("repo read failed for", path, "-", e)
    live = env("SITE_URL", "https://www.novametricsgroup.com").rstrip("/")
    r = requests.get(f"{live}/{re.sub(r'[.]html$', '', path)}", timeout=30,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.text


def site_get(path):
    r = requests.get(f"https://api.github.com/repos/{site_repo()}/contents/{path}",
                     headers=site_headers(), timeout=30)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    j = r.json()
    return base64.b64decode(j["content"]), j["sha"]


def site_put(path, data, message):
    _, sha = site_get(path)
    body = {"message": message, "content": base64.b64encode(data).decode()}
    if sha:
        body["sha"] = sha
    branch = env("SITE_BRANCH")
    if branch:
        body["branch"] = branch
    r = requests.put(f"https://api.github.com/repos/{site_repo()}/contents/{path}",
                     headers=site_headers(), json=body, timeout=60)
    if r.status_code in (401, 403, 404):
        sys.exit(f"Could not write {path} to {site_repo()} (HTTP {r.status_code}). "
                 "SITE_REPO_TOKEN needs 'Contents: Read and write' on the website repository.")
    r.raise_for_status()


# ------------------------------------------------------------ model calls
PAUSE = int(env("ARTICLE_PAUSE", "60"))     # seconds to rest between rewrites (free tier limit per minute)
WAIT_BUDGET = int(env("ARTICLE_WAIT_BUDGET", "420"))
_waited = 0


_model = None


def pick_article_model(url, hdr):
    """Long articles need a plain (non-'thinking') model; fall back to the shared pick."""
    ids = [m["id"] for m in requests.get(url + "/models", headers=hdr, timeout=30).json()["data"]]
    skip = re.compile(r"whisper|guard|tts|embed|vision|distil|preview", re.I)
    for pat in ("llama-3.3-70b", "llama-3.1-70b", "70b"):
        for i in ids:
            if pat in i and not skip.search(i):
                return i
    return base.pick_model(url, hdr)


def model_call(msgs):
    """One request to the free model. Prints the reason if the service refuses."""
    global _model
    url = env("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    hdr = {"Authorization": "Bearer " + env("LLM_API_KEY")}
    if not _model:
        _model = env("ARTICLE_MODEL") or pick_article_model(url, hdr)
        log("article model:", _model)
    body = {"model": _model, "messages": msgs, "temperature": 0.6,
            "response_format": {"type": "json_object"}}
    if "gpt-oss" in _model:
        body["reasoning_effort"] = "low"      # these models otherwise spend the budget thinking
    r = requests.post(url + "/chat/completions", headers=hdr, timeout=180, json=body)
    if not r.ok:
        log(f"model said HTTP {r.status_code} ({_model}):", r.text[:700])
        r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])


def ask(msgs):
    """Call the model. Wait and retry if it is busy, retry if it returns a broken reply."""
    global _waited
    broken = 0
    for attempt in range(10):
        try:
            return model_call(msgs)
        except (json.JSONDecodeError, KeyError, IndexError):
            kind, code = "broken", 0
        except requests.HTTPError as e:
            r = e.response
            code = r.status_code if r is not None else 0
            body = (r.text if r is not None else "").lower()
            if code == 400 and ("json" in body or "generate" in body):
                kind = "broken"
            elif code in (429, 500, 502, 503, 504):
                kind = "busy"
            else:
                raise
        if kind == "broken":
            broken += 1
            if broken > 3:
                raise RuntimeError("The model keeps returning a broken reply; try again later.")
            log(f"broken reply from the model; trying again ({broken}/3)")
            time.sleep(8)
            continue
        try:
            wait = float(r.headers.get("retry-after")) + 3
        except Exception:
            wait = 25 * (attempt + 1)
        wait = min(wait, 90)
        if _waited + wait > WAIT_BUDGET:
            raise RuntimeError("The free model stayed busy too long; try again in a few minutes.")
        _waited += wait
        log(f"model busy (HTTP {code}); waiting {wait:.0f}s before trying again")
        time.sleep(wait)
    raise RuntimeError("The model did not answer.")


# ---------------------------------------------------------------- validate
def all_text(a):
    parts = [a.get("title", ""), a.get("meta_description", ""), a.get("excerpt", ""),
             a.get("intro", ""), a.get("closing", "")]
    for s in a.get("sections", []):
        parts += [s.get("heading", "")] + list(s.get("paragraphs", [])) + list(s.get("bullets", []))
    for f in a.get("faq", []):
        parts += [f.get("q", ""), f.get("a", "")]
    return [p for p in parts if isinstance(p, str)]


def word_count(a):
    body = [a["intro"], a["closing"]]
    for s in a["sections"]:
        body += [s["heading"]] + s["paragraphs"] + s.get("bullets", [])
    for f in a["faq"]:
        body += [f["q"], f["a"]]
    return len(" ".join(body).split())


def validate(a, corpus, stand, used_slugs):
    errs = []
    try:
        for k in ("title", "slug", "meta_description", "excerpt", "intro", "closing"):
            if not isinstance(a.get(k), str) or not a[k].strip():
                errs.append(f"missing {k}")
        secs = a.get("sections")
        if not isinstance(secs, list) or not 3 <= len(secs) <= 7:
            errs.append("need 4 or 5 sections")
        else:
            for s in secs:
                if not isinstance(s.get("heading"), str) or not isinstance(s.get("paragraphs"), list) \
                        or not s["paragraphs"] or not all(isinstance(x, str) for x in s["paragraphs"]):
                    errs.append("every section needs a heading and paragraphs (strings)")
                    break
                s.setdefault("bullets", [])
                if not isinstance(s["bullets"], list) or not all(isinstance(x, str) for x in s["bullets"]):
                    errs.append("bullets must be a list of strings")
                    break
        faq = a.get("faq")
        if not isinstance(faq, list) or len(faq) != 3 or not all(
                isinstance(f, dict) and isinstance(f.get("q"), str) and isinstance(f.get("a"), str)
                for f in faq):
            errs.append("faq must be exactly 3 {q, a} items")
        if not isinstance(a.get("review_notes"), list):
            a["review_notes"] = []
        a["review_notes"] = [str(x) for x in a["review_notes"]][:6]
    except Exception as e:  # malformed structure
        return [f"malformed article structure: {e}"]
    if errs:
        return errs

    text = " ".join(all_text(a))
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", a["slug"]) or len(a["slug"]) > 60:
        errs.append("slug must be lowercase words joined by hyphens, max 60 characters")
    if a["slug"] in used_slugs:
        errs.append("slug already used; choose a different one")
    if len(a["title"]) > 65:
        errs.append("title max 65 characters")
    if not 120 <= len(a["meta_description"]) <= 160:
        errs.append("meta_description must be 120 to 158 characters")
    if len(a["excerpt"]) > 180:
        errs.append("excerpt max 180 characters")
    wc = word_count(a)
    if not MIN_WORDS <= wc <= MAX_WORDS:
        errs.append(f"article is {wc} words; it must be 650 to 950")
    if re.search(r"[\[\]{}<>]|\*\*|^#", text, re.M):
        errs.append("plain text only: remove brackets, markup and markdown")
    if BANNED.search(text):
        errs.append("contains a banned word or claim (guarantees, hype, testimonials, partners, prices, "
                    "trials, internals)")
    if re.search(r"\bI(['’](m|ve|d|ll))?\b", text) or re.search(r"\b(me|my|myself|mine)\b", text, re.I):
        errs.append("company voice: never use I, me or my; write as we, our or Nova Metrics")
    if not stand and re.search(r"\bstand\b", text, re.I):
        errs.append("do not mention a stand")
    if len(re.findall(r"Solar Intelligence", text)) > 3:
        errs.append("you mention Solar Intelligence too often; use it at most twice in the body and once in the closing")
    for n in re.findall(r"\d[\d,.]*\d|\d", text):
        plain = n.replace(",", "")
        if plain.isdigit() and int(plain) <= 31:
            continue
        if n not in corpus and plain not in corpus:
            errs.append(f"number '{n}' is not in the sources; remove it")
    return errs


# ------------------------------------------------------------------ render
CSS = """
:root{--navy:#0A2342;--gold:#C9A84C;--text:#12161F;--muted:#5B6B80;--border:rgba(10,35,66,.12);--surface:#fff;--bg:#F5F7FA}
*{box-sizing:border-box}
body{font-family:'DM Sans',system-ui,sans-serif;background:var(--bg);color:var(--text);margin:0;line-height:1.7}
.topbar{background:var(--navy);padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.topbar img{height:30px;display:block}
.topbar nav a{color:#fff;font-size:13px;text-decoration:none;margin-left:20px;opacity:.85}
.topbar nav a:hover{color:var(--gold);opacity:1}
.wrap{max-width:740px;margin:0 auto;padding:48px 22px 72px}
.eyebrow{font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#9A7B22;margin-bottom:10px}
h1{font-family:'DM Serif Display',Georgia,serif;font-weight:400;font-size:2.15rem;line-height:1.2;margin:0 0 10px;color:var(--navy)}
.meta{color:var(--muted);font-size:13px;margin-bottom:28px}
.lead{font-size:18px;color:#2b3646;margin:0 0 24px}
h2{font-family:'DM Serif Display',Georgia,serif;font-weight:400;font-size:1.45rem;line-height:1.25;color:var(--navy);margin:38px 0 10px}
p{margin:0 0 15px;font-size:16px;color:#2b3646}
ul{margin:0 0 18px;padding-left:22px}li{margin-bottom:7px;font-size:16px;color:#2b3646}
.faq h3{font-size:16px;font-weight:700;color:var(--navy);margin:22px 0 6px}
.event,.cta{background:#FBF6EA;border:1px solid rgba(201,168,76,.4);border-radius:12px;padding:20px 22px;margin:34px 0 0}
.cta{background:var(--navy);border-color:var(--navy);color:#fff}
.cta p{color:#e7ecf3}.cta strong{color:#fff}
.btn{display:inline-block;background:var(--gold);color:#1A1305;font-weight:700;font-size:14px;padding:11px 20px;border-radius:7px;text-decoration:none;margin:4px 10px 0 0}
.btn.alt{background:transparent;color:#fff;border:1px solid rgba(255,255,255,.4)}
.list a.item{display:block;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px 22px;margin-bottom:14px;text-decoration:none}
.list a.item:hover{border-color:var(--gold)}
.list .t{font-family:'DM Serif Display',Georgia,serif;font-size:1.3rem;color:var(--navy);margin:0 0 4px}
.list .d{font-size:12px;color:var(--muted);margin-bottom:6px}.list .x{font-size:15px;color:#2b3646;margin:0}
footer{text-align:center;padding:30px;color:var(--muted);font-size:12px}
footer a{color:var(--muted)}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family='
         'DM+Serif+Display&display=swap" rel="stylesheet">')


def site_url():
    return env("SITE_URL", "https://www.novametricsgroup.com").rstrip("/")


def esc(s):
    return html.escape(s, quote=True)


def nice_date(d):
    return f"{d.day} {d.strftime('%B %Y')}"


def top(page_title):
    s = site_url()
    return (f'<div class="topbar"><a href="{s}/"><img src="{LOGO}" alt="Nova Metrics"></a>'
            f'<nav><a href="{s}/">Home</a><a href="{s}/solar-intelligence">Solar Intelligence</a>'
            f'<a href="{s}/articles/">Articles</a><a href="{s}/contact">Contact</a></nav></div>')


def foot():
    return (f'<footer>&copy; Nova Metrics (Pty) Ltd &middot; <a href="{site_url()}/privacy">Privacy</a>'
            f' &middot; <a href="{site_url()}/terms">Terms</a></footer>')


def event_block(stand):
    for e in base.events():
        if 0 <= e["days_to_event"] <= 30 and stand:
            start, end = dt.date.fromisoformat(e["start"]), dt.date.fromisoformat(e["end"])
            when = (f"{start.day}–{end.day} {end.strftime('%B %Y')}"
                    if start.month == end.month else f"{nice_date(start)} to {nice_date(end)}")
            return (f'<div class="event"><p><strong>Visiting {esc(e["name"])}?</strong> '
                    f'We are at stand {esc(stand)}, {esc(when)}. Come and see how Solar Intelligence '
                    f'works on a real project.</p>'
                    f'<a class="btn" href="{site_url()}/capetown-2026">Book a short demo</a></div>')
    return ""


def render_article(a, date, stand):
    url = f'{site_url()}/articles/{a["slug"]}'
    wc = word_count(a)
    mins = max(3, round(wc / 200))
    body = [f'<p class="lead">{esc(a["intro"])}</p>']
    for s in a["sections"]:
        body.append(f'<h2>{esc(s["heading"])}</h2>')
        body += [f"<p>{esc(p)}</p>" for p in s["paragraphs"]]
        if s["bullets"]:
            body.append("<ul>" + "".join(f"<li>{esc(b)}</li>" for b in s["bullets"]) + "</ul>")
    body.append('<div class="faq"><h2>Common questions</h2>')
    for f in a["faq"]:
        body.append(f'<h3>{esc(f["q"])}</h3><p>{esc(f["a"])}</p>')
    body.append("</div>")
    cta = (f'<div class="cta"><p><strong>{esc(a["closing"])}</strong></p>'
           f'<a class="btn" href="{site_url()}/solar-intelligence">See Solar Intelligence</a>'
           f'<a class="btn alt" href="{site_url()}/contact">Talk to us</a></div>')
    ld = [{
        "@context": "https://schema.org", "@type": "Article", "headline": a["title"],
        "description": a["meta_description"], "datePublished": date.isoformat(),
        "dateModified": date.isoformat(), "inLanguage": "en-ZA",
        "mainEntityOfPage": url,
        "author": {"@type": "Organization", "name": "Nova Metrics"},
        "publisher": {"@type": "Organization", "name": "Nova Metrics",
                      "logo": {"@type": "ImageObject", "url": LOGO}}},
        {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": f["q"],
                         "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in a["faq"]]}]
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en-ZA">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(a["title"])} | Nova Metrics</title>
<meta name="description" content="{esc(a["meta_description"])}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(a["title"])}">
<meta property="og:description" content="{esc(a["meta_description"])}">
<meta property="og:url" content="{url}">
<meta property="og:site_name" content="Nova Metrics">
<meta property="og:image" content="{LOGO}">
<meta name="twitter:card" content="summary">
{FONTS}
<style>{CSS}</style>
<script type="application/ld+json">{ld_json}</script>
</head>
<body>
{top(a["title"])}
<article class="wrap">
<div class="eyebrow">Nova Metrics &middot; Insights</div>
<h1>{esc(a["title"])}</h1>
<div class="meta">By Nova Metrics &middot; {nice_date(date)} &middot; {mins} min read</div>
{chr(10).join(body)}
{event_block(stand)}
{cta}
</article>
{foot()}
</body>
</html>
"""


def render_index(items):
    pubs = sorted([i for i in items if i["status"] == "published"], key=lambda i: i["date"], reverse=True)
    cards = "".join(
        f'<a class="item" href="{site_url()}/articles/{esc(i["slug"])}">'
        f'<div class="d">{nice_date(dt.date.fromisoformat(i["date"]))}</div>'
        f'<div class="t">{esc(i["title"])}</div><p class="x">{esc(i["excerpt"])}</p></a>'
        for i in pubs) or "<p>New articles are on the way.</p>"
    desc = "Practical guides for South African solar installers from Nova Metrics, the team behind Solar Intelligence."
    return f"""<!DOCTYPE html>
<html lang="en-ZA">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Articles for solar installers | Nova Metrics</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{site_url()}/articles/">
{FONTS}
<style>{CSS}</style>
</head>
<body>
{top("Articles")}
<main class="wrap list">
<div class="eyebrow">Nova Metrics &middot; Insights</div>
<h1>Articles for South African solar installers</h1>
<p class="lead">{esc(desc)}</p>
{cards}
</main>
{foot()}
</body>
</html>
"""


def update_sitemap(existing_xml, items):
    """Keep every existing entry, add the articles, and use the correct sitemap namespace."""
    entries = []
    if existing_xml:
        try:
            root = ET.fromstring(existing_xml)
            for u in root:
                loc = next((c.text for c in u if c.tag.endswith("loc")), None)
                if loc:
                    entries.append(loc.strip())
        except ET.ParseError:
            log("existing sitemap could not be parsed; rebuilding from articles only")
    new = [f"{site_url()}/articles/"] + [
        f'{site_url()}/articles/{i["slug"]}' for i in items if i["status"] == "published"]
    for loc in new:
        if loc not in entries:
            entries.append(loc)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc in entries:
        lines.append(f"  <url><loc>{html.escape(loc)}</loc></url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- stages
def pick_topic(items):
    used = {i.get("topic_key") for i in items}
    for t in TOPICS:
        if t["key"] not in used:
            return t
    return None


def build_context(topic, items):
    recent_social = [h["topic"] for h in base.load_history()[-12:]]
    ctx = {"today": TODAY.isoformat(),
           "already_written_articles": [{"title": i["title"], "slug": i["slug"]} for i in items]}
    texts = []
    if topic:
        ctx["article_angle"] = topic["angle"]
        for path in topic["sources"]:
            t = strip_html(read_site_file(path))
            ctx.setdefault("source_material", {})[path] = t
            texts.append(t)
    else:
        facts = base.gather()
        ctx["article_angle"] = ("Choose one fresh, genuinely useful angle for South African solar "
                                "installers that is not covered by already_written_articles. Base it on "
                                "the live site text, recent product changes and recent social topics.")
        ctx["recent_social_topics"] = recent_social
        ctx.update(facts)
        texts.append(json.dumps(facts, ensure_ascii=False))
    return ctx, " ".join(texts)


def pr_body(a, topic_label, wc):
    lines = [f"## {a['title']}", "",
             f"*Topic:* {topic_label}  \n*Length:* about {wc} words  \n*Will appear at:* "
             f"`{site_url()}/articles/{a['slug']}`", "",
             "**To publish: press Merge pull request. To skip: close it.** Nothing goes on the website "
             "until you merge.", ""]
    if a["review_notes"]:
        lines += ["### Please double-check these points", ""] + [f"- {n}" for n in a["review_notes"]] + [""]
    lines += ["---", "", f"> {a['meta_description']}", "", a["intro"], ""]
    for s in a["sections"]:
        lines += [f"### {s['heading']}", ""] + [p + "\n" for p in s["paragraphs"]]
        lines += [f"- {b}" for b in s["bullets"]] + [""] if s["bullets"] else []
    lines += ["### Common questions", ""]
    for f in a["faq"]:
        lines += [f"**{f['q']}**  ", f["a"], ""]
    lines += ["---", "", a["closing"]]
    return "\n".join(lines)


def generate():
    items = load_articles()
    topic = pick_topic(items)
    stand = env("STAND_NO")
    brand = (AGENT / "brand.md").read_text()
    ctx, source_text = build_context(topic, items)
    corpus = (brand + source_text + json.dumps(base.events()) + stand
              + f" {TODAY.year} {TODAY.year + 1}")
    used = {i["slug"] for i in items}
    first = [{"role": "system", "content": brand + SCHEMA},
             {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}]
    msgs = first
    problems = []
    a, errs = None, []
    for _ in range(5):
        a = ask(msgs)
        errs = validate(a, corpus, stand, used)
        if not errs:
            break
        log("rejected:", errs)
        time.sleep(PAUSE)
        # Keep requests small: send the list of problems, not the whole failed draft.
        problems = (problems + errs)[-8:]
        msgs = first + [{"role": "user", "content":
                         "Your previous draft was rejected for these reasons: " + "; ".join(problems)
                         + ". Write a new article that avoids every one of them. Return the full JSON."}]
    else:
        sys.exit("The agent could not produce a compliant article this week: " + "; ".join(errs))

    QUEUE.mkdir(exist_ok=True)
    (QUEUE / f"{a['slug']}.html").write_text(render_article(a, TODAY, stand))
    key = topic["key"] if topic else "fresh-" + TODAY.isoformat()
    items.append({"slug": a["slug"], "title": a["title"], "excerpt": a["excerpt"],
                  "date": TODAY.isoformat(), "topic_key": key, "status": "queued"})
    save_articles(items)
    OUT.mkdir(exist_ok=True)
    wc = word_count(a)
    (OUT / "pr-body.md").write_text(pr_body(a, topic["angle"] if topic else "fresh angle", wc))
    (OUT / "article-meta.json").write_text(json.dumps({"slug": a["slug"], "title": a["title"]}))
    log("Article written:", a["title"], f"({wc} words)")


def publish():
    items = load_articles()
    todo = [i for i in items if i["status"] == "queued" and (QUEUE / f"{i['slug']}.html").exists()]
    if not todo:
        log("Nothing queued to publish.")
        return
    if not env("SITE_REPO_TOKEN"):
        sys.exit("SITE_REPO_TOKEN is not set.")
    for i in todo:
        site_put(f"articles/{i['slug']}.html", (QUEUE / f"{i['slug']}.html").read_bytes(),
                 f"Article: {i['title']}")
        i["status"] = "published"
        i["published"] = dt.datetime.now(base.SAST).isoformat(timespec="minutes")
        log("Published:", i["title"])
    site_put("articles/index.html", render_index(items).encode(), "Articles: update index")
    old, _ = site_get("sitemap.xml")
    site_put("sitemap.xml", update_sitemap(old.decode() if old else "", items).encode(),
             "Articles: update sitemap")
    save_articles(items)


if __name__ == "__main__":
    {"generate": generate, "publish": publish}[sys.argv[1]]()
