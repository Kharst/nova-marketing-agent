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
import editor  # noqa: E402
import run as base  # noqa: E402  (shared helpers: env, log, llm, events, gather)

ROOT = base.ROOT
AGENT = base.AGENT
OUT = base.OUT
QUEUE = ROOT / "articles-queue"
ARTICLES = ROOT / "data" / "articles.json"
TODAY = base.TODAY
LOGO = base.LOGO
env, log = base.env, base.log

MIN_WORDS, MAX_WORDS = 450, 1300

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
- Total length 700 to 950 words (not shorter than 650). Short paragraphs, at most 70 words each. 4 or 5 sections.
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
- You are given verified_facts. Never state what a law, regulator or standard requires, defines or allows,
  and never write "compliant with" or "aligned to" a standard, unless that exact statement is listed in
  verified_facts. Text in source_material about what a standard says is NOT verified. Describe what
  Solar Intelligence checks or flags instead (for example "Solar Intelligence flags a ratio outside
  1.0 to 1.5" rather than "the standard requires 1.0 to 1.5").
- If an editor note later asks you to fix a claim and you are sure it is right, keep it and add a key
  "pushback": [{"claim": "...", "reason": "...", "quote": "exact words from the source material"}].
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
PAUSE = int(env("ARTICLE_PAUSE", "25"))     # seconds to rest between rewrites (free tier limit per minute)
WAIT_BUDGET = int(env("ARTICLE_WAIT_BUDGET", "420"))
_waited = 0


_model = None


def pick_article_model(url, hdr):
    """Long articles need a plain (non-'thinking') model; fall back to the shared pick."""
    ids = [m["id"] for m in requests.get(url + "/models", headers=hdr, timeout=30).json()["data"]]
    log("models available:", ", ".join(ids))
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


# ------------------------------------------------------------- tidy-up
def fit(text, lo, hi):
    """Trim text to at most hi characters, preferring a sentence end, then a word boundary."""
    text = " ".join(str(text).split())
    if len(text) <= hi:
        return text
    cut = text[:hi + 1]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if end >= lo - 1:
        return cut[:end + 1]
    cut = cut[:hi - 1].rsplit(" ", 1)[0].rstrip(",;:- ")
    return cut + "\u2026"


def tidy(s):
    """Remove a stray closing quote mark that the model sometimes leaves at the end of a paragraph."""
    s = s.strip()
    for op, cl in (("\u201c", "\u201d"), ('"', '"')):
        while s.endswith(cl) and s.count(cl) > s.count(op) if op != cl else (s.endswith(cl) and s.count(cl) % 2 == 1):
            s = s[:-1].rstrip()
    while s.startswith("\u201d"):
        s = s[1:].lstrip()
    return s


def normalise(a):
    """The model cannot count characters reliably, so fix lengths in code."""
    for k in ("intro", "closing"):
        if isinstance(a.get(k), str):
            a[k] = tidy(a[k])
    for sec in a.get("sections", []) if isinstance(a.get("sections"), list) else []:
        if isinstance(sec, dict):
            sec["paragraphs"] = [tidy(x) if isinstance(x, str) else x for x in sec.get("paragraphs", [])]
            sec["bullets"] = [tidy(x) if isinstance(x, str) else x for x in sec.get("bullets", [])]
    for f in a.get("faq", []) if isinstance(a.get("faq"), list) else []:
        if isinstance(f, dict):
            for k in ("q", "a"):
                if isinstance(f.get(k), str):
                    f[k] = tidy(f[k])
    t = " ".join(a["title"].split())
    if len(t) > 70:
        for sep in (": ", " \u2014 ", " - ", " | "):
            if sep in t and len(t.split(sep)[0]) >= 25:
                t = t.split(sep)[0]
                break
    a["title"] = t.rstrip(" .,:;-")      # if still over 70, validation sends it back for a shorter one
    meta = " ".join(a["meta_description"].split())
    if len(meta) < 120:
        meta = " ".join((meta + " " + a["excerpt"]).split())
    if len(meta) < 120:
        meta = " ".join((meta + " " + a["intro"]).split())
    a["meta_description"] = fit(meta, 120, 158)
    a["excerpt"] = fit(a["excerpt"], 100, 178)


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

    normalise(a)
    text = " ".join(all_text(a))
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", a["slug"]) or len(a["slug"]) > 60:
        errs.append("slug must be lowercase words joined by hyphens, max 60 characters")
    if a["slug"] in used_slugs:
        errs.append("slug already used; choose a different one")
    if len(a["title"]) > 70:
        errs.append("title max 65 characters")
    if not 120 <= len(a["meta_description"]) <= 160:
        errs.append("meta_description must be 120 to 158 characters")
    if len(a["excerpt"]) > 180:
        errs.append("excerpt max 180 characters")
    wc = word_count(a)
    if not MIN_WORDS <= wc <= MAX_WORDS:
        errs.append(f"article is {wc} words; write at least 700 words (aim for 700 to 950)")
    if re.search(r"[\[\]{}<>]|\*\*|^#", text, re.M):
        errs.append("plain text only: remove brackets, markup and markdown")
    if BANNED.search(text):
        errs.append("contains a banned word or claim (guarantees, hype, testimonials, partners, prices, "
                    "trials, internals)")
    if re.search(r"\bI(['’](m|ve|d|ll))?\b", text) or re.search(r"\b(me|my|myself|mine)\b", text, re.I):
        errs.append("company voice: never use I, me or my; write as we, our or Nova Metrics")
    if not stand and re.search(r"\bstand\b", text, re.I):
        errs.append("do not mention a stand")
    if len(re.findall(r"Solar Intelligence", text)) > 6:
        errs.append("you mention Solar Intelligence too often; use the name at most 4 times in total")
    for n in re.findall(r"\d[\d,.]*\d|\d", text):
        plain = n.replace(",", "")
        if plain.isdigit() and int(plain) <= 31:
            continue
        if n not in corpus and plain not in corpus:
            errs.append(f"number '{n}' is not in the sources; remove it")
    return errs


# ------------------------------------------------------------------ render
CSS = """
.article-wrap{max-width:740px;margin:0 auto;padding:0 24px 72px}
.article-wrap .page-hero{padding:128px 0 24px}
.article-wrap .eyebrow{font-family:var(--f-mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--amber);margin-bottom:14px}
.article-wrap .meta{font-size:13px;color:var(--text-dim);margin-top:14px}
.article-wrap strong{color:var(--white);font-weight:600}
.article-wrap .lead{font-size:18px;line-height:1.7;color:var(--white);margin:8px 0 28px}
.article-wrap h2{font-family:var(--f-display);font-weight:700;font-size:30px;line-height:1.1;color:var(--white);margin:46px 0 14px}
.article-wrap h3{font-size:16px;font-weight:600;color:var(--white);margin:24px 0 6px}
.article-wrap p{font-size:16px;line-height:1.8;color:var(--text);margin:0 0 16px}
.article-wrap ul{margin:0 0 18px;padding-left:0}
.article-wrap li{font-size:16px;line-height:1.7;color:var(--text);padding-left:18px;position:relative;margin-bottom:8px}
.article-wrap li::before{content:'\\00b7';position:absolute;left:4px;color:var(--amber);font-weight:700}
.article-wrap .box{border:1px solid var(--line-2);background:var(--panel);padding:22px 24px;margin:38px 0 0}
.article-wrap .box p{margin:0 0 14px}
.article-wrap .box .btn{margin:4px 10px 0 0}
.article-list a.item{display:block;border:1px solid var(--line);background:var(--panel);padding:22px 24px;margin-bottom:14px;text-decoration:none}
.article-list a.item:hover{border-color:var(--amber)}
.article-list .d{font-family:var(--f-mono);font-size:11px;color:var(--text-dim);margin-bottom:6px}
.article-list .t{font-family:var(--f-display);font-weight:700;font-size:26px;line-height:1.1;color:var(--white);margin:0 0 8px}
.article-list .x{font-size:14.5px;color:var(--text-dim);margin:0;line-height:1.7}
"""


def site_url():
    return env("SITE_URL", "https://www.novametricsgroup.com").rstrip("/")


def esc(s):
    return html.escape(s, quote=True)


def nice_date(d):
    return f"{d.day} {d.strftime('%B %Y')}"


NAV = [("Platform", "/products"), ("Job Portal", "/#job-portal"), ("Pricing", "/#pricing"),
       ("Articles", "/articles/"), ("About", "/about"), ("Contact", "/contact")]

MENU_JS = ("<script>(function(){var b=document.querySelector('.nav-hamburger'),m=document.querySelector('.mobile-menu');"
           "if(b&&m){document.addEventListener('click',function(e){if(m.classList.contains('open')&&!m.contains(e.target)"
           "&&e.target!==b){m.classList.remove('open');document.body.classList.remove('menu-open')}});"
           "m.addEventListener('click',function(e){if(e.target.closest('a')){m.classList.remove('open');"
           "document.body.classList.remove('menu-open')}})}})();</script>")


def top(page_title):
    """The site header, identical to the main pages: six links, Sign in, Start free trial."""
    links = "".join(f'<li><a href="{h}">{esc(t)}</a></li>' for t, h in NAV)
    return (f'<header><a href="/" class="brand"><img src="{LOGO}" alt="Nova Metrics" class="brand-mark">'
            f'<div class="brand-text"><div class="brand-name">Nova Metrics</div>'
            f'<div class="brand-sub">Solar Intelligence</div></div></a>'
            f'<button class="nav-hamburger" onclick="document.querySelector(\'.mobile-menu\').classList.toggle(\'open\');'
            f'document.body.classList.toggle(\'menu-open\')" aria-label="Menu">☰</button>'
            f'<div class="mobile-menu"><nav><ul>{links}</ul></nav>'
            f'<div class="nav-actions"><a href="/solar-intelligence" class="btn">Sign in</a>'
            f'<a href="/register" class="btn btn-solid">Start free trial</a></div></div></header>' + MENU_JS)


def foot():
    """The site footer, identical to the main pages."""
    return (f'<footer><div class="wrap"><div class="footer-grid"><div>'
            f'<a href="/" class="brand"><img src="{LOGO}" alt="Nova Metrics" class="brand-mark">'
            f'<div class="brand-text"><div class="brand-name">Nova Metrics</div></div></a>'
            f'<p class="footer-desc">Solar Intelligence: the end-to-end operations platform for South African solar installers.</p></div>'
            f'<div class="footer-col"><h5>Platform</h5><a href="/products">Solar Intelligence</a>'
            f'<a href="/#job-portal">Job Portal</a><a href="/#pricing">Pricing</a></div>'
            f'<div class="footer-col"><h5>Company</h5><a href="/about">About</a><a href="/faq">FAQ</a>'
            f'<a href="/articles/">Articles</a><a href="/partner-apply">Partners</a><a href="/contact">Contact</a></div>'
            f'<div class="footer-col"><h5>Contact</h5><a href="mailto:info@novametricsgroup.com">info@novametricsgroup.com</a>'
            f'<a href="tel:+27677167716">+27 67 716 7716</a></div></div>'
            f'<div class="footer-bottom"><span>© 2026 Nova Metrics. All rights reserved. '
            f'<a href="/privacy">Privacy policy</a> · <a href="/terms">Terms of service</a></span>'
            f'<span>Nova Metrics (Pty) Ltd, South Africa</span></div></div></footer>')


def event_block(stand):
    for e in base.events():
        if 0 <= e["days_to_event"] <= 30 and stand:
            start, end = dt.date.fromisoformat(e["start"]), dt.date.fromisoformat(e["end"])
            when = (f"{start.day}–{end.day} {end.strftime('%B %Y')}"
                    if start.month == end.month else f"{nice_date(start)} to {nice_date(end)}")
            return (f'<div class="box"><p><strong>Visiting {esc(e["name"])}?</strong> '
                    f'We are at stand {esc(stand)}, {esc(when)}. Come and see how Solar Intelligence '
                    f'works on a real project.</p>'
                    f'<a class="btn btn-solid" href="{site_url()}/capetown-2026">Book a short demo</a></div>')
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
    body.append('<div><h2>Common questions</h2>')
    for f in a["faq"]:
        body.append(f'<h3>{esc(f["q"])}</h3><p>{esc(f["a"])}</p>')
    body.append("</div>")
    cta = (f'<div class="box"><p><strong style="color:var(--white)">{esc(a["closing"])}</strong></p>'
           f'<a class="btn btn-solid" href="{site_url()}/solar-intelligence">See Solar Intelligence</a>'
           f'<a class="btn" href="{site_url()}/contact">Talk to us</a></div>')
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
<link rel="stylesheet" href="/style.css?v=5">
<style>{CSS}</style>
<script type="application/ld+json">{ld_json}</script>
</head>
<body>
{top(a["title"])}
<article class="article-wrap">
<div class="page-hero">
<div class="eyebrow">Nova Metrics &middot; Insights</div>
<h1>{esc(a["title"])}</h1>
<div class="meta">By Nova Metrics &middot; {nice_date(date)} &middot; {mins} min read</div>
</div>
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
<link rel="stylesheet" href="/style.css?v=5">
<style>{CSS}</style>
</head>
<body>
{top("Articles")}
<main class="article-wrap article-list">
<div class="page-hero">
<div class="eyebrow">Nova Metrics &middot; Insights</div>
<h1>Articles for South African <span class="accent">solar installers</span></h1>
<p>{esc(desc)}</p>
</div>
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
    ctx = {"today": TODAY.isoformat(), "verified_facts": editor.ledger_lines(),
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


def pr_body(a, topic_label, wc, open_claims=None, claims=None, pushback=None, note=""):
    lines = [f"## {a['title']}", "",
             f"*Topic:* {topic_label}  \n*Length:* about {wc} words  \n*Will appear at:* "
             f"`{site_url()}/articles/{a['slug']}`", "",
             "**To publish: press Merge pull request. To skip: close it.** Nothing goes on the website "
             "until you merge.", ""]
    if open_claims or note:
        lines[2:2] = ["> **NEEDS YOUR DECISION.** The writer and the editor could not settle the points "
                      "below. Do not merge until you have checked them.", "",
                      (note + "\n" if note else "") + editor.dispute_markdown(open_claims or [], pushback), ""]
    elif claims:
        checked = [c for c in claims if c["status"] in editor.OK]
        lines += ["**Editor check passed.** " + f"{len(checked)} claims checked and backed by the verified "
                  "list, the product facts or an official source.", ""]
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
    reviews, open_claims, last_claims, note = 0, [], [], ""
    corpus += json.dumps(editor.ledger_lines())
    for _ in range(8):
        a = ask(msgs)
        errs = validate(a, corpus, stand, used)
        text = "\n".join(all_text(a)) if not errs else ""
        if not errs:
            errs = editor.never_hits(text)
        if errs:
            log("rejected:", errs)
            time.sleep(PAUSE)
            # Keep requests small: send the list of problems, not the whole failed draft.
            problems = (problems + errs)[-8:]
            msgs = first + [{"role": "user", "content":
                             "Your previous draft was rejected for these reasons: " + "; ".join(problems)
                             + ". Write a new article that avoids every one of them. Return the full JSON."}]
            continue
        reviews += 1
        time.sleep(PAUSE)
        rev = editor.review(text, source_text, a.get("pushback"), kind="article")
        if rev["unavailable"]:
            note = "The editor could not be reached, so the claims in this article were NOT checked."
            open_claims = []
            break
        last_claims, open_claims = rev["claims"], rev["open"]
        if rev["ok"]:
            break
        log("editor open claims:", [c["text"] for c in open_claims])
        if reviews >= 3:
            break
        msgs = first + [{"role": "user", "content": editor.feedback(open_claims)
                         + (" Also avoid: " + "; ".join(problems) if problems else "")}]
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
    (OUT / "pr-body.md").write_text(pr_body(a, topic["angle"] if topic else "fresh angle", wc,
                                            open_claims, last_claims, a.get("pushback"), note))
    flag = " (needs your decision)" if (open_claims or note) else ""
    (OUT / "article-meta.json").write_text(json.dumps({"slug": a["slug"], "title": a["title"] + flag}))
    log("Article written:", a["title"], f"({wc} words)")


HEADER_RE = re.compile(r"<header>.*?</header>\s*<script>.*?</script>", re.S)
FOOTER_RE = re.compile(r"<footer>.*?</footer>", re.S)
OLD_ARTICLE_RE = re.compile(r'<article class="wrap">(.*?)</article>', re.S)


def modernise(page):
    """Articles published before the site design was shared used their own navy and gold page.
    Rebuild them in the site design, keeping the article text, so every article looks the same."""
    if "<header>" in page or 'class="topbar"' not in page:
        return page
    m = OLD_ARTICLE_RE.search(page)
    if not m:
        return page
    inner = m.group(1)
    hero = re.match(r'\s*(<div class="eyebrow">.*?</div>\s*<h1>.*?</h1>\s*<div class="meta">.*?</div>)\s*', inner, re.S)
    if not hero:
        return page
    rest = inner[hero.end():]
    rest = rest.replace('<div class="faq">', "<div>")
    rest = rest.replace('<div class="event">', '<div class="box">').replace('<div class="cta">', '<div class="box">')
    rest = rest.replace('class="btn alt"', 'class="btn__sec"').replace('class="btn"', 'class="btn btn-solid"')
    rest = rest.replace('class="btn__sec"', 'class="btn"')
    rest = rest.replace('<a class="btn" href="https://www.novametricsgroup.com/contact">', '<a class="btn" href="/contact">')
    rest = re.sub(r'(?<=[.!?])\u201d</p>', "</p>", rest)
    rest = re.sub(r"\bSP (\d)", r"SP\1", rest)
    head = page[:page.index("<style>")]
    head = re.sub(r'<link rel="preconnect".*?rel="stylesheet">\s*', "", head, flags=re.S)
    tail_head = page[page.index("</style>") + len("</style>"):page.index("</head>")]
    return (head + '<link rel="stylesheet" href="/style.css?v=5">\n<style>' + CSS + "</style>" + tail_head
            + "</head>\n<body>\n" + top("") + '\n<article class="article-wrap">\n<div class="page-hero">\n'
            + hero.group(1) + "\n</div>\n" + rest.strip() + "\n</article>\n" + foot() + "\n</body>\n</html>\n")


def refresh_chrome(page):
    """Give an already-written article the current header and footer, so site-wide menu changes reach old articles."""
    page = modernise(page)
    page = HEADER_RE.sub(lambda m: top(""), page, count=1)
    return FOOTER_RE.sub(lambda m: foot(), page, count=1)


def put_if_changed(path, data, message):
    old, _ = site_get(path)
    if old == data:
        return False
    site_put(path, data, message)
    return True


def publish():
    items = load_articles()
    todo = [i for i in items if i["status"] == "queued" and (QUEUE / f"{i['slug']}.html").exists()]
    if not env("SITE_REPO_TOKEN"):
        sys.exit("SITE_REPO_TOKEN is not set.")
    for i in todo:
        site_put(f"articles/{i['slug']}.html", refresh_chrome((QUEUE / f"{i['slug']}.html").read_text()).encode(),
                 f"Article: {i['title']}")
        i["status"] = "published"
        i["published"] = dt.datetime.now(base.SAST).isoformat(timespec="minutes")
        log("Published:", i["title"])
    for i in items:     # older articles: bring their header and footer up to date
        f = QUEUE / f"{i['slug']}.html"
        if i["status"] == "published" and i not in todo and f.exists():
            if put_if_changed(f"articles/{i['slug']}.html", refresh_chrome(f.read_text()).encode(),
                              f"Article: refresh menu and footer ({i['slug']})"):
                log("Refreshed menu and footer:", i["slug"])
    put_if_changed("articles/index.html", render_index(items).encode(), "Articles: update index")
    feed = [{"slug": i["slug"], "title": i["title"], "excerpt": i["excerpt"], "date": i["date"]}
            for i in sorted((x for x in items if x["status"] == "published"),
                            key=lambda x: x["date"], reverse=True)]
    put_if_changed("articles/articles.json", json.dumps(feed, indent=2, ensure_ascii=False).encode(),
                   "Articles: update feed for the homepage")
    old, _ = site_get("sitemap.xml")
    put_if_changed("sitemap.xml", update_sitemap(old.decode() if old else "", items).encode(),
                   "Articles: update sitemap")
    save_articles(items)


if __name__ == "__main__":
    {"generate": generate, "publish": publish}[sys.argv[1]]()
