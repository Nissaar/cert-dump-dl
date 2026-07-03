"""
Generates Markdown with <details> collapsible sections for answers/discussions.
Works natively on GitHub, VS Code, and many Markdown renderers.
"""

from pathlib import Path


def generate_markdown(questions: list[dict], output_path: Path):
    """Generate Markdown with collapsible answers and discussions."""
    lines = []
    lines.append("# 📝 Exam Study Guide\n")
    lines.append(f"> **Total Questions:** {len(questions)}\n")
    lines.append("> **Tip:** Click the ► arrows to reveal answers and discussions.\n")
    lines.append("---\n")

    for i, q in enumerate(questions, 1):
        title = q.get("title", f"Question {i}")
        lines.append(f"## Q{i}. {title}\n")

        if q.get("header"):
            lines.append(f"*{q['header']}*\n")

        # Question body
        body = q.get("content") or q.get("questions") or ""
        lines.append(f"{body}\n")

        # Collapsible answer
        answer = q.get("answer", "Not available")
        lines.append("<details>")
        lines.append("<summary><strong>🔑 Show Answer</strong></summary>\n")
        lines.append(f"**Answer:** {answer}\n")
        lines.append("</details>\n")

        # Collapsible discussion
        comments = q.get("comments")
        if comments:
            lines.append("<details>")
            lines.append("<summary><strong>💬 Discussion</strong></summary>\n")
            if isinstance(comments, str):
                lines.append(f"{comments}\n")
            elif isinstance(comments, list):
                for c in comments:
                    lines.append(f"- {c}")
                lines.append("")
            lines.append("</details>\n")

        # Link
        link = q.get("question_link")
        if link:
            lines.append(f"[View on ExamTopics]({link})\n")

        lines.append("---\n")

    output_path.write_text("\n".join(lines), encoding="utf-8")
