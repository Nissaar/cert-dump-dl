"""
Interactive HTML generator — a self-contained single-page study app.

All questions are embedded as JSON and rendered client-side one at a time,
which keeps the page fast with 1000+ questions and avoids HTML-escaping bugs.
Progress (answers, flags, position, filters, mock exams) is saved in
localStorage, keyed by exam code, so it survives closing the browser and
regenerating the file (questions are keyed by a stable content hash).
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from classify import UNCLASSIFIED, answer_letters

_CHOOSE_N = {"two": 2, "three": 3, "four": 4, "five": 5}


def generate_html(questions: list[dict], output_path: Path, theme: str = "dark",
                  exam_code: str = "", provider: str = ""):
    """Generate the interactive HTML study app."""
    title = (exam_code or _title_from_questions(questions)).upper()
    payload = _build_payload(questions, title, exam_code, provider)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (
        HTML_TEMPLATE
        .replace("__TITLE__", _esc(title))
        .replace("__THEME__", "light" if theme == "light" else "dark")
        .replace("__DATA__", data)
    )
    output_path.write_text(html, encoding="utf-8")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _title_from_questions(questions: list[dict]) -> str:
    for q in questions[:5]:
        m = re.search(r"exam\s+([\w]+-[\w]+)", q.get("title", ""), re.IGNORECASE)
        if m:
            return m.group(1)
    return "Exam Questions"


def _required_count(content: str, key_len: int) -> int:
    m = re.search(r"\(\s*choose\s+(two|three|four|five|\d)\s*\.?\s*\)", content, re.IGNORECASE) \
        or re.search(r"\bchoose\s+(two|three|four|five)\b", content, re.IGNORECASE)
    if m:
        w = m.group(1).lower()
        return _CHOOSE_N.get(w) or int(w)
    return max(1, key_len)


def _order_comments(comments: list[dict]) -> list[dict]:
    """Threads: top-level by (highly voted, upvotes), each followed by its replies."""
    tops, replies = [], {}
    for c in comments:
        pid = c.get("parent_id") or ""
        if pid:
            replies.setdefault(pid, []).append(c)
        else:
            tops.append(c)
    tops.sort(key=lambda c: (c.get("badge") != "highly_voted", -(c.get("upvotes") or 0)))
    out = []

    def add(c):
        out.append(c)
        for r in replies.get(c.get("id") or "\0", []):
            add(r)

    for c in tops:
        add(c)
    return out


def _build_payload(questions: list[dict], title: str, exam_code: str, provider: str) -> dict:
    images: list[str] = []
    img_index: dict[str, int] = {}

    def img(b64: str | None) -> int | None:
        if not b64:
            return None
        if b64 not in img_index:
            img_index[b64] = len(images)
            images.append(b64)
        return img_index[b64]

    qs = []
    domains, topics = {}, {}
    for i, q in enumerate(questions):
        content = q.get("content") or ""
        official = answer_letters(q.get("answer") or "")
        voted = answer_letters(q.get("voted_answer") or "")
        votes = []
        for v in q.get("vote_data") or []:
            letters = "".join(answer_letters(str(v.get("voted_answers", ""))))
            if letters:
                votes.append([letters, int(v.get("vote_count") or 0)])
        votes.sort(key=lambda x: -x[1])

        comments = []
        for c in _order_comments(q.get("comments") or []):
            comments.append([
                c.get("author") or "Anonymous",
                c.get("date") or "",
                c.get("text") or "",
                int(c.get("upvotes") or 0),
                1 if c.get("badge") == "highly_voted" else 0,
                c.get("selected_answer") or "",
                int(c.get("depth") or 0),
            ])

        choices = q.get("choices") or []
        d = q.get("domain") or ""
        tags = q.get("topic_tags") or []
        if d:
            domains[d] = domains.get(d, 0) + 1
        for t in tags:
            topics[t] = topics.get(t, 0) + 1

        qs.append({
            "u": q.get("uid") or str(i),
            "n": i + 1,
            "qn": q.get("question_number") or 0,
            "tp": q.get("topic") or 0,
            "h": q.get("header") or "",
            "c": content,
            "ch": [[c.get("letter", ""), c.get("text", ""), img(c.get("image"))] for c in choices],
            "im": [x for x in (img(m.get("base64")) for m in q.get("images") or []) if x is not None],
            "o": "".join(official),
            "or": "" if official else (q.get("answer") or ""),
            "v": "".join(voted),
            "vd": votes,
            "k": _required_count(content, len(voted or official)) if choices else 0,
            "d": d,
            "tg": tags,
            "l": q.get("question_link") or "",
            "cm": comments,
        })

    domain_list = sorted(domains, key=lambda d: (d == UNCLASSIFIED, d))
    topic_list = sorted(topics, key=lambda t: (t == "General", -topics[t], t))
    return {
        "meta": {
            "title": title,
            "exam": exam_code or title.lower(),
            "provider": provider,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "domains": domain_list,
            "topics": topic_list,
        },
        "img": images,
        "q": qs,
    }


HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en" data-theme="__THEME__">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__ · Exam Studio</title>
<style>
:root {
  --bg: #f5f6f8; --surface: #ffffff; --surface-2: #f0f2f5; --surface-3: #e7eaef;
  --border: #dfe3ea; --border-strong: #c6ccd6;
  --text: #1a1e26; --text-2: #4a5261; --muted: #6b7382;
  --accent: #3b5bdb; --accent-weak: rgba(59,91,219,.10); --accent-text: #2f4bc0; --on-accent: #fff;
  --good: #0ca30c; --good-text: #067306; --good-weak: rgba(12,163,12,.10);
  --bad: #d03b3b; --bad-text: #b02a2a; --bad-weak: rgba(208,59,59,.09);
  --warn: #fab219; --warn-text: #8a5a00; --warn-weak: rgba(250,178,25,.16);
  --track: #e3e6ec;
  --shadow: 0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.06);
  --shadow-lg: 0 12px 32px rgba(16,24,40,.18);
  --radius: 12px;
  color-scheme: light;
}
:root[data-theme="dark"] {
  --bg: #0e1116; --surface: #161a21; --surface-2: #1c212a; --surface-3: #242a35;
  --border: #2a303b; --border-strong: #3a4250;
  --text: #e7eaf0; --text-2: #b7bfcc; --muted: #8b94a3;
  --accent: #7c93ff; --accent-weak: rgba(124,147,255,.14); --accent-text: #a3b3ff; --on-accent: #0e1116;
  --good: #0ca30c; --good-text: #4cd34c; --good-weak: rgba(12,163,12,.16);
  --bad: #d03b3b; --bad-text: #ff7b7b; --bad-weak: rgba(208,59,59,.16);
  --warn: #fab219; --warn-text: #fac55a; --warn-weak: rgba(250,178,25,.14);
  --track: #262c37;
  --shadow: 0 1px 2px rgba(0,0,0,.3);
  --shadow-lg: 0 16px 40px rgba(0,0,0,.5);
  color-scheme: dark;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  background: var(--bg); color: var(--text);
  -webkit-font-smoothing: antialiased;
}
button, input, select { font: inherit; color: inherit; }
button { cursor: pointer; }
a { color: var(--accent-text); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.hidden { display: none !important; }
.muted { color: var(--muted); }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

/* ── Top bar ── */
.topbar {
  position: sticky; top: 0; z-index: 50;
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  backdrop-filter: saturate(1.4) blur(8px);
  border-bottom: 1px solid var(--border);
}
.topbar-in { display: flex; align-items: center; gap: 16px; padding: 10px 20px; }
.brand { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.brand b { font-size: 17px; letter-spacing: -.01em; white-space: nowrap; }
.brand span { color: var(--muted); font-size: 13px; white-space: nowrap; }
.tabs { display: flex; gap: 2px; background: var(--surface-2); border-radius: 10px; padding: 3px; }
.tab { border: 0; background: transparent; padding: 6px 14px; border-radius: 8px; color: var(--text-2); font-weight: 550; font-size: 14px; }
.tab[aria-selected="true"] { background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
.spacer { flex: 1; }
.progress-mini { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text-2); }
.progress-mini .bar { width: 160px; }
.iconbtn {
  border: 1px solid var(--border); background: var(--surface); border-radius: 9px;
  height: 34px; min-width: 34px; padding: 0 10px; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  color: var(--text-2); font-size: 14px;
}
.iconbtn:hover { border-color: var(--border-strong); color: var(--text); }
.timer { font-variant-numeric: tabular-nums; font-weight: 650; padding: 4px 10px; border-radius: 8px; background: var(--accent-weak); color: var(--accent-text); }
.timer.low { background: var(--bad-weak); color: var(--bad-text); }

/* ── Stacked progress bar (correct / wrong / revealed / remaining) ── */
.bar { display: flex; gap: 2px; height: 8px; border-radius: 4px; overflow: hidden; background: var(--track); }
.bar > i { display: block; height: 100%; }
.bar > i:first-child { border-radius: 4px 0 0 4px; }
.bar .g { background: var(--good); } .bar .r { background: var(--bad); } .bar .y { background: var(--warn); }
.bar.thick { height: 12px; border-radius: 6px; }

/* ── Layout ── */
.layout { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 0; min-height: calc(100vh - 56px); }
.sidebar {
  position: sticky; top: 56px; align-self: start; height: calc(100vh - 56px); overflow-y: auto;
  border-right: 1px solid var(--border); background: var(--surface); padding: 16px 16px 40px;
}
.main { padding: 20px 28px 80px; min-width: 0; }
.wrap { max-width: 860px; margin: 0 auto; }

/* ── Sidebar filters ── */
.fgroup { margin-bottom: 18px; }
.fgroup h4 { margin: 0 0 8px; font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); font-weight: 650; display: flex; justify-content: space-between; align-items: center; }
.fgroup h4 button { border: 0; background: none; color: var(--accent-text); font-size: 11.5px; text-transform: none; letter-spacing: 0; padding: 0; }
.search { width: 100%; padding: 8px 12px; border-radius: 9px; border: 1px solid var(--border); background: var(--surface-2); }
.search:focus { outline: none; border-color: var(--accent); background: var(--surface); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  border: 1px solid var(--border); background: var(--surface); border-radius: 999px;
  padding: 4px 10px; font-size: 13px; color: var(--text-2); display: inline-flex; gap: 6px; align-items: center;
}
.chip small { color: var(--muted); font-size: 11.5px; font-variant-numeric: tabular-nums; }
.chip:hover { border-color: var(--border-strong); color: var(--text); }
.chip[aria-pressed="true"] { background: var(--accent-weak); border-color: var(--accent); color: var(--accent-text); }
.chip[aria-pressed="true"] small { color: var(--accent-text); }
.dlist { display: flex; flex-direction: column; gap: 4px; }
.drow {
  display: grid; grid-template-columns: 18px 1fr auto; gap: 8px; align-items: center; text-align: left;
  border: 1px solid transparent; background: none; border-radius: 8px; padding: 6px 8px; font-size: 13.5px; color: var(--text-2);
}
.drow:hover { background: var(--surface-2); }
.drow[aria-pressed="true"] { background: var(--accent-weak); color: var(--text); border-color: color-mix(in srgb, var(--accent) 40%, transparent); }
.drow .box { width: 16px; height: 16px; border-radius: 4px; border: 1.5px solid var(--border-strong); display: grid; place-items: center; font-size: 11px; line-height: 1; }
.drow[aria-pressed="true"] .box { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.drow .bar { grid-column: 2 / 4; height: 4px; }
.drow small { color: var(--muted); font-variant-numeric: tabular-nums; }
.toggle { display: flex; align-items: center; gap: 10px; font-size: 13.5px; color: var(--text-2); cursor: pointer; padding: 4px 0; }
.toggle input { width: 16px; height: 16px; accent-color: var(--accent); }
.match-count { font-size: 13px; color: var(--muted); padding: 10px 12px; background: var(--surface-2); border-radius: 9px; margin-bottom: 16px; }
.match-count b { color: var(--text); }
.special { display: flex; align-items: center; justify-content: space-between; gap: 8px; background: var(--warn-weak); border-radius: 9px; padding: 8px 10px; font-size: 13px; margin-bottom: 14px; }
.special button { border: 0; background: none; color: var(--text-2); font-size: 16px; line-height: 1; }

/* ── Practice toolbar ── */
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 14px; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 9px; overflow: hidden; background: var(--surface); }
.seg button { border: 0; background: none; padding: 6px 12px; font-size: 13.5px; color: var(--text-2); }
.seg button + button { border-left: 1px solid var(--border); }
.seg button[aria-pressed="true"] { background: var(--accent-weak); color: var(--accent-text); font-weight: 600; }
.pos { font-size: 13.5px; color: var(--text-2); font-variant-numeric: tabular-nums; }
.pos input { width: 64px; padding: 5px 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); text-align: center; }

/* ── Question card ── */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); }
.qcard { padding: 22px 26px 24px; }
.qmeta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 14px; }
.qnum { font-weight: 700; font-size: 15px; margin-right: 4px; }
.pill { font-size: 12px; padding: 2px 9px; border-radius: 999px; background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); white-space: nowrap; }
.pill.dom { background: var(--accent-weak); color: var(--accent-text); border-color: transparent; }
.pill.st-ok { background: var(--good-weak); color: var(--good-text); border-color: transparent; }
.pill.st-bad { background: var(--bad-weak); color: var(--bad-text); border-color: transparent; }
.pill.st-seen { background: var(--warn-weak); color: var(--warn-text); border-color: transparent; }
.qmeta .right { margin-left: auto; display: flex; gap: 6px; align-items: center; }
.flagbtn[aria-pressed="true"] { color: var(--warn-text); border-color: var(--warn); background: var(--warn-weak); }
.qheader { font-style: italic; color: var(--text-2); margin-bottom: 8px; font-size: 14px; }
.stem { font-size: 16px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.stem strong { font-weight: 700; color: var(--text); background: var(--warn-weak); padding: 0 3px; border-radius: 3px; }
.qimgs img, .ctext img { max-width: 100%; height: auto; border-radius: 8px; border: 1px solid var(--border); margin-top: 12px; cursor: zoom-in; background: #fff; }
.need { margin: 18px 0 8px; font-size: 13px; color: var(--text-2); display: flex; gap: 8px; align-items: center; }
.need b { color: var(--accent-text); }
.choices { display: flex; flex-direction: column; gap: 8px; margin-top: 18px; }
.need + .choices { margin-top: 0; }
.choice {
  display: grid; grid-template-columns: 30px 1fr auto; gap: 12px; align-items: start; text-align: left;
  width: 100%; padding: 12px 14px; border-radius: 10px; border: 1.5px solid var(--border); background: var(--surface);
  font-size: 15px; line-height: 1.55; transition: border-color .12s, background .12s;
}
.choice:hover:not([disabled]) { border-color: var(--border-strong); background: var(--surface-2); }
.choice .letter {
  width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; font-weight: 700; font-size: 13.5px;
  background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border);
}
.choice.multi .letter { border-radius: 6px; }
.choice.single .letter { border-radius: 50%; }
.choice .ctext { white-space: pre-wrap; overflow-wrap: anywhere; padding-top: 3px; }
.choice .tag { font-size: 12px; font-weight: 650; padding: 3px 0 0; white-space: nowrap; }
.choice[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-weak); }
.choice[aria-pressed="true"] .letter { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
.choice[disabled] { cursor: default; }
.choice.is-correct { border-color: var(--good); background: var(--good-weak); }
.choice.is-correct .letter { background: var(--good); color: #fff; border-color: var(--good); }
.choice.is-correct .tag { color: var(--good-text); }
.choice.is-wrong { border-color: var(--bad); background: var(--bad-weak); }
.choice.is-wrong .letter { background: var(--bad); color: #fff; border-color: var(--bad); }
.choice.is-wrong .tag { color: var(--bad-text); }
.choice.is-missed { border-style: dashed; border-color: var(--good); background: transparent; }
.choice.is-missed .letter { color: var(--good-text); border-color: var(--good); background: transparent; }
.choice.is-missed .tag { color: var(--good-text); }
.choice.dim { opacity: .62; }

.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 18px; }
.btn {
  border: 1px solid var(--border); background: var(--surface); border-radius: 9px; padding: 8px 14px;
  font-size: 14px; font-weight: 550; color: var(--text); display: inline-flex; align-items: center; gap: 6px;
}
.btn:hover:not([disabled]) { border-color: var(--border-strong); background: var(--surface-2); }
.btn[disabled] { opacity: .45; cursor: not-allowed; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.btn.primary:hover:not([disabled]) { background: var(--accent); filter: brightness(1.08); }
.btn.ghost { border-color: transparent; background: transparent; color: var(--text-2); }
.btn.ghost:hover:not([disabled]) { background: var(--surface-2); }
.btn.danger { color: var(--bad-text); }
.btn.good { color: var(--good-text); border-color: var(--good); }
.btn.bad { color: var(--bad-text); border-color: var(--bad); }
.kbd { font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; border: 1px solid var(--border); border-bottom-width: 2px; border-radius: 4px; padding: 0 5px; color: var(--muted); background: var(--surface-2); }
.btn .kbd { margin-left: 2px; }
.btn.primary .kbd { color: inherit; border-color: color-mix(in srgb, var(--on-accent) 35%, transparent); background: transparent; }

/* ── Feedback ── */
.feedback { margin-top: 18px; border-radius: 10px; padding: 14px 16px; border: 1px solid var(--border); background: var(--surface-2); }
.feedback.ok { border-color: color-mix(in srgb, var(--good) 45%, transparent); background: var(--good-weak); }
.feedback.bad { border-color: color-mix(in srgb, var(--bad) 45%, transparent); background: var(--bad-weak); }
.fb-title { font-weight: 700; font-size: 15.5px; display: flex; align-items: center; gap: 8px; }
.feedback.ok .fb-title { color: var(--good-text); }
.feedback.bad .fb-title { color: var(--bad-text); }
.fb-lines { margin-top: 6px; font-size: 14px; color: var(--text-2); display: flex; flex-wrap: wrap; gap: 4px 18px; }
.fb-lines b { color: var(--text); }
.fb-note { margin-top: 8px; font-size: 13px; color: var(--warn-text); }
.votes { margin-top: 12px; display: grid; grid-template-columns: auto 1fr auto; gap: 6px 10px; align-items: center; font-size: 13px; }
.votes .vl { font-weight: 650; font-variant-numeric: tabular-nums; }
.votes .vt { height: 8px; background: var(--track); border-radius: 4px; overflow: hidden; }
.votes .vt i { display: block; height: 100%; background: var(--accent); border-radius: 0 4px 4px 0; }
.votes .vn { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.votes-h { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-top: 14px; font-weight: 650; }

/* ── Discussion ── */
.disc { margin-top: 16px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.disc > summary { list-style: none; cursor: pointer; padding: 10px 14px; font-size: 14px; font-weight: 600; color: var(--text-2); display: flex; align-items: center; gap: 8px; background: var(--surface-2); }
.disc > summary::-webkit-details-marker { display: none; }
.disc > summary::before { content: "▸"; transition: transform .15s; display: inline-block; }
.disc[open] > summary::before { transform: rotate(90deg); }
.disc.empty > summary { cursor: default; font-weight: 500; color: var(--muted); }
.disc.empty > summary::before { content: ""; }
.cmts { max-height: 560px; overflow-y: auto; }
.cmt { padding: 12px 14px; border-top: 1px solid var(--border); font-size: 14px; }
.cmt.reply { border-left: 2px solid var(--border-strong); background: color-mix(in srgb, var(--surface-2) 50%, transparent); }
.cmt-h { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; margin-bottom: 4px; font-size: 12.5px; }
.cmt-h .au { font-weight: 650; color: var(--text); font-size: 13px; }
.cmt-h .dt { color: var(--muted); }
.cmt-h .up { color: var(--text-2); font-variant-numeric: tabular-nums; }
.badge { font-size: 11px; font-weight: 650; padding: 1px 7px; border-radius: 999px; }
.badge.hv { background: var(--accent-weak); color: var(--accent-text); }
.badge.sel { background: var(--surface-3); color: var(--text-2); }
.badge.sel.ok { background: var(--good-weak); color: var(--good-text); }
.badge.sel.no { background: var(--bad-weak); color: var(--bad-text); }
.cmt-b { color: var(--text-2); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.55; }
.more { display: block; width: 100%; border: 0; border-top: 1px solid var(--border); background: var(--surface-2); padding: 10px; font-size: 13.5px; color: var(--accent-text); font-weight: 600; }

.navrow { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-top: 16px; }
.hint { font-size: 12.5px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 18px; justify-content: center; }
.empty-state { text-align: center; padding: 60px 20px; color: var(--text-2); }
.empty-state h3 { margin: 0 0 6px; color: var(--text); }

/* ── Map view ── */
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; color: var(--text-2); margin-bottom: 14px; align-items: center; }
.legend i { display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(44px, 1fr)); gap: 5px; }
.cell {
  height: 34px; border-radius: 7px; border: 1px solid var(--border); background: var(--surface);
  font-size: 12px; font-variant-numeric: tabular-nums; color: var(--text-2); position: relative; padding: 0;
}
.cell:hover { border-color: var(--border-strong); }
.cell.ok { background: var(--good); border-color: var(--good); color: #fff; }
.cell.bad { background: var(--bad); border-color: var(--bad); color: #fff; }
.cell.seen { background: var(--warn); border-color: var(--warn); color: #3a2800; }
.cell.ans { background: var(--accent-weak); border-color: var(--accent); color: var(--accent-text); }
.cell.cur { outline: 2px solid var(--text); outline-offset: 1px; }
.cell.fl::after { content: ""; position: absolute; top: 3px; right: 3px; width: 6px; height: 6px; border-radius: 50%; background: var(--warn); box-shadow: 0 0 0 2px var(--surface); }

/* ── Stats view ── */
.h2 { font-size: 20px; font-weight: 700; margin: 0 0 4px; letter-spacing: -.01em; }
.sub { color: var(--muted); font-size: 13.5px; margin: 0 0 18px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; }
.kpi { padding: 14px 16px; }
.kpi .lbl { font-size: 12.5px; color: var(--muted); }
.kpi .val { font-size: 26px; font-weight: 700; letter-spacing: -.02em; font-variant-numeric: tabular-nums; margin-top: 2px; }
.kpi .val small { font-size: 14px; color: var(--muted); font-weight: 500; }
.panel { padding: 18px 20px; margin-bottom: 16px; }
.panel h3 { margin: 0 0 4px; font-size: 15.5px; }
.panel .sub { margin-bottom: 14px; }
.brow { display: grid; grid-template-columns: minmax(120px, 240px) 1fr 150px; gap: 14px; align-items: center; padding: 7px 8px; border-radius: 8px; cursor: pointer; border: 0; background: none; width: 100%; text-align: left; font-size: 14px; }
.brow:hover { background: var(--surface-2); }
.brow .nm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.brow .nums { font-size: 12.5px; color: var(--text-2); font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.brow .nums b { color: var(--text); }
.stat-legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12.5px; color: var(--text-2); margin-bottom: 8px; }
.stat-legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
.actions-row { display: flex; flex-wrap: wrap; gap: 8px; }
.wrow { display: grid; grid-template-columns: minmax(120px, 220px) 1fr auto; gap: 4px 14px; align-items: center; padding: 10px 8px; border-bottom: 1px solid var(--border); font-size: 14px; }
.wrow:last-child { border-bottom: 0; }
.wrow .nums { font-size: 13px; color: var(--text-2); font-variant-numeric: tabular-nums; }
.wrow .bar { grid-column: 1 / -1; height: 6px; }
.btn.sm { padding: 5px 10px; font-size: 13px; }
table.tbl { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.tbl th, .tbl td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
.tbl th { font-size: 12px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }

/* ── Mock exam ── */
.mockbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.result-hero { text-align: center; padding: 28px 20px; }
.result-hero .score { font-size: 54px; font-weight: 800; letter-spacing: -.03em; line-height: 1; }
.result-hero .verdict { margin-top: 8px; font-weight: 650; }
.result-hero .verdict.ok { color: var(--good-text); } .result-hero .verdict.bad { color: var(--bad-text); }

/* ── Modal / toast / lightbox ── */
.modal-bg { position: fixed; inset: 0; background: rgba(8,10,14,.55); z-index: 100; display: grid; place-items: center; padding: 16px; }
.modal { width: min(520px, 100%); max-height: calc(100vh - 32px); overflow-y: auto; padding: 22px 24px; box-shadow: var(--shadow-lg); }
.modal h3 { margin: 0 0 4px; font-size: 18px; }
.modal .row { display: flex; flex-direction: column; gap: 6px; margin: 14px 0; font-size: 14px; }
.modal .row label { font-weight: 600; font-size: 13px; color: var(--text-2); }
.modal input[type=number], .modal select { padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface-2); }
.modal .foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
.keys { display: grid; grid-template-columns: auto 1fr; gap: 8px 14px; font-size: 14px; align-items: center; }
.toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: var(--text); color: var(--bg); padding: 10px 16px; border-radius: 10px; font-size: 14px; z-index: 200; box-shadow: var(--shadow-lg); max-width: calc(100vw - 32px); }
.lightbox { position: fixed; inset: 0; background: rgba(0,0,0,.85); z-index: 150; display: grid; place-items: center; padding: 16px; cursor: zoom-out; }
.lightbox img { max-width: 100%; max-height: 100%; background: #fff; border-radius: 8px; }

.drawer-btn, .drawer-close { display: none; }
.drawer-close { width: 100%; justify-content: center; margin-bottom: 10px; }
@media (max-width: 1100px) {
  .progress-mini .bar { width: 100px; }
}
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .sidebar { position: fixed; top: 0; left: 0; bottom: 0; width: min(320px, 88vw); height: 100vh; z-index: 90; transform: translateX(-100%); transition: transform .2s; box-shadow: var(--shadow-lg); }
  body.drawer-open .sidebar { transform: none; }
  body.drawer-open::after { content: ""; position: fixed; inset: 0; background: rgba(8,10,14,.45); z-index: 80; }
  .drawer-btn, .drawer-close { display: inline-flex; }
  .main { padding: 16px 16px 80px; }
  .progress-mini { display: none; }
  .topbar-in { padding: 8px 16px; gap: 10px; flex-wrap: wrap; }
  .brand span { display: none; }
}
@media (max-width: 560px) {
  .qcard { padding: 16px; }
  .stem { font-size: 15.5px; }
  .choice { grid-template-columns: 26px 1fr; padding: 10px 12px; }
  .choice .tag { grid-column: 2; padding: 0; }
  .brow { grid-template-columns: 1fr; gap: 6px; }
  .brow .nums { text-align: left; }
  .wrow { grid-template-columns: 1fr; }
  .tabs { order: 5; width: 100%; }
  .tab { flex: 1; }
  .hint { display: none; }
}
</style>
</head>
<body>

<header class="topbar">
  <div class="topbar-in">
    <button class="iconbtn drawer-btn" id="drawerBtn" aria-label="Filters">☰ Filters</button>
    <div class="brand"><b>__TITLE__</b><span>Exam Studio</span></div>
    <nav class="tabs" role="tablist" id="tabs">
      <button class="tab" role="tab" data-view="practice">Practice</button>
      <button class="tab" role="tab" data-view="map">Map</button>
      <button class="tab" role="tab" data-view="stats">Progress</button>
      <button class="tab" role="tab" data-view="mock">Mock</button>
    </nav>
    <div class="spacer"></div>
    <div class="progress-mini" id="miniProgress"></div>
    <span class="timer hidden" id="timer"></span>
    <button class="iconbtn" id="themeBtn" title="Toggle theme (T)" aria-label="Toggle theme">◐</button>
    <button class="iconbtn" id="settingsBtn" title="Settings" aria-label="Settings">⚙</button>
    <button class="iconbtn" id="helpBtn" title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts">?</button>
  </div>
</header>

<div class="layout">
  <aside class="sidebar" id="sidebar"></aside>
  <main class="main"><div class="wrap" id="view"></div></main>
</div>

<div id="overlay"></div>

<script id="exam-data" type="application/json">__DATA__</script>
<script>
(function () {
"use strict";

// ═════════════ Data ═════════════
const DATA = JSON.parse(document.getElementById("exam-data").textContent);
const META = DATA.meta, IMG = DATA.img, Q = DATA.q;
const BY_UID = new Map();
Q.forEach((q, i) => {
  q.ix = i;
  q.s = (q.c + " " + q.ch.map(c => c[1]).join(" ") + " #" + q.n).toLowerCase();
  BY_UID.set(q.u, q);
});
const HAS_CHOICELESS = Q.some(q => !q.ch.length);
const HAS_MULTI = Q.some(q => q.k > 1);
const HAS_DISC = Q.some(q => q.cm.length);
const HAS_OFFICIAL = Q.some(q => q.o);
const HAS_COMMUNITY = Q.some(q => q.v);

// ═════════════ State (persisted) ═════════════
const STORE_KEY = "examstudio:v2:" + META.exam;
const DEFAULT_FILTERS = { q: "", status: "all", domains: [], topics: [], type: "all", disc: false, ids: null, idsLabel: "" };
function defaults() {
  return {
    ans: {},            // uid → {sel, ok?, rev?, n, w, t}
    flag: {},           // uid → 1
    pos: null,          // current uid
    filters: Object.assign({}, DEFAULT_FILTERS),
    order: { mode: "seq", seed: 1 },
    view: "practice",
    theme: null,
    grade: "community", // community | official
    instant: false,     // single-answer: check on click
    advance: false,     // auto-advance after a correct answer
    discOpen: false,
    statSort: "weak",
    mock: null,
    mocks: [],
  };
}
let storageOk = true;
function load() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch (e) { storageOk = false; }
  const d = defaults();
  if (!s || typeof s !== "object") return d;
  const out = Object.assign(d, s);
  out.filters = Object.assign({}, DEFAULT_FILTERS, s.filters || {});
  out.order = Object.assign({ mode: "seq", seed: 1 }, s.order || {});
  return out;
}
const S = load();
let saveTimer = null;
function saveNow() {
  clearTimeout(saveTimer);
  try { localStorage.setItem(STORE_KEY, JSON.stringify(S)); storageOk = true; }
  catch (e) { if (storageOk) toast("⚠ Progress can't be saved in this browser (storage blocked). Use Export."); storageOk = false; }
}
function save() { clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, 120); }
window.addEventListener("beforeunload", saveNow);
document.addEventListener("visibilitychange", () => { if (document.hidden) saveNow(); });

// ═════════════ Helpers ═════════════
const $ = (sel, root = document) => root.querySelector(sel);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (a, b) => b ? Math.round(a / b * 100) : 0;
const sameSet = (a, b) => a.length === b.length && [...a].every(x => b.includes(x));
const letters = s => (s || "").split("").filter(Boolean);
function emphasize(text) {
  // Bold the qualifiers that decide AWS/Azure-style questions
  return esc(text).replace(/\b(MOST|LEAST|NOT|BEST|FEWEST|EXCEPT|ONLY|MINIMUM|MAXIMUM|MINIMAL|LOWEST|HIGHEST|FASTEST|CHEAPEST)\b|\((?:Choose|Select) (?:two|three|four|five|\d)\.?\)/g, m => "<strong>" + m + "</strong>");
}
function mulberry32(a) {
  return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
function shuffled(arr, seed) {
  const a = arr.slice(), rnd = mulberry32(seed);
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}
function fmtTime(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}
function fmtDate(t) { const d = new Date(t); return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
let toastTimer;
function toast(msg) {
  let el = $("#toast");
  if (!el) { el = document.createElement("div"); el.id = "toast"; el.className = "toast"; el.setAttribute("role", "status"); document.body.appendChild(el); }
  el.textContent = msg; el.classList.remove("hidden");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.add("hidden"), 2600);
}

// ═════════════ Grading ═════════════
function answerKey(q) {
  const c = letters(q.v), o = letters(q.o);
  if (S.grade === "official") return o.length ? o : c;
  return c.length ? c : o;
}
// The key decides how many picks are needed; "(Choose two.)" only matters when there is no key
function required(q) { return answerKey(q).length || q.k || 1; }
function statusOf(q) {
  const r = S.ans[q.u];
  if (!r) return "new";
  if (q.ch.length && r.sel) {
    const key = answerKey(q);
    if (!key.length) return "seen";
    return sameSet(letters(r.sel), key) ? "ok" : "bad";
  }
  if (r.ok === true) return "ok";
  if (r.ok === false) return "bad";
  return "seen";
}
function tally(list) {
  const t = { total: list.length, ok: 0, bad: 0, seen: 0, new: 0, flag: 0 };
  for (const q of list) { t[statusOf(q)]++; if (S.flag[q.u]) t.flag++; }
  t.done = t.ok + t.bad + t.seen;
  return t;
}
function barHTML(t, cls = "") {
  const w = n => (t.total ? n / t.total * 100 : 0).toFixed(2) + "%";
  const tip = `✓ ${t.ok} correct · ✗ ${t.bad} wrong · ${t.seen} revealed · ${t.new} not answered`;
  return `<div class="bar ${cls}" title="${tip}" role="img" aria-label="${tip}">` +
    (t.ok ? `<i class="g" style="width:${w(t.ok)}"></i>` : "") +
    (t.bad ? `<i class="r" style="width:${w(t.bad)}"></i>` : "") +
    (t.seen ? `<i class="y" style="width:${w(t.seen)}"></i>` : "") + `</div>`;
}

// ═════════════ Filtering & order ═════════════
let orderCache = { seed: null, list: null };
function orderedAll() {
  if (S.order.mode !== "shuffle") return Q;
  if (orderCache.seed !== S.order.seed) orderCache = { seed: S.order.seed, list: shuffled(Q, S.order.seed) };
  return orderCache.list;
}
function matches(q, f = S.filters, skip = null) {
  if (f.ids && !f.ids.includes(q.u)) return false;
  if (skip !== "status" && f.status !== "all") {
    if (f.status === "flag") { if (!S.flag[q.u]) return false; }
    else if (f.status === "done") { if (statusOf(q) === "new") return false; }
    else if (statusOf(q) !== f.status) return false;
  }
  if (skip !== "domain" && f.domains.length && !f.domains.includes(q.d)) return false;
  if (skip !== "topic" && f.topics.length && !q.tg.some(t => f.topics.includes(t))) return false;
  if (skip !== "type" && f.type !== "all") {
    const type = !q.ch.length ? "none" : q.k > 1 ? "multi" : "single";
    if (type !== f.type) return false;
  }
  if (f.disc && !q.cm.length) return false;
  if (f.q) {
    const terms = f.q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.every(t => q.s.includes(t))) return false;
  }
  return true;
}
let LIST = [];
function recompute() { LIST = orderedAll().filter(q => matches(q)); }
function curIndex() {
  const i = LIST.findIndex(q => q.u === S.pos);
  return i;
}
function current() {
  let i = curIndex();
  if (i < 0) { i = 0; S.pos = LIST.length ? LIST[0].u : null; }
  return LIST[i] || null;
}

const DISC_PAGE = 25;
let discShown = DISC_PAGE;

// ═════════════ Practice session (transient per-question UI state) ═════════════
let sess = { uid: null, sel: [], checked: false, revealed: false, discOpen: false };
function openQuestion(q) {
  const r = q ? S.ans[q.u] : null;
  sess = { uid: q ? q.u : null, sel: r && r.sel ? letters(r.sel) : [], checked: !!r, revealed: !!r, discOpen: false };
  discShown = DISC_PAGE;
}
function goto(uid, scroll = true) {
  S.pos = uid; save();
  openQuestion(BY_UID.get(uid));
  if (S.view !== "practice") setView("practice"); else renderPractice();
  if (scroll) window.scrollTo({ top: 0, behavior: "smooth" });
}
function step(delta) {
  if (!LIST.length) return;
  let i = curIndex(); if (i < 0) i = 0;
  const j = Math.min(LIST.length - 1, Math.max(0, i + delta));
  if (j !== i) goto(LIST[j].u);
  else toast(delta > 0 ? "End of the list" : "Start of the list");
}
function nextUnanswered() {
  if (!LIST.length) return;
  let i = curIndex();
  for (let k = 1; k <= LIST.length; k++) {
    const q = LIST[(i + k) % LIST.length];
    if (statusOf(q) === "new") { goto(q.u); return; }
  }
  toast("🎉 Every question in this selection has been answered");
}
function record(q, patch) {
  const prev = S.ans[q.u] || { n: 0, w: 0 };
  const r = Object.assign({}, prev, patch, { t: Date.now() });
  S.ans[q.u] = r;
  save();
  return r;
}
function check() {
  const q = current(); if (!q || sess.checked) return;
  if (!q.ch.length) { reveal(); return; }
  if (sess.sel.length !== required(q)) { toast(`Select ${required(q)} answer${required(q) > 1 ? "s" : ""}`); return; }
  const key = answerKey(q);
  const ok = key.length ? sameSet(sess.sel, key) : null;
  const prev = S.ans[q.u] || { n: 0, w: 0 };
  record(q, { sel: sess.sel.slice().sort().join(""), rev: 0, n: prev.n + 1, w: prev.w + (ok === false ? 1 : 0) });
  sess.checked = true; sess.revealed = true;
  renderPractice(); renderChrome();
  if (ok && S.advance) setTimeout(() => { if (sess.uid === q.u) step(1); }, 900);
}
function reveal() {
  const q = current(); if (!q) return;
  if (!S.ans[q.u]) record(q, { rev: 1, n: 0, w: 0 });
  sess.checked = true; sess.revealed = true;
  renderPractice(); renderChrome();
}
function selfGrade(ok) {
  const q = current(); if (!q) return;
  const prev = S.ans[q.u] || { n: 0, w: 0 };
  record(q, { ok, rev: 0, n: prev.n + 1, w: prev.w + (ok ? 0 : 1) });
  renderPractice(); renderChrome();
  if (ok && S.advance) setTimeout(() => step(1), 700);
}
function retry() {
  const q = current(); if (!q) return;
  sess = Object.assign(sess, { sel: [], checked: false, revealed: false });
  renderPractice();
}
function forget() {
  const q = current(); if (!q) return;
  delete S.ans[q.u]; save();
  retry(); renderChrome();
}
function toggleChoice(letter) {
  const q = current(); if (!q || sess.checked) return;
  if (!q.ch.some(c => c[0] === letter)) return;
  const need = required(q);
  if (need === 1) sess.sel = [letter];
  else if (sess.sel.includes(letter)) sess.sel = sess.sel.filter(x => x !== letter);
  else sess.sel = sess.sel.concat(letter);
  if (need === 1 && S.instant) { check(); return; }
  renderPractice();
}
function toggleFlag(q) {
  q = q || current(); if (!q) return;
  if (S.flag[q.u]) delete S.flag[q.u]; else S.flag[q.u] = 1;
  save(); render();
}

// ═════════════ Rendering: chrome ═════════════
function applyTheme() {
  document.documentElement.setAttribute("data-theme", S.theme || "__THEME__");
}
function renderChrome() {
  const t = tally(Q);
  $("#miniProgress").innerHTML = `<span><b>${t.done}</b>/${t.total} done · ${pct(t.ok, t.ok + t.bad)}% correct</span>${barHTML(t)}`;
  document.querySelectorAll("#tabs .tab").forEach(b => b.setAttribute("aria-selected", String(b.dataset.view === S.view)));
  const mockTab = document.querySelector('#tabs .tab[data-view="mock"]');
  mockTab.textContent = S.mock && !S.mock.done ? "Mock ●" : "Mock";
}
function render() {
  renderChrome();
  renderSidebar();
  if (S.view === "practice") renderPractice();
  else if (S.view === "map") renderMap();
  else if (S.view === "stats") renderStats();
  else if (S.view === "mock") renderMock();
}
function setView(v) {
  S.view = v; save();
  document.body.classList.remove("drawer-open");
  if (v === "practice") openQuestion(current());
  render();
  window.scrollTo({ top: 0 });
}

// ═════════════ Rendering: sidebar ═════════════
function countWith(pred, skip) { let n = 0; for (const q of Q) if (matches(q, S.filters, skip) && pred(q)) n++; return n; }
function renderSidebar() {
  const sb = $("#sidebar");
  if (S.view === "mock" || S.view === "stats") {
    sb.innerHTML = sidebarSummary();
    return;
  }
  const f = S.filters;
  const statusOpts = [["all", "All"], ["new", "Unanswered"], ["done", "Answered"], ["ok", "Correct"], ["bad", "Wrong"], ["flag", "⚑ Flagged"]];
  if (Q.some(q => statusOf(q) === "seen")) statusOpts.splice(5, 0, ["seen", "Revealed"]);
  const statusCount = v => countWith(q => v === "all" ? true : v === "flag" ? !!S.flag[q.u] : v === "done" ? statusOf(q) !== "new" : statusOf(q) === v, "status");

  let h = "";
  if (f.ids) h += `<div class="special"><span>${esc(f.idsLabel || "Custom selection")}</span><button data-act="clear-ids" title="Clear" aria-label="Clear selection">✕</button></div>`;
  h += `<button class="btn ghost drawer-close" data-act="close-drawer">✕ Close filters</button>`;
  h += `<div class="match-count"><b>${LIST.length}</b> of ${Q.length} questions match` +
       (isFiltered() ? ` · <a href="#" data-act="reset-filters">clear filters</a>` : "") + `</div>`;
  h += `<div class="fgroup"><input class="search" id="search" type="search" placeholder="Search questions…  ( / )" value="${esc(f.q)}" aria-label="Search questions"></div>`;
  h += `<div class="fgroup"><h4>Status</h4><div class="chips">` + statusOpts.map(([v, l]) =>
    `<button class="chip" data-status="${v}" aria-pressed="${f.status === v}">${l} <small>${statusCount(v)}</small></button>`).join("") + `</div></div>`;

  if (META.domains.length) {
    h += `<div class="fgroup"><h4>Domains ${f.domains.length ? '<button data-act="clear-domains">clear</button>' : ""}</h4><div class="dlist">` +
      META.domains.map(d => {
        const all = Q.filter(q => q.d === d);
        const on = f.domains.includes(d);
        return `<button class="drow" data-domain="${esc(d)}" aria-pressed="${on}"><span class="box">${on ? "✓" : ""}</span><span>${esc(d)}</span><small>${countWith(q => q.d === d, "domain")}</small>${barHTML(tally(all))}</button>`;
      }).join("") + `</div></div>`;
  }
  if (META.topics.length) {
    h += `<div class="fgroup"><h4>Topics ${f.topics.length ? '<button data-act="clear-topics">clear</button>' : ""}</h4><div class="chips">` +
      META.topics.map(t => `<button class="chip" data-topic="${esc(t)}" aria-pressed="${f.topics.includes(t)}">${esc(t)} <small>${countWith(q => q.tg.includes(t), "topic")}</small></button>`).join("") +
      `</div></div>`;
  }
  const types = [["all", "All"], ["single", "Single answer"]];
  if (HAS_MULTI) types.push(["multi", "Multiple answers"]);
  if (HAS_CHOICELESS) types.push(["none", "No choices / hotspot"]);
  if (types.length > 2) {
    h += `<div class="fgroup"><h4>Question type</h4><div class="chips">` + types.map(([v, l]) =>
      `<button class="chip" data-type="${v}" aria-pressed="${f.type === v}">${l} <small>${countWith(q => v === "all" || (v === "none" ? !q.ch.length : v === "multi" ? q.k > 1 : q.ch.length && q.k <= 1), "type")}</small></button>`).join("") + `</div></div>`;
  }
  if (HAS_DISC) h += `<div class="fgroup"><label class="toggle"><input type="checkbox" id="discOnly" ${f.disc ? "checked" : ""}> Only questions with discussion</label></div>`;
  h += `<div class="fgroup muted" style="font-size:12px">Generated ${esc(META.generated)} · progress is saved in this browser</div>`;
  sb.innerHTML = h;
}
function sidebarSummary() {
  const t = tally(Q);
  let h = `<div class="fgroup"><h4>Overall</h4><div style="font-size:26px;font-weight:700">${pct(t.done, t.total)}%<span class="muted" style="font-size:13px;font-weight:500"> answered</span></div>${barHTML(t, "thick")}<div class="muted" style="font-size:13px;margin-top:8px">✓ ${t.ok} correct · ✗ ${t.bad} wrong · ${t.new} left</div></div>`;
  if (META.domains.length) {
    h += `<div class="fgroup"><h4>By domain</h4><div class="dlist">` + META.domains.map(d => {
      const dt = tally(Q.filter(q => q.d === d));
      return `<div style="font-size:13px;margin-bottom:8px"><div style="display:flex;justify-content:space-between;gap:8px"><span>${esc(d)}</span><span class="muted">${pct(dt.ok, dt.ok + dt.bad)}%</span></div>${barHTML(dt)}</div>`;
    }).join("") + `</div></div>`;
  }
  return h;
}
function isFiltered() {
  const f = S.filters;
  return !!(f.q || f.status !== "all" || f.domains.length || f.topics.length || f.type !== "all" || f.disc || f.ids);
}
function filtersChanged() {
  const keep = S.pos;
  recompute();
  if (!LIST.some(q => q.u === keep)) S.pos = LIST.length ? LIST[0].u : null;
  openQuestion(current());
  save(); render();
}

// ═════════════ Rendering: practice ═════════════
function choiceClass(q, letter) {
  if (!sess.checked || !q.ch.length) return "";
  const key = answerKey(q), picked = sess.sel.includes(letter), correct = key.includes(letter);
  if (!key.length) return "";
  if (correct && picked) return "is-correct";
  if (correct && !picked) return sess.sel.length ? "is-missed" : "is-correct";
  if (picked) return "is-wrong";
  return "dim";
}
function choiceTag(cls) {
  return { "is-correct": "✓ Correct", "is-wrong": "✗ Your pick", "is-missed": "✓ Missed" }[cls] || "";
}
function renderPractice() {
  const view = $("#view");
  const q = current();
  if (sess.uid !== (q && q.u)) openQuestion(q);
  if (!q) {
    view.innerHTML = `<div class="card empty-state"><h3>No questions match these filters</h3><p>Try clearing a filter or two.</p><button class="btn primary" data-act="reset-filters">Clear filters</button></div>`;
    return;
  }
  const i = curIndex();
  const need = required(q), multi = need > 1, st = statusOf(q);
  const rec = S.ans[q.u];
  const stPill = { ok: '<span class="pill st-ok">✓ Correct</span>', bad: '<span class="pill st-bad">✗ Wrong</span>', seen: '<span class="pill st-seen">Revealed</span>' }[st] || "";

  let h = `<div class="toolbar">
    <div class="seg" role="group" aria-label="Order">
      <button data-order="seq" aria-pressed="${S.order.mode !== "shuffle"}">In order</button>
      <button data-order="shuffle" aria-pressed="${S.order.mode === "shuffle"}">Shuffled</button>
    </div>
    ${S.order.mode === "shuffle" ? `<button class="btn ghost" data-act="reshuffle" title="New random order (S)">🔀 Reshuffle</button>` : ""}
    <div class="spacer"></div>
    <span class="pos"><input id="jump" type="number" min="1" max="${LIST.length}" value="${i + 1}" aria-label="Go to position"> / ${LIST.length}</span>
  </div>`;

  h += `<article class="card qcard">
    <div class="qmeta">
      <span class="qnum">Question ${q.n}</span>
      ${q.tp ? `<span class="pill">Topic ${q.tp}</span>` : ""}
      ${q.d ? `<span class="pill dom">${esc(q.d)}</span>` : ""}
      ${q.tg.map(t => `<span class="pill">${esc(t)}</span>`).join("")}
      ${stPill}
      <span class="right">
        <button class="iconbtn flagbtn" data-act="flag" aria-pressed="${!!S.flag[q.u]}" title="Flag for review (M)">⚑ ${S.flag[q.u] ? "Flagged" : "Flag"}</button>
        ${q.l ? `<a class="iconbtn" href="${esc(q.l)}" target="_blank" rel="noopener" title="Open on ExamTopics">↗</a>` : ""}
      </span>
    </div>
    ${q.h ? `<div class="qheader">${esc(q.h)}</div>` : ""}
    <div class="stem">${emphasize(q.c)}</div>
    ${q.im.length ? `<div class="qimgs">${q.im.map(ix => `<img src="${IMG[ix]}" alt="Question exhibit" loading="lazy">`).join("")}</div>` : ""}`;

  if (q.ch.length) {
    h += multi ? `<div class="need">Select <b>${need}</b> answers · ${sess.sel.length}/${need} selected</div>` : "";
    h += `<div class="choices" role="group" aria-label="Answer choices">` + q.ch.map(([l, t, im]) => {
      const cls = choiceClass(q, l);
      return `<button class="choice ${multi ? "multi" : "single"} ${cls}" data-choice="${esc(l)}" aria-pressed="${sess.sel.includes(l)}" ${sess.checked ? "disabled" : ""}>
        <span class="letter">${esc(l)}</span>
        <span class="ctext">${esc(t)}${im != null ? `<br><img src="${IMG[im]}" alt="Option ${esc(l)}" loading="lazy">` : ""}</span>
        <span class="tag">${choiceTag(cls)}</span></button>`;
    }).join("") + `</div>`;
  }

  // Actions
  h += `<div class="actions">`;
  if (q.ch.length && !sess.checked) {
    h += `<button class="btn primary" data-act="check" ${sess.sel.length === need ? "" : "disabled"}>Check answer <span class="kbd">Enter</span></button>`;
    h += `<button class="btn ghost" data-act="reveal" title="Show the answer without answering (R)">Show answer</button>`;
  } else if (!q.ch.length && !sess.revealed) {
    h += `<button class="btn primary" data-act="reveal">Reveal answer <span class="kbd">Enter</span></button>`;
  } else {
    if (q.ch.length) h += `<button class="btn" data-act="retry">↺ Try again</button>`;
    h += `<button class="btn primary" data-act="next">Next <span class="kbd">Enter</span></button>`;
  }
  h += `<div class="spacer"></div>`;
  if (rec) h += `<button class="btn ghost" data-act="forget" title="Mark as not answered">Reset</button>`;
  h += `</div>`;

  if (sess.revealed) h += feedbackHTML(q);
  h += discussionHTML(q);

  h += `<div class="navrow">
      <button class="btn" data-act="prev" ${i <= 0 ? "disabled" : ""}>‹ Previous</button>
      <button class="btn ghost" data-act="next-new" title="Next unanswered (N)">Next unanswered ⏭</button>
      <button class="btn" data-act="next" ${i >= LIST.length - 1 ? "disabled" : ""}>Next ›</button>
    </div>
  </article>
  <div class="hint"><span><span class="kbd">A</span>–<span class="kbd">F</span> or <span class="kbd">1</span>–<span class="kbd">6</span> choose</span><span><span class="kbd">Enter</span> check / next</span><span><span class="kbd">←</span> <span class="kbd">→</span> navigate</span><span><span class="kbd">N</span> next unanswered</span><span><span class="kbd">M</span> flag</span><span><span class="kbd">?</span> all shortcuts</span></div>`;
  view.innerHTML = h;
}

function feedbackHTML(q) {
  const key = answerKey(q), off = letters(q.o), com = letters(q.v);
  const rec = S.ans[q.u];
  let cls = "", title = "";
  if (q.ch.length) {
    if (!key.length) { title = "No answer available for this question"; }
    else if (sess.sel.length && sess.checked && rec && rec.sel) {
      const ok = sameSet(sess.sel, key);
      cls = ok ? "ok" : "bad";
      title = ok ? "✓ Correct" : "✗ Incorrect";
    } else title = "Answer";
  } else {
    title = "Answer";
    if (rec && rec.ok === true) { cls = "ok"; title = "✓ You marked this as correct"; }
    if (rec && rec.ok === false) { cls = "bad"; title = "✗ You marked this as wrong"; }
  }
  let h = `<div class="feedback ${cls}"><div class="fb-title">${title}</div><div class="fb-lines">`;
  if (com.length) h += `<span>Community answer: <b>${com.join(", ")}</b></span>`;
  if (off.length) h += `<span>Official answer: <b>${off.join(", ")}</b></span>`;
  if (!off.length && q.or) h += `<span>Official answer: <b>${esc(q.or)}</b></span>`;
  if (!com.length && !off.length && !q.or) h += `<span>Check the discussion below for what the community thinks.</span>`;
  h += `</div>`;
  if (com.length && off.length && !sameSet(com, off)) {
    h += `<div class="fb-note">⚠ The official and community answers differ. You're graded against the <b>${S.grade === "official" ? "official" : "community"}</b> answer (change this in ⚙ Settings).</div>`;
  }
  if (q.vd.length) {
    const total = q.vd.reduce((a, v) => a + v[1], 0);
    h += `<div class="votes-h">Community vote · ${total} vote${total === 1 ? "" : "s"}</div><div class="votes">` +
      q.vd.slice(0, 5).map(([a, n]) => `<span class="vl">${a.split("").join(", ")}</span><span class="vt" title="${n} votes (${pct(n, total)}%)"><i style="width:${pct(n, total)}%"></i></span><span class="vn">${pct(n, total)}% · ${n}</span>`).join("") + `</div>`;
  }
  if (!q.ch.length && sess.revealed) {
    h += `<div class="actions"><span class="muted" style="font-size:13.5px">How did you do?</span>
      <button class="btn good" data-act="self-ok">✓ I got it right</button>
      <button class="btn bad" data-act="self-bad">✗ I got it wrong</button></div>`;
  }
  return h + `</div>`;
}

function discussionHTML(q) {
  if (!q.cm.length) return `<details class="disc empty"><summary>💬 No discussion scraped for this question</summary></details>`;
  const key = answerKey(q);
  const open = S.discOpen || sess.discOpen;
  const shown = q.cm.slice(0, discShown);
  let h = `<details class="disc" id="disc" ${open ? "open" : ""}><summary>💬 Discussion · ${q.cm.length} comment${q.cm.length === 1 ? "" : "s"}${sess.revealed ? "" : ' <span class="muted" style="font-weight:400">(may reveal the answer)</span>'}</summary><div class="cmts">`;
  h += shown.map(([au, dt, tx, up, hv, sel, depth]) => {
    const selCls = sel && key.length ? (sameSet(letters(sel), key) ? "ok" : "no") : "";
    return `<div class="cmt ${depth ? "reply" : ""}" style="${depth ? `margin-left:${Math.min(depth, 4) * 18}px` : ""}">
      <div class="cmt-h"><span class="au">${esc(au)}</span>${dt ? `<span class="dt">${esc(dt)}</span>` : ""}
      ${hv ? '<span class="badge hv">Highly voted</span>' : ""}
      ${sel ? `<span class="badge sel ${sess.revealed ? selCls : ""}">Selected ${esc(sel)}</span>` : ""}
      ${up ? `<span class="up">▲ ${up}</span>` : ""}</div>
      <div class="cmt-b">${esc(tx)}</div></div>`;
  }).join("");
  h += `</div>`;
  if (q.cm.length > shown.length) h += `<button class="more" data-act="more-comments">${q.cm.length - shown.length <= DISC_PAGE * 4 ? `Show ${q.cm.length - shown.length} more comments` : `Show ${DISC_PAGE * 4} more (${q.cm.length - shown.length} remaining)`}</button>`;
  return h + `</details>`;
}

// ═════════════ Rendering: map ═════════════
function renderMap() {
  const cur = S.pos;
  const t = tally(LIST);
  let h = `<h2 class="h2">Question map</h2><p class="sub">${LIST.length} question${LIST.length === 1 ? "" : "s"} in the current selection${isFiltered() ? " (filters applied)" : ""}${S.order.mode === "shuffle" ? " · shuffled order" : ""}. Click a square to open it.</p>
  <div class="legend">
    <span><i style="background:var(--good)"></i>Correct · ${t.ok}</span>
    <span><i style="background:var(--bad)"></i>Wrong · ${t.bad}</span>
    ${t.seen ? `<span><i style="background:var(--warn)"></i>Revealed · ${t.seen}</span>` : ""}
    <span><i style="background:var(--surface);border:1px solid var(--border-strong)"></i>Not answered · ${t.new}</span>
    <span><i style="background:var(--warn);border-radius:50%;width:8px;height:8px"></i>Flagged · ${t.flag}</span>
  </div><div class="card" style="padding:14px"><div class="grid">`;
  h += LIST.map(q => {
    const st = statusOf(q);
    return `<button class="cell ${st === "new" ? "" : st} ${q.u === cur ? "cur" : ""} ${S.flag[q.u] ? "fl" : ""}" data-goto="${q.u}" title="Question ${q.n}${q.d ? " · " + esc(q.d) : ""} · ${{ ok: "correct", bad: "wrong", seen: "revealed", new: "not answered" }[st]}">${q.n}</button>`;
  }).join("");
  h += `</div></div>`;
  if (!LIST.length) h = `<div class="card empty-state"><h3>No questions match these filters</h3><button class="btn primary" data-act="reset-filters">Clear filters</button></div>`;
  $("#view").innerHTML = h;
}

// ═════════════ Rendering: stats ═════════════
function groupStats(names, pick) {
  return names.map(n => {
    const t = tally(Q.filter(q => pick(q, n)));
    t.name = n; t.graded = t.ok + t.bad; t.acc = t.graded ? t.ok / t.graded : null;
    return t;
  });
}
function sortStats(rows) {
  if (S.statSort !== "weak") return rows;
  // Weakest first; groups with nothing graded yet go last
  return rows.slice().sort((a, b) => (a.acc === null) - (b.acc === null) || (a.acc - b.acc) || (b.bad - a.bad));
}
function breakdown(rows, filterKey) {
  return sortStats(rows).map(t => {
    const nums = t.graded
      ? `<span style="color:var(--good-text)">✓ <b>${pct(t.ok, t.graded)}%</b></span> · <span style="color:var(--bad-text)">✗ <b>${pct(t.bad, t.graded)}%</b></span> · ${t.done}/${t.total}`
      : `<span class="muted">not started</span> · 0/${t.total}`;
    return `<button class="brow" data-drill="${filterKey}" data-val="${esc(t.name)}" title="Practice ${esc(t.name)}: ${t.ok} correct, ${t.bad} wrong, ${t.new} not answered">
      <span class="nm">${esc(t.name)}</span>${barHTML(t)}
      <span class="nums">${nums}</span></button>`;
  }).join("");
}
function weakSpots(rows, kind) {
  const MIN = 3;
  const weak = rows.filter(t => t.graded >= MIN && t.acc < 0.8).sort((a, b) => a.acc - b.acc).slice(0, 5);
  if (!weak.length) return "";
  return weak.map(t => `<div class="wrow">
      <span class="nm"><b>${esc(t.name)}</b></span>
      <span class="nums"><span style="color:var(--bad-text)">✗ <b>${pct(t.bad, t.graded)}%</b> wrong</span> · ${t.bad} of ${t.graded} answered</span>
      <span class="actions-row">
        <button class="btn sm" data-drill="${kind}" data-val="${esc(t.name)}" data-drill-status="bad">Retry ${t.bad} wrong</button>
        ${t.new ? `<button class="btn sm ghost" data-drill="${kind}" data-val="${esc(t.name)}" data-drill-status="new">${t.new} new</button>` : ""}
      </span>${barHTML(t)}</div>`).join("");
}
function renderStats() {
  const t = tally(Q);
  const acc = pct(t.ok, t.ok + t.bad);
  let h = `<h2 class="h2">Your progress</h2><p class="sub">Saved in this browser for ${esc(META.title)}. Graded against the ${S.grade} answer.</p>
  <div class="kpis">
    <div class="card kpi"><div class="lbl">Answered</div><div class="val">${t.done}<small> / ${t.total}</small></div></div>
    <div class="card kpi"><div class="lbl">Accuracy</div><div class="val">${t.ok + t.bad ? acc + "%" : "—"}</div></div>
    <div class="card kpi"><div class="lbl">✓ Correct</div><div class="val">${t.ok}</div></div>
    <div class="card kpi"><div class="lbl">✗ Wrong</div><div class="val">${t.bad}</div></div>
    <div class="card kpi"><div class="lbl">⚑ Flagged</div><div class="val">${t.flag}</div></div>
  </div>
  <div class="card panel"><h3>Overall</h3><p class="sub">${t.new} questions left to answer.</p>${barHTML(t, "thick")}
    <div class="actions-row" style="margin-top:14px">
      <button class="btn primary" data-act="resume">▶ Resume practice</button>
      ${t.bad ? `<button class="btn" data-act="drill-wrong">Retry my ${t.bad} wrong answer${t.bad === 1 ? "" : "s"}</button>` : ""}
      ${t.flag ? `<button class="btn" data-act="drill-flag">Review ${t.flag} flagged</button>` : ""}
    </div></div>`;
  const domRows = groupStats(META.domains, (q, n) => q.d === n);
  const topRows = groupStats(META.topics, (q, n) => q.tg.includes(n));
  const weak = weakSpots(topRows, "topic") || weakSpots(domRows, "domain");
  h += `<div class="card panel"><h3>🎯 Weak spots</h3><p class="sub">Topics where you get the most wrong (at least 3 answered, under 80% correct). Focus here.</p>${
    weak || `<p class="muted" style="margin:0">${t.ok + t.bad < 10 ? "Answer a few more questions to see where you're weakest." : "Nothing below 80% — nice work."}</p>`}</div>`;
  const sortSeg = `<div class="seg" role="group" aria-label="Sort" style="float:right;margin-top:-4px"><button data-stat-sort="name" aria-pressed="${S.statSort !== "weak"}">Exam order</button><button data-stat-sort="weak" aria-pressed="${S.statSort === "weak"}">Weakest first</button></div>`;
  const legend = `<div class="stat-legend"><span><i style="background:var(--good)"></i>Correct</span><span><i style="background:var(--bad)"></i>Wrong</span><span><i style="background:var(--warn)"></i>Revealed</span><span><i style="background:var(--track)"></i>Not answered</span></div>`;
  if (META.topics.length) h += `<div class="card panel">${sortSeg}<h3>By topic</h3><p class="sub">% of answered questions you got right (✓) and wrong (✗). A question can belong to several topics. Click a row to practice it.</p>${legend}${breakdown(topRows, "topic")}</div>`;
  if (META.domains.length) h += `<div class="card panel">${META.topics.length ? "" : sortSeg}<h3>By exam domain</h3><p class="sub">Domains are inferred from question wording. Click a row to practice it.</p>${legend}${breakdown(domRows, "domain")}</div>`;
  if (S.mocks.length) {
    h += `<div class="card panel"><h3>Mock exam history</h3><table class="tbl"><thead><tr><th>Date</th><th>Score</th><th>Questions</th><th>Time</th><th></th></tr></thead><tbody>` +
      S.mocks.slice().reverse().map((m, ri) => `<tr><td>${fmtDate(m.date)}</td><td><b>${pct(m.ok, m.total)}%</b> (${m.ok}/${m.total})</td><td>${m.total}</td><td>${fmtTime(m.used)}</td><td><button class="btn ghost" data-mock-review="${S.mocks.length - 1 - ri}">Review</button></td></tr>`).join("") + `</tbody></table></div>`;
  }
  h += `<div class="card panel"><h3>Backup & reset</h3><p class="sub">Progress lives in this browser's storage. Export it to move to another browser or keep a backup.</p>
    <div class="actions-row"><button class="btn" data-act="export">⬇ Export progress</button><button class="btn" data-act="import">⬆ Import progress</button><button class="btn danger" data-act="reset-all">Reset all progress</button></div></div>`;
  $("#view").innerHTML = h;
}

// ═════════════ Mock exam ═════════════
function mockDefaults() {
  const aws = META.provider === "amazon";
  const n = Math.min(aws ? 65 : 50, Q.length);
  return { n, minutes: aws ? 130 : Math.round(n * 2) };
}
function startMock(n, minutes, pool, prefer) {
  let src = pool === "filtered" ? LIST.slice() : Q.slice();
  if (!src.length) { toast("No questions to build an exam from"); return; }
  src = shuffled(src, Date.now() & 0xffffffff);
  if (prefer) src.sort((a, b) => (statusOf(a) === "new" ? 0 : statusOf(a) === "bad" ? 1 : 2) - (statusOf(b) === "new" ? 0 : statusOf(b) === "bad" ? 1 : 2));
  const ids = src.slice(0, Math.min(n, src.length)).map(q => q.u);
  S.mock = { ids, i: 0, sel: {}, flag: {}, start: Date.now(), dur: minutes * 60, done: false };
  save(); setView("mock"); tickTimer();
}
function mockRemaining() { return S.mock ? S.mock.dur - (Date.now() - S.mock.start) / 1000 : 0; }
function submitMock(auto) {
  const m = S.mock; if (!m || m.done) return;
  if (!auto) {
    const unanswered = m.ids.filter(u => !(m.sel[u] || []).length).length;
    if (!confirm(unanswered ? `${unanswered} question(s) unanswered. Submit anyway?` : "Submit the exam?")) return;
  }
  let ok = 0; const per = {};
  for (const u of m.ids) {
    const q = BY_UID.get(u); if (!q) continue;
    const sel = (m.sel[u] || []).slice().sort();
    const good = sel.length && q.ch.length && sameSet(sel, answerKey(q));
    if (good) ok++;
    const d = q.d || "All";
    per[d] = per[d] || { ok: 0, total: 0 }; per[d].total++; if (good) per[d].ok++;
    if (sel.length && q.ch.length) {
      const prev = S.ans[u] || { n: 0, w: 0 };
      S.ans[u] = Object.assign({}, prev, { sel: sel.join(""), rev: 0, n: prev.n + 1, w: prev.w + (good ? 0 : 1), t: Date.now() });
    }
  }
  const used = Math.min(m.dur, (Date.now() - m.start) / 1000);
  S.mocks.push({ date: Date.now(), ok, total: m.ids.length, used, ids: m.ids, sel: m.sel, per });
  m.done = true; m.result = S.mocks.length - 1;
  save(); if (auto) toast("⏰ Time's up — exam submitted"); render(); tickTimer();
}
function renderMock() {
  const m = S.mock;
  const view = $("#view");
  if (!m) {
    const d = mockDefaults();
    view.innerHTML = `<h2 class="h2">Mock exam</h2><p class="sub">Timed, no feedback until you submit, like the real thing. Your answers also count toward your progress.</p>
    <div class="card panel">
      <div class="modal-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px">
        <label class="row" style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:var(--text-2)">Questions<input id="mkN" type="number" min="1" max="${Q.length}" value="${d.n}" class="search"></label>
        <label class="row" style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:var(--text-2)">Time limit (minutes)<input id="mkT" type="number" min="1" max="600" value="${d.minutes}" class="search"></label>
        <label class="row" style="display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:var(--text-2)">Draw questions from<select id="mkP" class="search"><option value="all">All ${Q.length} questions</option><option value="filtered" ${isFiltered() ? "selected" : ""}>Current filters (${LIST.length})</option></select></label>
      </div>
      <label class="toggle" style="margin-top:12px"><input type="checkbox" id="mkPrefer" checked> Prefer questions I haven't answered or got wrong</label>
      <div class="actions-row" style="margin-top:16px"><button class="btn primary" data-act="mock-start">Start exam</button></div>
    </div>` + (S.mocks.length ? `<p class="sub">Past results are under <a href="#" data-view-link="stats">Progress</a>.</p>` : "");
    return;
  }
  if (m.done) {
    const r = S.mocks[m.result];
    const score = pct(r.ok, r.total);
    const passLine = 72;
    view.innerHTML = `<div class="card result-hero"><div class="muted">Mock exam result</div><div class="score">${score}%</div>
      <div class="verdict ${score >= passLine ? "ok" : "bad"}">${score >= passLine ? "✓ Above" : "✗ Below"} the ~${passLine}% pass mark</div>
      <div class="muted" style="margin-top:6px">${r.ok} of ${r.total} correct · ${fmtTime(r.used)} used</div>
      <div class="actions-row" style="justify-content:center;margin-top:16px">
        <button class="btn primary" data-mock-review="${m.result}">Review answers</button>
        <button class="btn" data-act="mock-new">New mock exam</button></div></div>` +
      (Object.keys(r.per).length > 1 ? `<div class="card panel" style="margin-top:16px"><h3>By domain</h3><table class="tbl"><thead><tr><th>Domain</th><th>Score</th><th>Correct</th></tr></thead><tbody>` +
        Object.entries(r.per).sort().map(([d, v]) => `<tr><td>${esc(d)}</td><td><b>${pct(v.ok, v.total)}%</b></td><td>${v.ok}/${v.total}</td></tr>`).join("") + `</tbody></table></div>` : "");
    return;
  }
  const u = m.ids[m.i], q = BY_UID.get(u);
  const sel = m.sel[u] || [], need = required(q);
  const answered = m.ids.filter(x => (m.sel[x] || []).length).length;
  let h = `<div class="mockbar"><div><b>Question ${m.i + 1}</b> <span class="muted">of ${m.ids.length} · ${answered} answered</span></div>
    <div class="actions-row"><button class="btn danger" data-act="mock-abandon">Abandon</button><button class="btn primary" data-act="mock-submit">Submit exam</button></div></div>
    <article class="card qcard"><div class="qmeta"><span class="qnum">Question ${m.i + 1}</span>
    <span class="right"><button class="iconbtn flagbtn" data-act="mock-flag" aria-pressed="${!!m.flag[u]}">⚑ ${m.flag[u] ? "Marked" : "Mark for review"}</button></span></div>
    <div class="stem">${emphasize(q.c)}</div>
    ${q.im.length ? `<div class="qimgs">${q.im.map(ix => `<img src="${IMG[ix]}" alt="Question exhibit" loading="lazy">`).join("")}</div>` : ""}`;
  if (q.ch.length) {
    h += need > 1 ? `<div class="need">Select <b>${need}</b> answers · ${sel.length}/${need} selected</div>` : "";
    h += `<div class="choices">` + q.ch.map(([l, t, im]) => `<button class="choice ${need > 1 ? "multi" : "single"}" data-mchoice="${esc(l)}" aria-pressed="${sel.includes(l)}"><span class="letter">${esc(l)}</span><span class="ctext">${esc(t)}${im != null ? `<br><img src="${IMG[im]}" alt="Option ${esc(l)}" loading="lazy">` : ""}</span><span class="tag"></span></button>`).join("") + `</div>`;
  } else {
    h += `<p class="muted">This question has no selectable choices and isn't scored in a mock exam.</p>`;
  }
  h += `<div class="navrow"><button class="btn" data-act="mock-prev" ${m.i ? "" : "disabled"}>‹ Previous</button><button class="btn" data-act="mock-next" ${m.i < m.ids.length - 1 ? "" : "disabled"}>Next ›</button></div></article>
    <div class="card" style="padding:14px;margin-top:16px"><div class="legend" style="margin-bottom:10px"><span><i style="background:var(--accent-weak);border:1px solid var(--accent)"></i>Answered</span><span><i style="background:var(--surface);border:1px solid var(--border-strong)"></i>Not answered</span><span><i style="background:var(--warn);border-radius:50%;width:8px;height:8px"></i>Marked</span></div><div class="grid">` +
    m.ids.map((x, k) => `<button class="cell ${(m.sel[x] || []).length ? "ans" : ""} ${k === m.i ? "cur" : ""} ${m.flag[x] ? "fl" : ""}" data-mgoto="${k}">${k + 1}</button>`).join("") + `</div></div>`;
  view.innerHTML = h;
}
function mockPick(letter) {
  const m = S.mock; if (!m || m.done) return;
  const u = m.ids[m.i], q = BY_UID.get(u);
  if (!q.ch.some(c => c[0] === letter)) return;
  const need = required(q);
  let sel = m.sel[u] || [];
  if (need === 1) sel = sel[0] === letter ? [] : [letter];
  else sel = sel.includes(letter) ? sel.filter(x => x !== letter) : sel.concat(letter);
  m.sel[u] = sel; save(); renderMock();
}
function mockGo(i) { const m = S.mock; if (!m) return; m.i = Math.max(0, Math.min(m.ids.length - 1, i)); save(); renderMock(); window.scrollTo({ top: 0 }); }
function tickTimer() {
  const el = $("#timer");
  if (S.mock && !S.mock.done) {
    const rem = mockRemaining();
    el.classList.remove("hidden"); el.classList.toggle("low", rem < 300);
    el.textContent = "⏱ " + fmtTime(rem);
    if (rem <= 0) submitMock(true);
  } else el.classList.add("hidden");
}
setInterval(tickTimer, 1000);

// ═════════════ Modals ═════════════
function modal(html, onMount) {
  const ov = $("#overlay");
  ov.innerHTML = `<div class="modal-bg" data-close="1"><div class="card modal" role="dialog" aria-modal="true">${html}</div></div>`;
  const first = ov.querySelector("button, select, input"); if (first) first.focus();
  if (onMount) onMount(ov);
}
function closeModal() { $("#overlay").innerHTML = ""; }
function openSettings() {
  modal(`<h3>Settings</h3><p class="sub">Saved with your progress.</p>
    <div class="row"><label for="setGrade">Grade answers against</label>
      <select id="setGrade">
        <option value="community" ${S.grade === "community" ? "selected" : ""}>Community vote (most voted answer)${HAS_COMMUNITY ? "" : " — not available"}</option>
        <option value="official" ${S.grade === "official" ? "selected" : ""}>Official / suggested answer${HAS_OFFICIAL ? "" : " — not available"}</option>
      </select>
      <span class="muted" style="font-size:12.5px">Falls back to the other when one is missing. ExamTopics' suggested answers are often wrong, so the community vote is usually more reliable.</span></div>
    <label class="toggle"><input type="checkbox" id="setInstant" ${S.instant ? "checked" : ""}> Check single-answer questions as soon as I click a choice</label>
    <label class="toggle"><input type="checkbox" id="setAdvance" ${S.advance ? "checked" : ""}> Go to the next question automatically after a correct answer</label>
    <label class="toggle"><input type="checkbox" id="setDisc" ${S.discOpen ? "checked" : ""}> Keep the discussion expanded</label>
    <div class="row"><label for="setTheme">Theme</label><select id="setTheme"><option value="">Default (__THEME__)</option><option value="light" ${S.theme === "light" ? "selected" : ""}>Light</option><option value="dark" ${S.theme === "dark" ? "selected" : ""}>Dark</option></select></div>
    <div class="foot"><button class="btn primary" data-act="close-modal">Done</button></div>`, ov => {
    ov.querySelector("#setGrade").onchange = e => { S.grade = e.target.value; save(); render(); };
    ov.querySelector("#setInstant").onchange = e => { S.instant = e.target.checked; save(); };
    ov.querySelector("#setAdvance").onchange = e => { S.advance = e.target.checked; save(); };
    ov.querySelector("#setDisc").onchange = e => { S.discOpen = e.target.checked; save(); render(); };
    ov.querySelector("#setTheme").onchange = e => { S.theme = e.target.value || null; save(); applyTheme(); };
  });
}
function openHelp() {
  const k = s => s.split(" ").map(x => `<span class="kbd">${x}</span>`).join(" ");
  modal(`<h3>Keyboard shortcuts</h3><p class="sub">Shortcuts are off while typing in a field.</p><div class="keys">
    <span>${k("A–H")} / ${k("1–8")}</span><span>Choose / unchoose an answer</span>
    <span>${k("Enter")}</span><span>Check answer, then go to the next question</span>
    <span>${k("←")} ${k("→")}</span><span>Previous / next question</span>
    <span>${k("N")}</span><span>Next unanswered question</span>
    <span>${k("R")}</span><span>Show the answer without answering</span>
    <span>${k("M")}</span><span>Flag / unflag for review</span>
    <span>${k("S")}</span><span>Reshuffle (turns on shuffled order)</span>
    <span>${k("/")}</span><span>Search</span>
    <span>${k("T")}</span><span>Toggle light / dark</span>
    <span>${k("Esc")}</span><span>Close dialogs</span></div>
    <div class="foot"><button class="btn primary" data-act="close-modal">Got it</button></div>`);
}
function exportProgress() {
  const blob = new Blob([JSON.stringify({ exam: META.exam, exported: new Date().toISOString(), state: S }, null, 1)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `exam-studio-${META.exam}-progress-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function importProgress() {
  const inp = document.createElement("input"); inp.type = "file"; inp.accept = "application/json,.json";
  inp.onchange = () => {
    const file = inp.files[0]; if (!file) return;
    file.text().then(txt => {
      const data = JSON.parse(txt);
      const st = data.state || data;
      if (!st || typeof st.ans !== "object") throw new Error("not a progress file");
      if (data.exam && data.exam !== META.exam && !confirm(`This backup is for ${data.exam}, not ${META.exam}. Import anyway?`)) return;
      let merged = 0;
      for (const [u, r] of Object.entries(st.ans || {})) {
        if (!S.ans[u] || (r.t || 0) > (S.ans[u].t || 0)) { S.ans[u] = r; merged++; }
      }
      Object.assign(S.flag, st.flag || {});
      const seen = new Set(S.mocks.map(m => m.date));
      (st.mocks || []).forEach(m => { if (!seen.has(m.date)) S.mocks.push(m); });
      S.mocks.sort((a, b) => a.date - b.date);
      saveNow(); render();
      toast(`Imported ${merged} answer${merged === 1 ? "" : "s"}`);
    }).catch(e => toast("Import failed: " + e.message));
  };
  inp.click();
}

// ═════════════ Events ═════════════
document.addEventListener("click", e => {
  const t = e.target.closest("button, a, [data-close]");
  if (!t) return;
  if (t.dataset.close && e.target === t) { closeModal(); return; }
  const d = t.dataset;
  if (d.view) { setView(d.view); return; }
  if (d.viewLink) { e.preventDefault(); setView(d.viewLink); return; }
  if (d.choice) { toggleChoice(d.choice); return; }
  if (d.mchoice) { mockPick(d.mchoice); return; }
  if (d.mgoto) { mockGo(+d.mgoto); return; }
  if (d.goto) { goto(d.goto); return; }
  if (d.status) { S.filters.status = d.status; filtersChanged(); return; }
  if (d.domain) { toggleIn(S.filters.domains, d.domain); filtersChanged(); return; }
  if (d.topic) { toggleIn(S.filters.topics, d.topic); filtersChanged(); return; }
  if (d.type) { S.filters.type = d.type; filtersChanged(); return; }
  if (d.order) {
    S.order.mode = d.order;
    if (d.order === "shuffle" && !S.order.seed) S.order.seed = (Math.random() * 2 ** 31) | 0;
    filtersChanged(); return;
  }
  if (d.statSort) { S.statSort = d.statSort; save(); renderStats(); return; }
  if (d.drill) {
    Object.assign(S.filters, DEFAULT_FILTERS, { domains: [], topics: [], status: d.drillStatus || "all" });
    if (d.drill === "domain") S.filters.domains = [d.val]; else S.filters.topics = [d.val];
    S.view = "practice"; filtersChanged(); return;
  }
  if (d.mockReview) {
    const r = S.mocks[+d.mockReview];
    Object.assign(S.filters, DEFAULT_FILTERS, { domains: [], topics: [], ids: r.ids.slice(), idsLabel: `Mock exam · ${fmtDate(r.date)}` });
    S.order.mode = "seq"; S.pos = r.ids[0];
    S.view = "practice"; filtersChanged(); return;
  }
  switch (d.act) {
    case "check": check(); break;
    case "reveal": reveal(); break;
    case "retry": retry(); break;
    case "forget": forget(); break;
    case "next": step(1); break;
    case "prev": step(-1); break;
    case "next-new": nextUnanswered(); break;
    case "flag": toggleFlag(); break;
    case "self-ok": selfGrade(true); break;
    case "self-bad": selfGrade(false); break;
    case "reshuffle": reshuffle(); break;
    case "more-comments": discShown += DISC_PAGE * 4; sess.discOpen = true; renderPractice(); break;
    case "reset-filters": e.preventDefault(); Object.assign(S.filters, DEFAULT_FILTERS, { domains: [], topics: [] }); filtersChanged(); break;
    case "clear-ids": S.filters.ids = null; S.filters.idsLabel = ""; filtersChanged(); break;
    case "clear-domains": S.filters.domains = []; filtersChanged(); break;
    case "clear-topics": S.filters.topics = []; filtersChanged(); break;
    case "resume": setView("practice"); if (statusOf(current() || Q[0]) !== "new") nextUnanswered(); break;
    case "drill-wrong": Object.assign(S.filters, DEFAULT_FILTERS, { domains: [], topics: [], status: "bad" }); S.view = "practice"; filtersChanged(); break;
    case "drill-flag": Object.assign(S.filters, DEFAULT_FILTERS, { domains: [], topics: [], status: "flag" }); S.view = "practice"; filtersChanged(); break;
    case "export": exportProgress(); break;
    case "import": importProgress(); break;
    case "reset-all":
      if (confirm("Erase all answers, flags and mock exam history for " + META.title + "? This can't be undone (export first if unsure).")) {
        S.ans = {}; S.flag = {}; S.mocks = []; S.mock = null; saveNow(); recompute(); openQuestion(current()); render(); toast("Progress reset");
      }
      break;
    case "close-modal": closeModal(); break;
    case "close-drawer": document.body.classList.remove("drawer-open"); break;
    case "mock-start": {
      const n = Math.max(1, parseInt($("#mkN").value, 10) || 1), mins = Math.max(1, parseInt($("#mkT").value, 10) || 1);
      startMock(n, mins, $("#mkP").value, $("#mkPrefer").checked); break;
    }
    case "mock-submit": submitMock(false); break;
    case "mock-abandon": if (confirm("Abandon this mock exam? Answers won't be recorded.")) { S.mock = null; save(); render(); tickTimer(); } break;
    case "mock-new": S.mock = null; save(); render(); break;
    case "mock-flag": { const m = S.mock, u = m.ids[m.i]; if (m.flag[u]) delete m.flag[u]; else m.flag[u] = 1; save(); renderMock(); break; }
    case "mock-prev": mockGo(S.mock.i - 1); break;
    case "mock-next": mockGo(S.mock.i + 1); break;
  }
});
function toggleIn(arr, v) { const i = arr.indexOf(v); if (i >= 0) arr.splice(i, 1); else arr.push(v); }
function reshuffle() {
  S.order.mode = "shuffle";
  S.order.seed = (Math.random() * 2 ** 31) | 0;
  recompute();
  S.pos = LIST.length ? LIST[0].u : null;
  openQuestion(current()); save(); render();
  toast("🔀 New random order");
}
document.addEventListener("toggle", e => {
  if (e.target.id === "disc") sess.discOpen = e.target.open;
}, true);
let searchTimer;
document.addEventListener("input", e => {
  if (e.target.id === "search") {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      S.filters.q = e.target.value.trim();
      recompute();
      if (!LIST.some(q => q.u === S.pos)) S.pos = LIST.length ? LIST[0].u : null;
      save();
      // Re-render without losing focus in the search box
      const pos = e.target.selectionStart;
      renderSidebar(); renderChrome();
      if (S.view === "practice") renderPractice(); else if (S.view === "map") renderMap();
      const s = $("#search"); if (s) { s.focus(); try { s.setSelectionRange(pos, pos); } catch (_) {} }
    }, 180);
  }
});
document.addEventListener("change", e => {
  if (e.target.id === "discOnly") { S.filters.disc = e.target.checked; filtersChanged(); }
  if (e.target.id === "jump") {
    const n = parseInt(e.target.value, 10);
    if (n >= 1 && n <= LIST.length) goto(LIST[n - 1].u); else e.target.value = curIndex() + 1;
  }
});
$("#themeBtn").onclick = () => { const cur = document.documentElement.getAttribute("data-theme"); S.theme = cur === "dark" ? "light" : "dark"; save(); applyTheme(); };
$("#settingsBtn").onclick = openSettings;
$("#helpBtn").onclick = openHelp;
$("#drawerBtn").onclick = () => document.body.classList.toggle("drawer-open");
document.addEventListener("click", e => {
  if (document.body.classList.contains("drawer-open") && !e.target.closest("#sidebar") && !e.target.closest("#drawerBtn")) document.body.classList.remove("drawer-open");
});
document.addEventListener("click", e => {
  const img = e.target.closest(".qimgs img, .ctext img");
  if (img && !e.target.closest(".choice:not([disabled])")) {
    $("#overlay").innerHTML = `<div class="lightbox" data-close="1"><img src="${img.src}" alt="${esc(img.alt)}" data-close="1"></div>`;
  }
});

document.addEventListener("keydown", e => {
  if (e.key === "Escape") { closeModal(); document.body.classList.remove("drawer-open"); return; }
  if ($("#overlay").innerHTML) return;
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") {
    if (e.key === "Enter" && e.target.id === "search") e.target.blur();
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key;
  const letter = /^[a-h]$/i.test(k) ? k.toUpperCase() : /^[1-8]$/.test(k) ? String.fromCharCode(64 + +k) : null;

  if (S.view === "mock" && S.mock && !S.mock.done) {
    if (letter) { mockPick(letter); e.preventDefault(); }
    else if (k === "ArrowRight") mockGo(S.mock.i + 1);
    else if (k === "ArrowLeft") mockGo(S.mock.i - 1);
    else if (k === "m" || k === "M") $('[data-act="mock-flag"]')?.click();
    return;
  }
  if (k === "?" ) { openHelp(); return; }
  if (k === "t" || k === "T") { $("#themeBtn").click(); return; }
  if (k === "/") { e.preventDefault(); if (S.view !== "practice" && S.view !== "map") setView("practice"); document.body.classList.add("drawer-open"); $("#search")?.focus(); return; }
  if (S.view !== "practice") return;
  const q = current(); if (!q) return;
  if (letter && q.ch.length && !(k.toLowerCase() === "m")) { if (q.ch.some(c => c[0] === letter)) { toggleChoice(letter); e.preventDefault(); } return; }
  if (k === "Enter") {
    e.preventDefault();
    if (!sess.checked && q.ch.length) { if (sess.sel.length === required(q)) check(); else toast(`Select ${required(q)} answer${required(q) > 1 ? "s" : ""}`); }
    else if (!q.ch.length && !sess.revealed) reveal();
    else step(1);
  }
  else if (k === "ArrowRight") { e.preventDefault(); step(1); }
  else if (k === "ArrowLeft") { e.preventDefault(); step(-1); }
  else if (k === "n" || k === "N") nextUnanswered();
  else if (k === "r" || k === "R") reveal();
  else if (k === "m" || k === "M") toggleFlag();
  else if (k === "s" || k === "S") reshuffle();
});

// ═════════════ Boot ═════════════
applyTheme();
recompute();
if (!S.pos || !LIST.some(q => q.u === S.pos)) {
  const firstNew = LIST.find(q => statusOf(q) === "new");
  S.pos = (firstNew || LIST[0] || {}).u || null;
}
openQuestion(current());
render();
tickTimer();
if (Object.keys(S.ans).length && S.view === "practice") {
  const t = tally(Q);
  toast(`Welcome back — ${t.done}/${t.total} answered. Picking up where you left off.`);
}
})();
</script>
</body>
</html>
'''
