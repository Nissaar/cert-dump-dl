# 📝 Exam Studio

Dockerized CLI that scrapes ExamTopics questions and generates **interactive study materials**
with hidden/collapsible answers and discussions.

## Quick Start

```bash
# Build
docker build -t exam-studio .

# Run — Interactive HTML (dark theme)
docker run --rm -v $(pwd)/output:/app/output exam-studio \
  -p microsoft -s az-104 -c -f html

# Run — All formats (HTML + Markdown + PDF)
docker run --rm -v $(pwd)/output:/app/output exam-studio \
  -p amazon -s saa-c03 -c -f all --shuffle

# List available exams
docker run --rm exam-studio -p cisco --list-exams

# Microsoft
docker run --rm --network host -v $(pwd)/output:/app/output exam-studio \
  -p microsoft -s az-400 -c -f html

docker run --rm --network host -v $(pwd)/output:/app/output exam-studio \
  -p microsoft -s az-104 -c -f html

# Amazon AWS
docker run --rm --network host -v $(pwd)/output:/app/output exam-studio \
  -p amazon -s saa-c03 -c -f html

docker run --rm --network host -v $(pwd)/output:/app/output exam-studio \
  -p amazon -s clf-c02 -c -f html

# Google Cloud
docker run --rm --network host -v $(pwd)/output:/app/output exam-studio \
  -p google -s professional-cloud-architect -c -f html

# Cisco
docker run --rm --network host -v $(pwd)/output:/app/output exam-studio \
  -p cisco -s 200-301 -c -f html

# CompTIA
docker run --rm --network host -v $(pwd)/output:/app/output exam-studio \
  -p comptia -s sy0-701 -c -f html

# Re-generate from cached JSON (instant, no scraping)
docker run --rm -v $(pwd)/output:/app/output exam-studio \
  --json /app/output/microsoft_az-400.json -f html --theme light --shuffle
```

## The HTML study app

The generated `.html` is a single self-contained file (no internet needed):

- **Practice** — one question at a time; radio-style picks for single-answer questions,
  checkboxes for "Choose two/three"; check, retry, or just reveal. Qualifiers like
  **MOST** / **LEAST** / **NOT** are highlighted. Hotspot/drag-drop questions (no choices)
  are self-graded after revealing.
- **Filters** — status (unanswered / correct / wrong / flagged), exam domains, topics,
  question type, discussion, full-text search. Combine freely.
- **In order / Shuffled** — shuffled order is seeded and remembered; *Reshuffle* (or `S`)
  gives a new order.
- **Progress** — answered/accuracy KPIs, ✓/✗ % per topic and per domain (sort weakest
  first), a *Weak spots* list with one-click "Retry wrong", and mock exam history.
- **Map** — every question as a colored square (correct / wrong / flagged / current).
- **Mock exam** — timed (defaults to 65 questions / 130 min for AWS), no feedback until
  you submit, per-domain score; survives closing the browser.
- **Resume anywhere** — answers, flags, position, filters and settings are saved in the
  browser (`localStorage`, per exam). Questions are keyed by a content hash, so progress
  survives re-scraping and regenerating. Use *Export / Import progress* to move browsers.
- **Grading** — against the community vote by default (switchable to the official answer
  in ⚙ Settings). Keyboard: `A–H` choose, `Enter` check/next, `←/→`, `N` next unanswered,
  `M` flag, `?` for all shortcuts.

Domains and topics are inferred from question wording (`app/classify.py`): exam-specific
profiles exist for `saa-c03`, `clf-c02` and `az-400`; other exams get provider-level topics.

### Notes on ExamTopics data

ExamTopics no longer shows the suggested answer or structured choices to anonymous users.
The scraper parses the inline choices, builds the **community vote** from each comment's
"Selected Answer", and fills any missing official answers/choices/images from the previous
`output/<provider>_<exam>.json` if it exists — so keep that file around between scrapes.

Set `EXAM_STUDIO_OUTPUT` to change the output folder when running outside Docker.
