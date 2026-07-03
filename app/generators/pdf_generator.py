"""
Generates a study-mode PDF using WeasyPrint.
- Questions on the page with clear numbering
- Answers grouped in a separate Answer Key section at the end
- Discussions in a third section
"""

from pathlib import Path

#from weasyprint import HTML


PDF_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @page {{
    size: A4;
    margin: 15mm;
    @bottom-center {{
      content: "Page " counter(page) " of " counter(pages);
      font-size: 9px;
      color: #888;
    }}
  }}

  body {{
    font-family: "Segoe UI", Arial, Helvetica, sans-serif;
    max-width: 100%;
    margin: 0;
    padding: 0;
    color: #222;
    line-height: 1.6;
    font-size: 11pt;
  }}

  h1 {{
    color: #d32f2f;
    border-bottom: 2px solid #d32f2f;
    padding-bottom: 0.5rem;
    font-size: 18pt;
  }}

  h2 {{
    color: #333;
    margin-top: 1.5rem;
    font-size: 14pt;
  }}

  .question-block {{
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 1rem;
    margin: 0.8rem 0;
    page-break-inside: avoid;
  }}

  .q-title {{
    font-weight: 700;
    color: #d32f2f;
    margin-bottom: 0.4rem;
    font-size: 11pt;
  }}

  .q-body {{
    margin-bottom: 0.5rem;
    white-space: pre-wrap;
  }}

  .q-body img {{
    max-width: 100%;
    margin: 0.3rem 0;
  }}

  .choices {{
    list-style: none;
    padding: 0;
    margin: 0.5rem 0;
  }}

  .choices li {{
    padding: 0.3rem 0.5rem;
    margin: 0.2rem 0;
    border-left: 3px solid #ddd;
    padding-left: 0.8rem;
  }}

  .choices li img {{
    max-width: 80%;
    margin-top: 0.2rem;
  }}

  .choice-letter {{
    font-weight: 700;
    color: #d32f2f;
    margin-right: 0.4rem;
  }}

  .separator {{
    border-top: 3px double #d32f2f;
    margin: 2rem 0 1.5rem 0;
    page-break-before: always;
  }}

  .answer-key {{
    background: #f9f9f9;
    padding: 0.6rem 1rem;
    border-radius: 6px;
    margin: 0.4rem 0;
    page-break-inside: avoid;
  }}

  .a-num {{
    font-weight: 700;
    color: #d32f2f;
  }}

  .voted {{
    color: #7b1fa2;
    font-size: 10pt;
  }}

  .meta {{
    font-size: 9pt;
    color: #888;
  }}

  .discussion {{
    font-size: 10pt;
    color: #555;
    margin-top: 0.3rem;
    border-left: 3px solid #ddd;
    padding-left: 0.8rem;
  }}

  .comment {{
    margin-bottom: 0.4rem;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid #eee;
  }}

  .comment:last-child {{
    border-bottom: none;
  }}

  .comment-author {{
    font-weight: 600;
    color: #d32f2f;
    font-size: 9pt;
  }}

  .comment-date {{
    color: #888;
    font-size: 8pt;
  }}

  a {{
    color: #1976d2;
    text-decoration: none;
  }}
</style>
</head>
<body>

<h1>📝 Exam Study Guide</h1>
<p><strong>Total Questions:</strong> {total}</p>
<p><em>Answers are at the end of this document — no peeking!</em></p>
<hr>

<h2>Questions</h2>
{questions_html}

<div class="separator"></div>

<h1>🔑 Answer Key</h1>
<p><em>Check your answers below.</em></p>
{answers_html}

{discussions_html}

</body>
</html>
"""


def generate_pdf(questions: list[dict], output_path: Path):
    """Generate a study-mode PDF with answers at the end."""

    q_parts = []
    a_parts = []
    d_parts = []

    for i, q in enumerate(questions, 1):
        title = q.get("title", f"Question {i}")
        content = q.get("content", "")
        answer = q.get("answer", "N/A")
        voted = q.get("voted_answer", "")
        link = q.get("question_link", "")
        choices = q.get("choices", [])
        images = q.get("images", [])
        comments = q.get("comments", [])

        # Build question HTML
        choices_html = ""
        if choices:
            items = []
            for c in choices:
                img_html = ""
                if c.get("image"):
                    img_html = f'<br><img src="{c["image"]}" alt="Option {c.get("letter", "")}">'
                items.append(
                    f'<li>'
                    f'<span class="choice-letter">{c.get("letter", "")}.</span>'
                    f'{c.get("text", "")}'
                    f'{img_html}'
                    f'</li>'
                )
            choices_html = f'<ul class="choices">{"".join(items)}</ul>'

        images_html = ""
        if images:
            imgs = []
            for img in images:
                b64 = img.get("base64", "")
                alt = img.get("alt", "Question image")
                if b64:
                    imgs.append(f'<img src="{b64}" alt="{alt}">')
            images_html = "".join(imgs)

        q_parts.append(
            f'<div class="question-block">'
            f'<div class="q-title">Q{i}. {title}</div>'
            f'<div class="q-body">{content}</div>'
            f'{images_html}'
            f'{choices_html}'
            f'</div>'
        )

        # Build answer key entry
        voted_html = ""
        if voted and voted != answer:
            voted_html = f' <span class="voted">| Community: {voted}</span>'

        link_html = ""
        if link:
            link_html = f'<br><a href="{link}">View on ExamTopics</a>'

        a_parts.append(
            f'<div class="answer-key">'
            f'<span class="a-num">Q{i}.</span> {answer}'
            f'{voted_html}'
            f'{link_html}'
            f'</div>'
        )

        # Build discussion entry
        if comments:
            comment_items = []
            for c in comments:
                if isinstance(c, dict):
                    author = c.get("author", "Anonymous")
                    date = c.get("date", "")
                    text = c.get("text", "")
                    comment_items.append(
                        f'<div class="comment">'
                        f'<span class="comment-author">{author}</span> '
                        f'<span class="comment-date">{date}</span>'
                        f'<br>{text}'
                        f'</div>'
                    )
                elif isinstance(c, str):
                    comment_items.append(f'<div class="comment">{c}</div>')

            d_parts.append(
                f'<div class="answer-key">'
                f'<span class="a-num">Q{i} Discussion:</span>'
                f'<div class="discussion">{"".join(comment_items)}</div>'
                f'</div>'
            )

    discussions_html = ""
    if d_parts:
        discussions_html = (
            '<div class="separator"></div>'
            '<h1>💬 Discussions</h1>'
            + "\n".join(d_parts)
        )

    full_html = PDF_HTML_TEMPLATE.format(
        total=len(questions),
        questions_html="\n".join(q_parts),
        answers_html="\n".join(a_parts),
        discussions_html=discussions_html,
    )

    #HTML(string=full_html).write_pdf(str(output_path))
    try:
      from weasyprint import HTML
      HTML(string=full_html).write_pdf(str(output_path))
    except ImportError:
      # Fallback: save as HTML if WeasyPrint isn't available
      fallback = output_path.with_suffix(".pdf.html")
      fallback.write_text(full_html, encoding="utf-8")
      raise RuntimeError(
        f"WeasyPrint not available. Saved HTML fallback to {fallback}"
     )
