#!/usr/bin/env python3
"""
Exam Studio — Interactive exam question viewer generator.
Scrapes ExamTopics via plain HTTP (no JS = paywall bypass) and produces
interactive HTML/MD/PDF with collapsible answers and discussions.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from generators.html_generator import generate_html
from generators.md_generator import generate_markdown
from generators.pdf_generator import generate_pdf
from generators.scraper_fallback import ExamTopicsScraper

console = Console()

OUTPUT_DIR = Path("/app/output")


# ─────────────────────────────────────────────
#  DATA NORMALIZATION
# ─────────────────────────────────────────────

def normalize_question(q: dict, index: int) -> dict:
    """Normalize question into consistent structure for generators."""
    if isinstance(q.get("choices"), list) and q["choices"] and isinstance(q["choices"][0], dict):
        return q

    choices = q.get("choices", [])

    if isinstance(choices, str):
        choices = []
        for m in re.finditer(r'([A-F])\.?\s+(.+?)(?=(?:[A-F]\.?\s)|\Z)', q.get("choices", ""), re.DOTALL):
            choices.append({"letter": m.group(1), "text": m.group(2).strip(), "image": None})

    if not choices and q.get("questions"):
        qs = q["questions"]
        if isinstance(qs, str):
            for m in re.finditer(r'([A-F])\.?\s+(.+?)(?=(?:[A-F]\.?\s)|\Z)', qs, re.DOTALL):
                choices.append({"letter": m.group(1), "text": m.group(2).strip(), "image": None})
        elif isinstance(qs, list) and qs and isinstance(qs[0], str):
            for opt in qs:
                m = re.match(r'([A-F])\.?\s*(.*)', opt.strip())
                if m:
                    choices.append({"letter": m.group(1), "text": m.group(2).strip(), "image": None})

    comments = q.get("comments", [])
    if isinstance(comments, str) and comments:
        parts = re.split(r'(?:upvoted\s*\d+\s*times?|(?:Highly\s+)?Voted)', comments)
        comments = []
        for p in parts:
            p = p.strip()
            if p and len(p) > 10:
                m = re.match(r'^(\w[\w\d_]+)\s+(\d+\s+(?:months?|years?)\s+ago)\s*(.*)', p, re.DOTALL)
                if m:
                    comments.append({
                        "author": m.group(1),
                        "date": m.group(2),
                        "text": m.group(3).strip(),
                        "upvotes": 0,
                    })
                else:
                    comments.append({"author": "Anonymous", "date": "", "text": p, "upvotes": 0})
    elif isinstance(comments, list) and comments and isinstance(comments[0], str):
        comments = [{"author": "Anonymous", "date": "", "text": c, "upvotes": 0} for c in comments if c.strip()]

    return {
        "title": q.get("title", f"Question {index}"),
        "topic": q.get("topic", 0),
        "question_number": q.get("question_number", index),
        "header": q.get("header", ""),
        "content": q.get("content", ""),
        "choices": choices,
        "images": q.get("images", []),
        "answer": q.get("answer", ""),
        "voted_answer": q.get("voted_answer", ""),
        "question_link": q.get("question_link", ""),
        "comments": comments,
    }


# ─────────────────────────────────────────────
#  LIST EXAMS
# ─────────────────────────────────────────────

def list_exams(provider: str):
    """List all available exams for a provider."""
    console.print(f"\n[bold cyan]🔍 Listing exams for: {provider}[/]\n")

    exams = ExamTopicsScraper.list_exams(provider)

    if not exams:
        console.print(f"[bold red]No exams found for provider '{provider}'.[/]")
        console.print(f"[yellow]Check the URL: https://www.examtopics.com/exams/{provider}/[/]")
        sys.exit(1)

    table = Table(title=f"{provider.title()} — {len(exams)} Exams Available")
    table.add_column("#", style="dim", width=4)
    table.add_column("Exam Code", style="cyan bold")
    table.add_column("Title", style="white")
    table.add_column("Command", style="green dim")

    for i, exam in enumerate(exams, 1):
        table.add_row(
            str(i),
            exam["code"],
            exam["title"][:60],
            f"-p {provider} -s {exam['code']}",
        )

    console.print(table)
    console.print(f"\n[dim]Usage: exam-studio -p {provider} -s <exam-code> -c -f html[/]\n")
    sys.exit(0)


# ─────────────────────────────────────────────
#  SCRAPING
# ─────────────────────────────────────────────

def run_scraper(provider: str, exam: str, include_comments: bool) -> list[dict]:
    """Scrape ExamTopics using plain HTTP (no JS = paywall bypass)."""
    console.print(f"\n[bold cyan]⏳ Scraping ExamTopics...[/]")
    console.print(f"   Provider: [yellow]{provider}[/]")
    console.print(f"   Exam:     [yellow]{exam}[/]")
    console.print(f"   Comments: [yellow]{'yes' if include_comments else 'no'}[/]\n")

    scraper = ExamTopicsScraper(provider, exam, include_comments)
    data = scraper.scrape_all()

    if data:
        console.print(f"\n[bold green]✅ Scraped {len(data)} questions[/]\n")
        return [normalize_question(q, i + 1) for i, q in enumerate(data)]

    console.print("[bold red]❌ Scraping failed. Check provider/exam name.[/]")
    console.print(f"[yellow]Expected URL: https://www.examtopics.com/exams/{provider}/{exam}/[/]")
    console.print(f"[yellow]List available exams: exam-studio -p {provider} --list-exams[/]")
    sys.exit(1)


def run_from_json(json_path: str) -> list[dict]:
    """Load and normalize questions from existing JSON."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    console.print(f"[bold green]✅ Loaded {len(data)} questions from {json_path}[/]\n")
    return [normalize_question(q, i + 1) for i, q in enumerate(data)]


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Exam Studio — Generate interactive study materials from ExamTopics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available exams for a provider
  exam-studio -p microsoft --list-exams
  exam-studio -p amazon --list-exams

  # Scrape and generate interactive HTML
  exam-studio -p microsoft -s az-400 -f html

  # Scrape with comments, output all formats
  exam-studio -p amazon -s saa-c03 -c -f all

  # Use existing JSON file (instant, no scraping)
  exam-studio --json /app/output/microsoft_az-400.json -f html

  # Light theme, shuffled
  exam-studio --json /app/output/exam.json -f html --theme light --shuffle

