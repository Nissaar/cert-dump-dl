"""
Interactive HTML generator — handles structured choices, images, and formatted discussions.
"""

from pathlib import Path
from jinja2 import Template

HTML_TEMPLATE = Template('''\
<!DOCTYPE html>
<html lang="en" data-theme="{{ theme }}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Exam Studio — {{ title }}</title>
<style>
  :root {
    --bg: #1a1a2e; --surface: #16213e; --card: #0f3460;
    --text: #e0e0e0; --text-muted: #a0a0b0; --accent: #e94560;
    --accent2: #533483; --correct: #00c853; --wrong: #ff5252;
    --border: #2a2a4a; --reveal-bg: #1b1b3a;
  }
  [data-theme="light"] {
    --bg: #f0f2f5; --surface: #ffffff; --card: #ffffff;
    --text: #1a1a1a; --text-muted: #555; --accent: #d32f2f;
    --accent2: #7b1fa2; --correct: #2e7d32; --wrong: #c62828;
    --border: #ddd; --reveal-bg: #fafafa;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    line-height: 1.65; font-size: 15px;
  }

  /* ── Header ── */
  .header {
    background: var(--surface); border-bottom: 3px solid var(--accent);
    padding: 1rem 2rem; position: sticky; top: 0; z-index: 100;
  }
  .header-top { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.8rem; }
  .header h1 { font-size: 1.3rem; color: var(--accent); }
  .header h1 span { color: var(--text-muted); font-weight: 400; font-size: 0.9rem; }
  .stats { display: flex; gap: 1.5rem; font-size: 0.85rem; color: var(--text-muted); }
  .stats b { color: var(--text); }
  .progress-bar { height: 3px; background: var(--border); margin-top: 0.6rem; border-radius: 2px; overflow: hidden; }
  .progress-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); width: 0%; transition: width 0.4s; }

  /* ── Controls ── */
  .controls {
    background: var(--surface); padding: 0.7rem 2rem;
    border-bottom: 1px solid var(--border);
    display: flex; gap: 0.8rem; flex-wrap: wrap; align-items: center;
  }
  .btn {
    background: var(--card); color: var(--text); border: 1px solid var(--border);
    padding: 0.45rem 1rem; border-radius: 6px; cursor: pointer;
    font-size: 0.82rem; transition: all 0.2s; white-space: nowrap;
  }
  .btn:hover { border-color: var(--accent); background: var(--accent)11; }
  .search-box {
    flex: 1; min-width: 180px; background: var(--card); color: var(--text);
    border: 1px solid var(--border); padding: 0.45rem 0.8rem;
    border-radius: 6px; font-size: 0.82rem;
  }
  .search-box:focus { outline: none; border-color: var(--accent); }

  .kbd {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 3px; padding: 0.05rem 0.35rem; font-size: 0.7rem;
    font-family: monospace; vertical-align: middle;
  }

  /* ── Container ── */
  .container { max-width: 960px; margin: 1.5rem auto; padding: 0 1.2rem; }

  /* ── Question Card ── */
  .qcard {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 1.5rem 1.8rem; margin-bottom: 1.2rem;
    transition: border-color 0.2s;
  }
  .qcard:hover { border-color: var(--accent)88; }
  .qcard.answered-correct { border-left: 4px solid var(--correct); }
  .qcard.answered-wrong { border-left: 4px solid var(--wrong); }

  .q-head { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.8rem; }
  .q-num { font-weight: 700; color: var(--accent); font-size: 0.95rem; }
  .q-meta { font-size: 0.75rem; color: var(--text-muted); }
  .q-meta a { color: var(--accent); }

  .q-body { margin-bottom: 1rem; white-space: pre-wrap; }
  .q-body img, .q-images img {
    max-width: 100%; border-radius: 6px; margin: 0.5rem 0;
    border: 1px solid var(--border);
  }

  /* ── Choices ── */
  .choices { list-style: none; margin-bottom: 1rem; }
  .choice {
    padding: 0.65rem 1rem; margin: 0.35rem 0;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; cursor: pointer; transition: all 0.2s;
    display: flex; align-items: flex-start; gap: 0.7rem;
  }
  .choice:hover { border-color: var(--accent); transform: translateX(3px); }
  .choice.selected { border-color: var(--accent2); background: rgba(83,52,131,0.12); }
  .choice.correct-show { border-color: var(--correct); background: rgba(0,200,83,0.08); }
  .choice.correct-show .choice-letter { color: var(--correct); }
  .choice.wrong-show { border-color: var(--wrong); background: rgba(255,82,82,0.08); }
  .choice-letter { font-weight: 700; color: var(--accent); min-width: 1.4rem; flex-shrink: 0; }
  .choice-text { flex: 1; }
  .choice-text img { max-width: 100%; border-radius: 4px; margin-top: 0.3rem; }

  /* ── Reveal ── */
  .reveal-btn {
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    color: #fff; border: none; padding: 0.55rem 1.4rem; border-radius: 8px;
    cursor: pointer; font-size: 0.85rem; font-weight: 600; transition: opacity 0.2s;
  }
  .reveal-btn:hover { opacity: 0.85; }
  .reveal-btn:disabled { opacity: 0.4; cursor: default; }

  .answer-block {
    display: none; margin-top: 0.8rem; padding: 1rem 1.2rem;
    background: var(--reveal-bg); border-radius: 8px;
    border-left: 3px solid var(--correct);
  }
  .answer-block.visible { display: block; animation: fadeIn 0.3s; }
  .answer-label { font-weight: 700; color: var(--correct); margin-bottom: 0.2rem; }
  .voted-label { font-size: 0.85rem; color: var(--text-muted); margin-top: 0.3rem; }
  .voted-label b { color: var(--accent2); }

  /* ── Discussion ── */
  .disc-btn {
    background: none; border: 1px solid var(--border); color: var(--text-muted);
    padding: 0.35rem 0.9rem; border-radius: 6px; cursor: pointer;
    font-size: 0.78rem; margin-top: 0.6rem; transition: all 0.2s;
  }
  .disc-btn:hover { border-color: var(--accent); color: var(--text); }
  .disc-box {
    display: none; margin-top: 0.6rem; max-height: 400px; overflow-y: auto;
    border-radius: 8px; border: 1px solid var(--border);
  }
  .disc-box.visible { display: block; animation: fadeIn 0.3s; }

  .comment {
    padding: 0.7rem 1rem; border-bottom: 1px solid var(--border);
    background: var(--surface); font-size: 0.82rem;
  }
  .comment:last-child { border-bottom: none; }
  .comment:nth-child(even) { background: var(--card); }
  .comment-header { display: flex; justify-content: space-between; margin-bottom: 0.3rem; }
  .comment-author { font-weight: 600; color: var(--accent); font-size: 0.78rem; }
  .comment-date { color: var(--text-muted); font-size: 0.72rem; }
  .comment-votes {
    display: inline-block; background: var(--correct)22; color: var(--correct);
    font-size: 0.7rem; padding: 0.1rem 0.4rem; border-radius: 10px;
    font-weight: 600; margin-left: 0.5rem;
  }
  .comment-body { color: var(--text-muted); line-height: 1.5; }

  /* ── Animations ── */
  @keyframes fadeIn { from { opacity:0; transform:translateY(-4px); } to { opacity:1; transform:translateY(0); } }

  /* ── Responsive ── */
  @media (max-width: 640px) {
    .header { padding: 0.8rem 1rem; }
    .controls { padding: 0.6rem 1rem; }
    .container { padding: 0 0.6rem; }
    .qcard { padding: 1rem 1.2rem; }
  }
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <h1>📝 Exam Studio <span>{{ title }}</span></h1>
    <div class="stats">
      <div>Total: <b id="totalQ">{{ questions|length }}</b></div>
      <div>Revealed: <b id="revealedQ">0</b></div>
      <div>Score: <b id="scoreQ">—</b></div>
    </div>
  </div>
  <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
</div>

<div class="controls">
  <button class="btn" onclick="revealAll()">👁 Reveal All</button>
  <button class="btn" onclick="hideAll()">🙈 Hide All</button>
  <button class="btn" onclick="scrollToNext()">⏭ Next</button>
  <input type="text" class="search-box" placeholder="🔍 Filter questions..." oninput="filterQ(this.value)">
  <span style="font-size:0.72rem;color:var(--text-muted);">
    <span class="kbd">R</span> Reveal &nbsp; <span class="kbd">↓</span> Next
  </span>
</div>

<div class="container" id="qContainer">
{% for q in questions %}
<div class="qcard" id="q{{ loop.index }}" data-idx="{{ loop.index }}"
     data-answer="{{ q.answer|default('',true)|upper }}"
     data-search="{{ (q.title or '')|lower }} {{ (q.content or '')|lower }}">

  <div class="q-head">
    <span class="q-num">Q{{ loop.index }}. {{ q.title or 'Question ' ~ loop.index }}</span>
    <span class="q-meta">
      {% if q.question_link %}<a href="{{ q.question_link }}" target="_blank" rel="noopener">View on ExamTopics ↗</a>{% endif %}
    </span>
  </div>

  {% if q.header %}
  <div style="font-size:0.83rem;color:var(--text-muted);margin-bottom:0.6rem;font-style:italic;">{{ q.header }}</div>
  {% endif %}

  <div class="q-body">{{ q.content or '' }}</div>

  {# ── Question images ── #}
  {% if q.images %}
  <div class="q-images">
    {% for img in q.images %}
      {% if img.context == 'question' %}
      <img src="{{ img.base64 }}" alt="{{ img.alt or 'Question image' }}" loading="lazy">
      {% endif %}
    {% endfor %}
  </div>
  {% endif %}

  {# ── Answer choices ── #}
  {% if q.choices %}
  <ul class="choices" id="choices{{ loop.index }}">
    {% for c in q.choices %}
    <li class="choice" onclick="pickChoice(this, {{ loop.index }}, '{{ c.letter }}')" data-letter="{{ c.letter }}">
      <span class="choice-letter">{{ c.letter }}.</span>
      <span class="choice-text">
        {{ c.text }}
        {% if c.image %}
        <br><img src="{{ c.image }}" alt="Option {{ c.letter }}" loading="lazy">
        {% endif %}
      </span>
    </li>
    {% endfor %}
  </ul>
  {% endif %}

  <button class="reveal-btn" id="revBtn{{ loop.index }}" onclick="reveal({{ loop.index }})">
    Show Answer
  </button>

  <div class="answer-block" id="ans{{ loop.index }}">
    <div class="answer-label">✅ Correct Answer: {{ q.answer or 'Not available' }}</div>
    {% if q.voted_answer and q.voted_answer != q.answer %}
    <div class="voted-label">🗳 Community Voted: <b>{{ q.voted_answer }}</b></div>
    {% endif %}
  </div>

  {# ── Discussion ── #}
  {% if q.comments %}
  <button class="disc-btn" onclick="toggleDisc({{ loop.index }})">
    💬 Discussion ({{ q.comments|length }} comment{{ 's' if q.comments|length != 1 }}) — click to expand
  </button>
  <div class="disc-box" id="disc{{ loop.index }}">
    {% for c in q.comments %}
    <div class="comment">
      <div class="comment-header">
        <span>
          <span class="comment-author">{{ c.author or 'Anonymous' }}</span>
          {% if c.upvotes %}<span class="comment-votes">▲ {{ c.upvotes }}</span>{% endif %}
        </span>
        <span class="comment-date">{{ c.date or '' }}</span>
      </div>
      <div class="comment-body">{{ c.text }}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

</div>
{% endfor %}
</div>

<script>
const total = {{ questions|length }};
let revealed = new Set();
let correct = 0;
let attempted = 0;

function updateStats() {
  document.getElementById("revealedQ").textContent = revealed.size;
  document.getElementById("progressFill").style.width = (revealed.size/total*100)+"%";
  if (attempted > 0) {
    document.getElementById("scoreQ").textContent = correct + "/" + attempted + " (" + Math.round(correct/attempted*100) + "%)";
  }
}

function pickChoice(el, idx, letter) {
  // Don't allow re-picking after reveal
  if (revealed.has(idx)) return;
  el.parentElement.querySelectorAll(".choice").forEach(c => c.classList.remove("selected"));
  el.classList.add("selected");
}

function reveal(idx) {
  const block = document.getElementById("ans" + idx);
  const card = document.getElementById("q" + idx);
  const answer = card.dataset.answer;
  const isShowing = block.classList.contains("visible");

  if (isShowing) {
    block.classList.remove("visible");
    revealed.delete(idx);
    // Reset choice highlighting
    const choices = document.querySelectorAll("#choices" + idx + " .choice");
    choices.forEach(c => { c.classList.remove("correct-show","wrong-show"); });
    card.classList.remove("answered-correct","answered-wrong");
    // Recalculate score
    recalcScore();
  } else {
    block.classList.add("visible");
    revealed.add(idx);

    // Highlight correct/wrong choices
    const choices = document.querySelectorAll("#choices" + idx + " .choice");
    const answerLetters = answer.split(/[,\\s]+/).map(l => l.trim());
    let userSelected = null;

    choices.forEach(c => {
      const letter = c.dataset.letter;
      if (c.classList.contains("selected")) userSelected = letter;
      if (answerLetters.includes(letter)) {
        c.classList.add("correct-show");
      } else if (c.classList.contains("selected")) {
        c.classList.add("wrong-show");
      }
    });

    if (userSelected) {
      attempted++;
      if (answerLetters.includes(userSelected)) {
        correct++;
        card.classList.add("answered-correct");
      } else {
        card.classList.add("answered-wrong");
      }
    }
  }
  updateStats();
}

function recalcScore() {
  correct = 0; attempted = 0;
  document.querySelectorAll(".qcard").forEach(card => {
    const idx = parseInt(card.dataset.idx);
    if (!revealed.has(idx)) return;
    const answer = card.dataset.answer;
    const answerLetters = answer.split(/[,\\s]+/).map(l => l.trim());
    const selected = card.querySelector(".choice.selected");
    if (selected) {
      attempted++;
      if (answerLetters.includes(selected.dataset.letter)) correct++;
    }
  });
}

function toggleDisc(idx) {
  document.getElementById("disc" + idx).classList.toggle("visible");
}

function revealAll() {
  for (let i = 1; i <= total; i++) {
    if (!revealed.has(i)) reveal(i);
  }
}

function hideAll() {
  for (let i = total; i >= 1; i--) {
    if (revealed.has(i)) reveal(i);
  }
}

function scrollToNext() {
  for (let i = 1; i <= total; i++) {
    const card = document.getElementById("q" + i);
    if (!revealed.has(i) && card.style.display !== "none") {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
  }
}

function filterQ(query) {
  const q = query.toLowerCase();
  document.querySelectorAll(".qcard").forEach(card => {
    card.style.display = card.dataset.search.includes(q) ? "" : "none";
  });
}

// Keyboard shortcuts
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "r" || e.key === "R") {
    const cards = document.querySelectorAll(".qcard");
    for (const card of cards) {
      const r = card.getBoundingClientRect();
      if (r.top >= -100 && r.top <= window.innerHeight * 0.5) {
        reveal(parseInt(card.dataset.idx));
        break;
      }
    }
  }
  if (e.key === "ArrowDown") { e.preventDefault(); scrollToNext(); }
});
</script>
</body>
</html>
''')


def generate_html(questions: list[dict], output_path: Path, theme: str = "dark"):
    """Generate interactive HTML with structured choices, images, and discussions."""
    title = _build_title(questions)
    html = HTML_TEMPLATE.render(questions=questions, title=title, theme=theme)
    output_path.write_text(html, encoding="utf-8")


def _build_title(questions: list[dict]) -> str:
    if questions:
        t = questions[0].get("title", "")
        # Extract exam name like "AZ-400"
        import re
        m = re.search(r'([\w]+-\d+)', t, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return "Exam Questions"
