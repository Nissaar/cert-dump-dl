"""
ExamTopics Scraper — 3-phase approach:

Phase 1: Exam view page 1 → total question count + first 10 questions
Phase 2: Full discussion index crawl (ALL pages, threaded) → find ALL discussion URLs
Phase 3: Scrape each discussion page (threaded) → questions + comments

Key HTML selectors (verified from live HTML dump):
  - Question card:     div.card.exam-question-card
  - Question header:   div.card-header → "Question #N" + span.question-title-topic
  - Question body:     div.card-body.question-body → p.card-text (first non-answer)
  - Choices:           li.multi-choice-item → span.multi-choice-letter[data-choice-letter]
  - Correct answer:    span.correct-answer (inside p.card-text.question-answer)
  - Correct choice:    li.multi-choice-item.correct-hidden
  - Voted answers:     div.voted-answers-tally → script[type="application/json"]
  - Comment text:      .original-comment
  - Comment author:    .comment-report-modal-username
  - Comment votes:     .voting-comment-tooltip-content

URL patterns:
  Microsoft: /discussions/microsoft/view/{id}-exam-az-400-topic-1-question-5-discussion/
  Amazon:    /discussions/amazon/view/{id}-exam-aws-certified-solutions-architect-associate-saa-c03-topic-1-question-123-discussion/
  Fallback:  If no topic-X-question-Y found, use data-id or sequential numbering
"""

import base64
import html
import json
import logging
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

BASE_URL = "https://www.examtopics.com"
ARCHIVE_CDX = "https://web.archive.org/cdx/search/cdx"
ARCHIVE_WEB = "https://web.archive.org/web"
ARCHIVE_INTERVAL = 1.0  # seconds between archive.org snapshot fetches

# All threads share one pacer: at most one request every BASE_INTERVAL seconds,
# stretched (up to MAX_INTERVAL) whenever ExamTopics answers 429 / a challenge.
BASE_INTERVAL = 1.0
MAX_INTERVAL = 6.0
INDEX_WORKERS = 3
DISC_WORKERS = 4