Providers: microsoft, amazon, google, cisco, comptia, isaca, vmware, etc.
Exam codes must match the ExamTopics URL slug (lowercase).
        """,
    )

    parser.add_argument("-p", "--provider", type=str,
                        help="Exam provider (e.g., microsoft, amazon, google, cisco)")
    parser.add_argument("-s", "--exam", type=str,
                        help="Exam code (e.g., az-400, saa-c03, 200-301)")
    parser.add_argument("-c", "--comments", action="store_true",
                        help="Include discussion comments (slower but more useful)")
    parser.add_argument("-f", "--format", type=str, default="html",
                        choices=["html", "md", "pdf", "all"],
                        help="Output format (default: html)")
    parser.add_argument("-o", "--output-name", type=str, default=None,
                        help="Base name for output files (default: {provider}_{exam})")
    parser.add_argument("--json", type=str, default=None,
                        help="Path to existing JSON file (skip scraping)")
    parser.add_argument("--theme", type=str, default="dark",
                        choices=["dark", "light"],
                        help="Color theme for HTML output (default: dark)")
    parser.add_argument("--shuffle", action="store_true",
                        help="Randomize question order")
    parser.add_argument("--list-exams", action="store_true",
                        help="List available exams for the provider and exit")

    args = parser.parse_args()

    # List exams mode
    if args.list_exams:
        if not args.provider:
            console.print("[bold red]Error: --provider (-p) is required with --list-exams[/]")
            sys.exit(1)
        list_exams(args.provider)

    # Validate inputs
    if not args.json and (not args.provider or not args.exam):
        console.print("[bold red]Error: --provider (-p) and --exam (-s) are required unless --json is provided.[/]")
        parser.print_help()
        sys.exit(1)

    # Get questions
    if args.json:
        questions = run_from_json(args.json)
    else:
        questions = run_scraper(args.provider, args.exam, args.comments)

    if not questions:
        console.print("[bold red]No questions found. Exiting.[/]")
        sys.exit(1)

    # Shuffle if requested
    if args.shuffle:
        import random
        random.shuffle(questions)
        console.print("[yellow]🔀 Questions shuffled[/]")

    # Output base name
    base_name = args.output_name or f"{args.provider or 'exam'}_{args.exam or 'questions'}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate outputs
    formats = ["html", "md", "pdf"] if args.format == "all" else [args.format]

    for fmt in formats:
        try:
            if fmt == "html":
                out = OUTPUT_DIR / f"{base_name}.html"
                generate_html(questions, out, theme=args.theme)
                console.print(f"[bold green]📄 HTML → {out}[/]")
            elif fmt == "md":
                out = OUTPUT_DIR / f"{base_name}.md"
                generate_markdown(questions, out)
                console.print(f"[bold green]📄 Markdown → {out}[/]")
            elif fmt == "pdf":
                out = OUTPUT_DIR / f"{base_name}.pdf"
                generate_pdf(questions, out)
                console.print(f"[bold green]📄 PDF → {out}[/]")
        except Exception as e:
            console.print(f"[bold red]Error generating {fmt}: {e}[/]")

    # Save normalized JSON
    json_out = OUTPUT_DIR / f"{base_name}.json"
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)
    console.print(f"[bold green]📄 JSON → {json_out}[/]")

    console.print(f"\n[bold cyan]✨ Done! Files saved to {OUTPUT_DIR}[/]\n")


if __name__ == "__main__":
    main()
