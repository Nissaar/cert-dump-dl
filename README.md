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