class ExamTopicsScraper:
    def __init__(self, provider: str, exam_code: str, include_comments: bool = True,
                 crawl_index: bool = True):
        self.provider = provider.lower().strip()
        self.exam_code = exam_code.lower().strip()
        self.include_comments = include_comments
        self._image_cache: dict[str, str] = {}
        self._image_lock = threading.Lock()
        self._progress_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._interval = BASE_INTERVAL
        self._next_slot = 0.0
        self._failed_pages: list[int] = []
        self.crawl_index = crawl_index
        self._archive_lock = threading.Lock()
        self._archive_next = 0.0
        self._urls_found = 0
        self._questions_scraped = 0

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(HEADERS)
        return s

    # ═════════════════════════════════════════════
    #  PUBLIC API
    # ═════════════════════════════════════════════

    def scrape_all(self) -> list[dict]:
        """
        3-phase scrape:
          1. Exam view page 1 → total question count + preview
          2. Discussion index crawl → ALL discussion URLs for this exam
          3. Scrape each discussion page → question card + comments
        Merge uses URL as unique key (not topic/question number).
        """

        # ── Phase 1 ──
        logger.info("Phase 1: Fetching exam overview...")
        first_10, total_expected = self._scrape_exam_view_page1()
        logger.info(f"  Got {len(first_10)} preview questions, {total_expected} total expected\n")

        # ── Phase 2 ──
        # The live discussion index only lists a fraction of an exam's
        # discussions, so URLs are also discovered from the Internet Archive.
        logger.info("Phase 2a: Discovering discussion URLs from the Internet Archive...")
        archive_urls = self._discover_from_archive()
        logger.info(f"  Archive: {len(archive_urls)} usable discussion URLs\n")

        index_urls: list[str] = []
        if self.crawl_index:
            logger.info("Phase 2b: Crawling live discussion index (catches the newest questions)...")
            logger.info("  (This crawls every page — typically 20-40 minutes; skip with --skip-index)\n")
            index_urls = self._crawl_full_discussion_index()
        disc_urls = self._dedupe_by_id(archive_urls + index_urls)
        logger.info(f"\n  Found {len(disc_urls)} discussion URLs total\n")

        if not disc_urls and not first_10:
            return []

        if not disc_urls:
            logger.warning("  No discussion URLs found — returning exam page preview only")
            return first_10

        # ── Phase 3 ──
        logger.info(f"Phase 3: Scraping {len(disc_urls)} discussion pages...")
        disc_questions = self._scrape_all_discussions(disc_urls)
        logger.info(f"  Scraped {len(disc_questions)} questions from discussions\n")

        # ── Merge using URL as primary key ──
        merged: dict[str, dict] = {}

        # Add Phase 1 questions (keyed by constructed discussion URL)
        for q in first_10:
            key = self._make_merge_key(q)
            merged[key] = q

        # Override with discussion versions (they include comments)
        for q in disc_questions:
            key = self._make_merge_key(q)
            merged[key] = q

        # Sort by topic, then question number; unnumbered ones last, ordered
        # by discussion id so the order is deterministic across runs
        def sort_key(q):
            qn = q.get("question_number", 0)
            m = re.search(r"/view/(\d+)-", q.get("question_link", ""))
            return (qn == 0, q.get("topic", 0), qn, int(m.group(1)) if m else 0)

        result = sorted(merged.values(), key=sort_key)

        # Re-number sequentially if topic/question numbers are all zero
        all_zero = all(
            q.get("topic", 0) == 0 and q.get("question_number", 0) == 0
            for q in result
        )
        if all_zero:
            for i, q in enumerate(result, 1):
                q["question_number"] = i
                q["title"] = f"Exam {self.exam_code.upper()} question {i}"

        logger.info(f"  Final: {len(result)} unique questions")
        return result

    @staticmethod
    def list_exams(provider: str) -> list[dict]:
        """
        List all available exams for a provider.
        Scrapes https://www.examtopics.com/exams/{provider}/
        """
        session = requests.Session()
        session.headers.update(HEADERS)

        url = f"{BASE_URL}/exams/{provider.lower().strip()}/"
        try:
            resp = session.get(url, timeout=30)
        except requests.RequestException as e:
            logger.error(f"  Cannot reach {url}: {e}")
            return []

        if resp.status_code != 200:
            logger.error(f"  HTTP {resp.status_code} from {url}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        exams = []
        # ExamTopics lists exams as cards/links under /exams/{provider}/
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Match pattern: /exams/{provider}/{exam-code}/
            m = re.match(
                rf'/exams/{re.escape(provider.lower().strip())}/([a-z0-9\-]+)/',
                href.lower(),
            )
            if not m:
                continue

            exam_code = m.group(1)
            if exam_code in ("view", "custom-view"):
                continue  # Skip non-exam links

            # Get exam title from link text or parent
            title = a.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            # Avoid duplicates
            if any(e["code"] == exam_code for e in exams):
                continue

            exams.append({
                "code": exam_code,
                "title": title,
                "url": urljoin(BASE_URL, href),
            })

        return exams

    def _make_merge_key(self, q: dict) -> str:
        """
        Create a unique key for merging questions.
        Prefer URL → data_id → topic+question_number.
        """
        # Best: normalize URL
        url = q.get("question_link", "")
        if url:
            # Strip base URL, normalize
            return url.lower().rstrip("/")

        # Fallback: data-id from card body
        data_id = q.get("data_id", "")
        if data_id:
            return f"dataid-{data_id}"

        # Last resort: topic + question number (but only if nonzero)
        t = q.get("topic", 0)
        n = q.get("question_number", 0)
        if t > 0 or n > 0:
            return f"t{t}-q{n}"

        # Absolute fallback: hash of content
        content = q.get("content", "")
        return f"content-{hash(content[:200])}"

    # ═════════════════════════════════════════════
    #  PHASE 1: EXAM VIEW PAGE 1
    # ═════════════════════════════════════════════

    def _scrape_exam_view_page1(self) -> tuple[list[dict], int]:
        session = self._make_session()
        url = f"{BASE_URL}/exams/{self.provider}/{self.exam_code}/view/"
        resp = self._fetch_with_session(session, url)
        if not resp:
            return [], 0

        soup = BeautifulSoup(resp.text, "html.parser")
        total = self._extract_total_count(resp.text)

        cards = soup.select("div.card.exam-question-card")
        questions = []
        for card in cards:
            q = self._parse_question_card(card)
            if q:
                questions.append(q)
        return questions, total

    def _extract_total_count(self, html: str) -> int:
        for pattern in [
            r'out\s+of\s+(\d+)\s+question',
            r'"marked">(\d+)</span>\s*<span>\s*Questions',
            r'(\d+)\s*</span>\s*<span>\s*Questions\s*(?:&amp;|&)\s*Answers',
        ]:
            m = re.search(pattern, html)
            if m:
                return int(m.group(1))
        return 0

    # ═════════════════════════════════════════════
    #  PHASE 2: FULL DISCUSSION INDEX CRAWL
    # ═════════════════════════════════════════════

    # ═════════════════════════════════════════════
    #  PHASE 2a: ARCHIVE DISCOVERY
    # ═════════════════════════════════════════════

    _FULL_URL = re.compile(r"/view/(\d+)-exam-(.+?)-topic-(\d+)-question-(\d+)-discussion/?$")
    _SHORT_URL = re.compile(r"/view/(\d+)-exam-(.+?)/?$")

    def _cdx(self, extra: str) -> list[list[str]]:
        """Query the Wayback Machine CDX index for this exam's discussion URLs."""
        url = (f"{ARCHIVE_CDX}?url=examtopics.com/discussions/{self.provider}/view/"
               f"&matchType=prefix&filter=original:.*{re.escape(self.exam_code)}.*"
               f"&collapse=urlkey&output=json&limit=200000{extra}")
        session = self._make_session()
        for attempt in range(4):
            try:
                resp = session.get(url, timeout=180)
                if resp.status_code == 200:
                    rows = resp.json() if resp.text.strip() else []
                    return rows[1:]  # first row is the header
                logger.warning(f"  Archive CDX HTTP {resp.status_code}, retrying...")
            except (requests.RequestException, ValueError) as e:
                logger.warning(f"  Archive CDX error: {e}")
            time.sleep(10 * (attempt + 1))
        return []

    def _discover_from_archive(self) -> list[str]:
        """
        Full URLs (…-topic-T-question-N-discussion/) are used as-is. Short URLs
        (…-exam-<slug>/, which the live site now 404s) are resolved to full URLs by
        reading the question number from one archived copy of the page.
        """
        rows = self._cdx("&fl=original")
        if not rows:
            logger.warning("  Archive has no URLs for this exam (or is unreachable)")
            return []

        full: dict[str, str] = {}
        short: dict[str, str] = {}
        for (orig,) in rows:
            path = urlparse(orig).path
            m = self._FULL_URL.search(path)
            if m:
                full[m.group(1)] = f"{BASE_URL}/discussions/{self.provider}{path[path.index('/view/'):]}".rstrip("/") + "/"
                continue
            m = self._SHORT_URL.search(path)
            if m and m.group(1) not in full:
                short[m.group(1)] = m.group(2)
        short = {i: slug for i, slug in short.items() if i not in full}
        logger.info(f"  {len(full)} full URLs, {len(short)} short URLs to resolve")

        if short:
            snaps = {}
            for ts, orig in self._cdx("&fl=timestamp,original&filter=statuscode:200"):
                m = self._SHORT_URL.search(urlparse(orig).path)
                if m and m.group(1) in short:
                    snaps[m.group(1)] = (ts, orig)
            logger.info(f"  {len(snaps)} short URLs have an archived copy — reading question numbers...")
            resolved = 0
            with ThreadPoolExecutor(max_workers=2) as ex:
                futures = {ex.submit(self._resolve_short, i, short[i], *snaps[i]): i for i in snaps}
                for f in as_completed(futures):
                    url = f.result()
                    if url:
                        full[futures[f]] = url
                        resolved += 1
                        if resolved % 50 == 0:
                            logger.info(f"  Resolved {resolved}/{len(snaps)}...")
            logger.info(f"  Resolved {resolved} short URLs "
                        f"({len(short) - resolved} unresolved — the previous JSON covers those)")
        return list(full.values())

    def _resolve_short(self, disc_id: str, slug: str, ts: str, orig: str) -> str | None:
        with self._archive_lock:
            wait = self._archive_next - time.monotonic()
            self._archive_next = max(time.monotonic(), self._archive_next) + ARCHIVE_INTERVAL
        if wait > 0:
            time.sleep(wait)
        session = self._make_session()
        for attempt in range(3):
            try:
                resp = session.get(f"{ARCHIVE_WEB}/{ts}id_/{orig}", timeout=60)
                if resp.status_code == 200:
                    text = resp.text
                    m = (re.search(r"topic\s+(\d+)\s+question\s+(\d+)\s+discussion", text, re.IGNORECASE)
                         or re.search(r"Topic\s*#:\s*(\d+).*?Question\s*#:\s*(\d+)", text, re.S))
                    if not m:
                        qm = re.search(r"Question\s*#:\s*(\d+)", text)
                        tm = re.search(r"Topic\s*#:\s*(\d+)", text)
                        if not qm:
                            return None
                        topic, qnum = (tm.group(1) if tm else "1"), qm.group(1)
                    else:
                        topic, qnum = m.group(1), m.group(2)
                    return (f"{BASE_URL}/discussions/{self.provider}/view/{disc_id}-exam-{slug}"
                            f"-topic-{topic}-question-{qnum}-discussion/")
                if resp.status_code in (404, 403):
                    return None
            except requests.RequestException:
                pass
            time.sleep(5 * (attempt + 1))
        return None

    def _dedupe_by_id(self, urls: list[str]) -> list[str]:
        """One URL per discussion id, preferring the full (current) URL form."""
        best: dict[str, str] = {}
        for u in urls:
            m = re.search(r"/view/(\d+)-", u)
            key = m.group(1) if m else u
            if key not in best or ("-question-" in u and "-question-" not in best[key]):
                best[key] = u
        return sorted(best.values())

    def _crawl_full_discussion_index(self) -> list[str]:
        session = self._make_session()
        first_url = f"{BASE_URL}/discussions/{self.provider}/"
        resp = self._fetch_with_session(session, first_url)
        if not resp:
            logger.error("  Cannot reach discussion index")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        if self._is_challenge_page(resp.text):
            logger.error("  Cloudflare challenge on discussion index")
            return []

        max_pages = self._get_max_discussion_pages(soup)
        logger.info(f"  Discussion index has {max_pages} pages to scan")

        all_urls: set[str] = set()
        page1_links = self._extract_exam_links(soup)
        all_urls.update(page1_links)
        if page1_links:
            logger.info(f"  Page 1: +{len(page1_links)} URLs")

        self._urls_found = len(all_urls)

        remaining = list(range(2, max_pages + 1))
        if not remaining:
            return sorted(all_urls)

        batch_size = max(1, len(remaining) // INDEX_WORKERS + 1)
        batches = [remaining[i:i + batch_size]
                    for i in range(0, len(remaining), batch_size)]

        logger.info(f"  Launching {len(batches)} workers across {len(remaining)} pages...\n")

        with ThreadPoolExecutor(max_workers=INDEX_WORKERS) as executor:
            futures = {
                executor.submit(self._crawl_index_batch, batch, max_pages): i
                for i, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                try:
                    batch_urls = future.result()
                    all_urls.update(batch_urls)
                except Exception as e:
                    logger.error(f"  Index batch error: {e}")

        if self._failed_pages:
            logger.warning(f"  ⚠ {len(self._failed_pages)} index pages could not be fetched "
                           f"(rate limited) — some questions may be missing; "
                           f"the previous JSON fills the gaps")
        return sorted(all_urls)

    def _crawl_index_batch(self, pages: list[int], max_pages: int) -> set[str]:
        session = self._make_session()
        results: set[str] = set()

        for page_num in pages:
            url = f"{BASE_URL}/discussions/{self.provider}/{page_num}"
            resp = self._fetch_with_session(session, url)

            if not resp:
                with self._progress_lock:
                    self._failed_pages.append(page_num)
            if resp:
                soup = BeautifulSoup(resp.text, "html.parser")
                found = self._extract_exam_links(soup)
                results.update(found)
                if found:
                    with self._progress_lock:
                        self._urls_found += len(found)

            if page_num % 100 == 0:
                with self._progress_lock:
                    logger.info(
                        f"  Page {page_num}/{max_pages}: "
                        f"{self._urls_found} URLs found so far..."
                    )


        return results

    def _extract_exam_links(self, soup: BeautifulSoup) -> set[str]:
        """
        Find all discussion links matching this exam code.
        Handles both URL patterns:
          - /view/{id}-exam-az-400-topic-...
          - /view/{id}-exam-aws-certified-solutions-architect-associate-saa-c03-topic-...
        """
        links: set[str] = set()
        exam_lower = self.exam_code

        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            # Must contain our exam code AND be a discussion view link
            if exam_lower in href and "/view/" in href:
                full_url = urljoin(BASE_URL, a["href"])
                full_url = full_url.split("?")[0].split("#")[0]
                if not full_url.endswith("/"):
                    full_url += "/"
                links.add(full_url)

        return links

    def _get_max_discussion_pages(self, soup: BeautifulSoup) -> int:
        indicators = soup.select(".discussion-list-page-indicator strong")
        if len(indicators) >= 2:
            try:
                return int(indicators[1].get_text(strip=True))
            except ValueError:
                pass

        max_page = 1
        for a in soup.select("a[href]"):
            m = re.search(r'/discussions/\w+/(\d+)', a.get("href", ""))
            if m:
                max_page = max(max_page, int(m.group(1)))

        for text_node in soup.find_all(string=re.compile(r'of\s+\d+')):
            m = re.search(r'of\s+(\d+)', str(text_node))
            if m:
                val = int(m.group(1))
                if 1 < val < 100000:
                    max_page = max(max_page, val)

        return max_page if max_page > 1 else 500

    # ═════════════════════════════════════════════
    #  PHASE 3: SCRAPE DISCUSSION PAGES
    # ═════════════════════════════════════════════

    def _scrape_all_discussions(self, urls: list[str]) -> list[dict]:
        questions: list[dict] = []
        total = len(urls)
        self._questions_scraped = 0

        with ThreadPoolExecutor(max_workers=DISC_WORKERS) as executor:
            futures = {
                executor.submit(self._scrape_one_discussion, url): url
                for url in urls
            }
            for future in as_completed(futures):
                try:
                    q = future.result()
                    if q:
                        questions.append(q)
                        with self._progress_lock:
                            self._questions_scraped += 1
                            if self._questions_scraped % 50 == 0:
                                logger.info(
                                    f"  Progress: {self._questions_scraped}/{total} "
                                    f"questions scraped..."
                                )
                except Exception as e:
                    logger.error(f"  Discussion scrape error: {e}")

        return questions

    def _scrape_one_discussion(self, url: str) -> dict | None:
        session = self._make_session()
        resp = self._fetch_with_session(session, url)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        if self._is_challenge_page(resp.text):
            return None

        card = soup.select_one("div.card.exam-question-card")
        if card:
            q = self._parse_question_card(card)
        else:
            # Current layout: header container + question-body with inline choices
            q = self._parse_discussion_question(soup)
        if not q:
            return None

        # Set the actual URL
        q["question_link"] = url

        # Extract topic/question from URL (multiple patterns)
        topic, qnum = self._extract_topic_question_from_url(url)
        if topic > 0 or qnum > 0:
            q["topic"] = topic
            q["question_number"] = qnum
            q["title"] = (
                f"Exam {self.exam_code.upper()} "
                f"topic {topic} question {qnum}"
            )

        # Parse comments (always: the community vote tally is built from them)
        comments = self._parse_comments(soup)
        if not q.get("vote_data"):
            vote_data = self._tally_votes(comments)
            if vote_data:
                q["vote_data"] = vote_data
                q["voted_answer"] = vote_data[0]["voted_answers"]
        q["discussion_count"] = q.get("discussion_count") or len(comments)
        if self.include_comments:
            q["comments"] = comments

        return q

    @staticmethod
    def _tally_votes(comments: list[dict]) -> list[dict]:
        """Community vote from 'Selected Answer' badges, one vote per author."""
        by_author: dict[str, str] = {}
        for i, c in enumerate(comments):
            sel = c.get("selected_answer")
            if sel:
                by_author.setdefault(c.get("author") or f"anon{i}", sel)
        counts: dict[str, int] = {}
        for sel in by_author.values():
            counts[sel] = counts.get(sel, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])
        return [
            {"voted_answers": a, "vote_count": n, "is_most_voted": i == 0}
            for i, (a, n) in enumerate(ranked)
        ]

    def _parse_discussion_question(self, soup: BeautifulSoup) -> dict | None:
        """
        Parse the current discussion-page layout:
          div.discussion-header-container
            "Question #: 7  Topic #: 1"
            div.question-body[data-id] > p.card-text  (stem + "A. ..." choices inline)
        """
        body = soup.select_one("div.discussion-header-container div.question-body") \
            or soup.select_one("div.question-body")
        if not body:
            return None
        p = body.select_one("p.card-text") or body

        lines, images = self._walk_lines(p)
        stem_lines: list[str] = []
        choices: list[dict] = []
        for line in lines:
            expected = chr(ord(choices[-1]["letter"]) + 1) if choices else "A"
            m = re.match(r"^([A-H])\.\s*(.*)$", line)
            if m and m.group(1) == expected:
                choices.append({"letter": m.group(1), "text": m.group(2).strip(),
                                "image": None, "is_correct": False})
            elif choices:
                choices[-1]["text"] = (choices[-1]["text"] + "\n" + line).strip()
            else:
                stem_lines.append(line)

        topic_num, q_num = 0, 0
        header = soup.select_one("div.discussion-header-container")
        if header:
            ht = header.get_text(" ", strip=True)
            m = re.search(r"Question\s*#:?\s*(\d+)", ht)
            if m:
                q_num = int(m.group(1))
            m = re.search(r"Topic\s*#:?\s*(\d+)", ht)
            if m:
                topic_num = int(m.group(1))

        return {
            "title": f"Exam {self.exam_code.upper()} topic {topic_num} question {q_num}",
            "topic": topic_num,
            "question_number": q_num,
            "header": "",
            "content": "\n".join(stem_lines).strip(),
            "choices": choices,
            "images": images,
            "answer": "",
            "voted_answer": "",
            "vote_data": [],
            "question_link": "",
            "discussion_count": 0,
            "data_id": body.get("data-id", ""),
            "comments": [],
        }

    def _walk_lines(self, el: Tag) -> tuple[list[str], list[dict]]:
        """
        Flatten an element into text lines split on <br>, collecting images.
        Recurses into <br> too: html.parser nests content inside unclosed <br>.
        """
        buf: list[str] = []
        images: list[dict] = []

        def walk(node):
            for child in node.children:
                if isinstance(child, NavigableString):
                    if isinstance(child, Comment):
                        continue
                    buf.append(str(child))
                elif isinstance(child, Tag):
                    if child.name == "br":
                        buf.append("\n")
                        walk(child)
                    elif child.name == "img":
                        idata = self._process_image(child)
                        if idata:
                            images.append(idata)
                    elif child.name in ("a",) and "btn" in (child.get("class") or []):
                        continue
                    else:
                        if child.name in ("p", "div", "li"):
                            buf.append("\n")
                        walk(child)
                        if child.name in ("p", "div", "li"):
                            buf.append("\n")

        walk(el)
        text = "".join(buf)
        lines = [re.sub(r"[ \t\r\f\v ]+", " ", ln).strip() for ln in text.split("\n")]
        return [ln for ln in lines if ln], images

    def _extract_topic_question_from_url(self, url: str) -> tuple[int, int]:
        """
        Extract topic and question numbers from various URL patterns:
          - exam-az-400-topic-1-question-5-discussion
          - exam-aws-certified-solutions-architect-associate-saa-c03-topic-1-question-123-discussion
          - Sometimes just question-123 without topic
        """
        url_lower = url.lower()

        # Pattern 1: topic-N-question-N (most common)
        m = re.search(r'topic-(\d+)-question-(\d+)', url_lower)
        if m:
            return int(m.group(1)), int(m.group(2))

        # Pattern 2: question-N without topic
        m = re.search(r'question-(\d+)', url_lower)
        if m:
            return 0, int(m.group(1))

        # Pattern 3: try to find any two numbers near end of URL
        # e.g., /view/12345-exam-...-1-5-discussion/
        parts = url_lower.rstrip("/").split("/")
        if parts:
            last = parts[-1]
            numbers = re.findall(r'(\d+)', last)
            if len(numbers) >= 3:
                # First number is the discussion ID, last two might be topic+question
                # But this is unreliable, so only use if we find topic/question keywords nearby
                pass

        return 0, 0

    # ═════════════════════════════════════════════
    #  QUESTION CARD PARSER
    # ═════════════════════════════════════════════

    def _parse_question_card(self, card: Tag) -> dict | None:
        """Parse one div.card.exam-question-card into structured data."""

        # ── Header ──
        q_num = 0
        topic_num = 0
        header_el = card.select_one("div.card-header")
        if header_el:
            header_text = header_el.get_text(strip=True)
            m = re.search(r'Question\s*#?(\d+)', header_text)
            if m:
                q_num = int(m.group(1))
            topic_el = header_el.select_one("span.question-title-topic")
            if topic_el:
                m = re.search(r'Topic\s*(\d+)', topic_el.get_text(strip=True))
                if m:
                    topic_num = int(m.group(1))

        # ── Question body ──
        body_el = (
            card.select_one("div.card-body.question-body")
            or card.select_one("div.card-body")
            or card
        )

        content = ""
        content_images = []

        for p in body_el.select("p.card-text"):
            p_classes = " ".join(p.get("class", []))
            if "question-answer" in p_classes:
                continue
            content = "\n".join(self._walk_lines(p)[0])
            for img in p.find_all("img"):
                img_data = self._process_image(img)
                if img_data:
                    content_images.append(img_data)
            break

        # Standalone images in question body
        if body_el != card:
            for child in body_el.children:
                if isinstance(child, Tag) and child.name == "img":
                    img_data = self._process_image(child)
                    if img_data:
                        content_images.append(img_data)

        # Images in choices container but outside <li>
        choices_container = card.select_one("div.question-choices-container")
        if choices_container:
            for img in choices_container.find_all("img", recursive=False):
                img_data = self._process_image(img)
                if img_data:
                    content_images.append(img_data)

        # ── Choices ──
        choices = []
        for li in card.select("li.multi-choice-item"):
            letter = ""
            letter_span = li.select_one("span.multi-choice-letter")
            if letter_span:
                letter = letter_span.get("data-choice-letter", "")
                if not letter:
                    letter = letter_span.get_text(strip=True).rstrip(".")

            parts = []
            choice_img = None
            for child in li.children:
                if isinstance(child, Tag):
                    child_classes = " ".join(child.get("class", []))
                    if "multi-choice-letter" in child_classes:
                        continue
                    if child.name == "img":
                        idata = self._process_image(child)
                        if idata:
                            choice_img = idata.get("base64")
                    else:
                        inner_img = child.find("img")
                        if inner_img:
                            idata = self._process_image(inner_img)
                            if idata:
                                choice_img = idata.get("base64")
                        parts.append(child.get_text(strip=True))
                elif isinstance(child, NavigableString):
                    t = child.strip()
                    if t:
                        parts.append(t)

            choice_text = " ".join(parts).strip()
            is_correct = "correct-hidden" in " ".join(li.get("class", []))

            if letter or choice_text or choice_img:
                choices.append({
                    "letter": letter.upper(),
                    "text": choice_text,
                    "image": choice_img,
                    "is_correct": is_correct,
                })

        # ── Correct answer ──
        answer = ""
        answer_el = card.select_one("span.correct-answer")
        if answer_el:
            answer = answer_el.get_text(strip=True)
        if not answer:
            correct_letters = [c["letter"] for c in choices if c.get("is_correct")]
            if correct_letters:
                answer = ", ".join(correct_letters)

        # ── Voted answers ──
        voted_answer = ""
        vote_data = []
        tally_script = card.select_one("div.voted-answers-tally script")
        if tally_script and tally_script.string:
            try:
                vote_data = json.loads(tally_script.string.strip())
                for v in vote_data:
                    if v.get("is_most_voted"):
                        voted_answer = v.get("voted_answers", "")
                        break
                if not voted_answer and vote_data:
                    voted_answer = vote_data[0].get("voted_answers", "")
            except (json.JSONDecodeError, TypeError):
                pass

        # ── Discussion count ──
        disc_count = 0
        disc_btn = card.select_one("a.question-discussion-button")
        if disc_btn:
            badge = disc_btn.select_one("span.badge")
            if badge:
                try:
                    disc_count = int(badge.get_text(strip=True))
                except ValueError:
                    pass

        # ── Data ID ──
        data_id = ""
        body_div = card.select_one("div.card-body[data-id]")
        if body_div:
            data_id = body_div.get("data-id", "")

        title = f"Exam {self.exam_code.upper()} topic {topic_num} question {q_num}"

        return {
            "title": title,
            "topic": topic_num,
            "question_number": q_num,
            "header": "",
            "content": content,
            "choices": choices,
            "images": content_images,
            "answer": answer,
            "voted_answer": voted_answer,
            "vote_data": vote_data,
            "question_link": "",
            "discussion_count": disc_count,
            "data_id": data_id,
            "comments": [],
        }

    # ═════════════════════════════════════════════
    #  COMMENT PARSER
    # ═════════════════════════════════════════════

    def _parse_comments(self, soup: BeautifulSoup) -> list[dict]:
        """
        Parse discussion comments from a discussion page.
        Anchors on .original-comment elements (the actual comment text),
        walks UP the DOM to find metadata.
        """
        containers = soup.select("div.comment-container")
        if containers:
            return self._parse_comment_containers(containers)

        comments = []
        original_comments = soup.select(".original-comment")
        if not original_comments:
            return []

        for oc in original_comments:
            text = oc.get_text(strip=True)
            if not text or len(text) < 5:
                continue

            # Walk up to find comment container
            container = oc
            for _ in range(8):
                if (container.parent
                    and container.parent.name in ("div", "article", "section")):
                    container = container.parent
                    child_divs = container.find_all("div", recursive=False)
                    if len(child_divs) >= 2:
                        break
                elif container.parent:
                    container = container.parent
                else:
                    break

            # Author
            author = ""
            for sel in [
                ".comment-report-modal-username",
                "span[class*='username']",
                "a[class*='username']",
                ".comment-username",
                ".comment-author",
            ]:
                el = container.select_one(sel)
                if el:
                    author = el.get_text(strip=True)
                    if author:
                        break

            # Date
            date = ""
            for el in container.find_all(["span", "small", "time", "div"]):
                el_text = el.get_text(strip=True)
                if re.search(
                    r'\d+\s+(months?|years?|days?|hours?|weeks?|minutes?)\s+ago',
                    el_text,
                ):
                    date = el_text
                    break

            # Upvotes
            upvotes = 0
            for sel in [
                ".upvote-count",
                "span[class*='upvote']",
                ".voting-comment-tooltip-content",
            ]:
                el = container.select_one(sel)
                if el:
                    m = re.search(r'(\d+)', el.get_text(strip=True))
                    if m:
                        upvotes = int(m.group(1))
                    break

            # Badge
            badge = ""
            for sel in [".badge", "span[class*='badge']"]:
                el = container.select_one(sel)
                if el:
                    badge_text = el.get_text(strip=True).lower()
                    if "highly voted" in badge_text:
                        badge = "highly_voted"
                    elif "most recent" in badge_text:
                        badge = "most_recent"
                    break

            comments.append({
                "author": author or "Anonymous",
                "date": date,
                "text": text[:3000],
                "upvotes": upvotes,
                "badge": badge,
            })

        # Deduplicate
        seen: set[str] = set()
        unique = []
        for c in comments:
            key = c["text"][:100]
            if key not in seen:
                seen.add(key)
                unique.append(c)

        # Sort: highly voted first, then by upvotes
        unique.sort(
            key=lambda c: (
                0 if c.get("badge") == "highly_voted" else 1,
                -c.get("upvotes", 0),
            )
        )
        return unique

    def _parse_comment_containers(self, containers: list[Tag]) -> list[dict]:
        """
        Current layout (one per comment, replies nested in div.comment-replies):
          div.media.comment-container[data-comment-id]
            .media-body > div:first  → h5.comment-username, span.comment-date, span.badge (Highly Voted)
            .media-body > .comment-body → div.badge "Selected Answer: AB", div.comment-content,
                                          span.upvote-count "12 times"
        Returned in page order (threads stay together); replies carry parent_id.
        """
        comments = []
        stack: list[tuple[int, str]] = []
        for cont in containers:
            body = cont.find("div", class_="media-body", recursive=False)
            if not body:
                continue
            head = body.find("div", recursive=False)
            cbody = body.find("div", class_="comment-body", recursive=False)
            content = cbody.find("div", class_="comment-content", recursive=False) if cbody else None
            if not content:
                continue
            text = html.unescape("\n".join(self._walk_lines(content)[0]).strip())
            if not text:
                continue

            author_el = head.select_one(".comment-username") if head else None
            date_el = head.select_one(".comment-date") if head else None
            badges = [b.get_text(" ", strip=True).lower() for b in head.select(".badge")] if head else []
            badge = ""
            if any("highly voted" in b for b in badges):
                badge = "highly_voted"
            elif any("most recent" in b for b in badges):
                badge = "most_recent"

            selected = ""
            if cbody:
                for b in cbody.find_all("div", class_="badge", recursive=False):
                    m = re.search(r"Selected Answer:\s*([A-H]+)", b.get_text(" ", strip=True))
                    if m:
                        selected = "".join(sorted(set(m.group(1).upper())))
                        break

            upvotes = 0
            up_el = cbody.select_one(".comment-control .upvote-count") if cbody else None
            if up_el:
                m = re.search(r"(\d+)", up_el.get_text(strip=True))
                if m:
                    upvotes = int(m.group(1))

            # Replies are flat siblings indented by 30px per level
            m = re.search(r"margin-left:\s*(\d+)px", cont.get("style", ""))
            depth = int(m.group(1)) // 30 if m else 0
            while stack and stack[-1][0] >= depth:
                stack.pop()
            parent_id = stack[-1][1] if stack else ""
            cid = cont.get("data-comment-id", "")
            stack.append((depth, cid))
            comments.append({
                "id": cid,
                "parent_id": parent_id,
                "depth": depth,
                "author": (author_el.get_text(strip=True) if author_el else "") or "Anonymous",
                "date": date_el.get_text(strip=True) if date_el else "",
                "date_full": date_el.get("title", "") if date_el else "",
                "text": text[:4000],
                "upvotes": upvotes,
                "badge": badge,
                "selected_answer": selected,
            })
        return comments

    # ═════════════════════════════════════════════
    #  TEXT / IMAGE HELPERS
    # ═════════════════════════════════════════════

    def _element_to_text(self, el: Tag) -> str:
        parts = []
        for child in el.children:
            if isinstance(child, NavigableString):
                parts.append(str(child).strip())
            elif isinstance(child, Tag):
                if child.name == "br":
                    parts.append("\n")
                elif child.name == "img":
                    pass
                elif child.name in ("code", "pre"):
                    parts.append(f"`{child.get_text()}`")
                else:
                    parts.append(child.get_text())
        return "".join(parts).strip()

    def _process_image(self, img: Tag) -> dict | None:
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            return None
        for attr in ("width", "height"):
            val = img.get(attr, "")
            if val and val.isdigit() and int(val) < 20:
                return None
        skip = [
            "avatar", "icon", "logo", "favicon", "tracking",
            "pixel", "facebook", "tr?", "badge", "1x1", "spacer",
        ]
        if any(s in src.lower() for s in skip):
            return None
        b64 = self._download_image_base64(src)
        if not b64:
            return None
        return {"src_original": src, "base64": b64, "alt": img.get("alt", "")}

    def _download_image_base64(self, src: str) -> str | None:
        with self._image_lock:
            if src in self._image_cache:
                return self._image_cache[src]
        full_url = urljoin(BASE_URL, src)
        try:
            session = self._make_session()
            resp = session.get(full_url, timeout=15)
            if resp.status_code != 200 or len(resp.content) < 100:
                return None
            ct = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
            b64 = base64.b64encode(resp.content).decode("utf-8")
            data_uri = f"data:{ct};base64,{b64}"
            with self._image_lock:
                self._image_cache[src] = data_uri
            return data_uri
        except Exception:
            return None

    # ═════════════════════════════════════════════
    #  HTTP HELPER
    # ═════════════════════════════════════════════

    def _is_challenge_page(self, html: str) -> bool:
        snippet = html[:3000].lower()
        return any(
            ind in snippet
            for ind in [
                "cf-browser-verification", "challenge-platform",
                "jschl-answer", "just a moment", "checking your browser",
            ]
        )

    def _throttle(self):
        """Shared pacing across all worker threads (ExamTopics rate-limits per IP)."""
        with self._rate_lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        if slot > now:
            time.sleep(slot - now)

    def _backoff(self, seconds: float):
        """Slow everyone down after a 429/challenge, then pause this thread."""
        with self._rate_lock:
            self._interval = min(self._interval * 1.5, MAX_INTERVAL)
            self._next_slot = max(self._next_slot, time.monotonic() + seconds)
        time.sleep(seconds)

    def _fetch_with_session(
        self, session: requests.Session, url: str, retries: int = 6,
    ) -> requests.Response | None:
        for attempt in range(retries):
            self._throttle()
            try:
                resp = session.get(url, timeout=30)
                if resp.status_code == 200 and self._is_challenge_page(resp.text):
                    wait = min(15 * 2 ** attempt, 300)
                    logger.warning(f"  Cloudflare challenge → pausing {wait}s...")
                    self._backoff(wait)
                    continue
                if resp.status_code == 200:
                    with self._rate_lock:  # recover speed slowly after throttling
                        self._interval = max(BASE_INTERVAL, self._interval * 0.97)
                    return resp
                if resp.status_code in (429, 500, 502, 503, 504):
                    retry_after = resp.headers.get("Retry-After", "")
                    wait = int(retry_after) if retry_after.isdigit() else min(10 * 2 ** attempt, 300)
                    logger.warning(f"  HTTP {resp.status_code} → pausing {wait}s "
                                   f"(pace now {self._interval:.1f}s/request)...")
                    self._backoff(wait)
                    continue
                if resp.status_code == 404:
                    return None
                logger.warning(f"  HTTP {resp.status_code} from {url}")
                return None
            except requests.RequestException as e:
                wait = 2 ** (attempt + 1)
                logger.error(f"  Request error ({url}): {e}")
                time.sleep(wait)
        return None
