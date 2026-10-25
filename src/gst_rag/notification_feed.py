"""Bounded public-source fetches and an explicitly partial GST Council adapter.

No credentials, browser automation, TLS bypass, provider calls or legal inference.
"""

from dataclasses import asdict, dataclass
import hashlib
from html.parser import HTMLParser
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests


AGENT = "GST-RAG-NotificationSync/0.1"
HOSTS = {"gstcouncil.gov.in", "www.gstcouncil.gov.in", "cbic-gst.gov.in",
         "www.cbic-gst.gov.in", "taxinformation.cbic.gov.in"}
SOURCES = {
    "cgst_tax": ("https://gstcouncil.gov.in/cgst-tax-notification", "central_tax"),
    "cgst_rate": ("https://gstcouncil.gov.in/cgst-rate-notification", "central_tax_rate"),
}
COVERAGE = "partial_official_mirror_not_verified_current_or_complete"


class SyncError(ValueError):
    """Stable safe error code, not an unfiltered HTTP/provider exception."""


def safe_url(url):
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
        raise SyncError("unsafe_source_url")
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.password
                or parts.port not in {None, 443} or not parts.path.startswith("/")):
            raise SyncError("unsafe_source_url")
    except ValueError as exc:
        raise SyncError("unsafe_source_url") from exc
    return urlunsplit(("https", parts.netloc.lower(), parts.path, parts.query, ""))


class OfficialClient:
    """Validate each redirect BEFORE fetching; fail closed on inaccessible robots.

    Small delays/retries are transport courtesy, not a real-time scheduler.
    Responses are streamed and bounded; session does not carry application keys.
    """

    def __init__(self, session=None, sleep=time.sleep, pause=.6):
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False  # Do not send ambient .netrc credentials.
        self.sleep, self.pause = sleep, pause
        self.robots = {}

    def close(self):
        self.session.close()

    def _request(self, url, limit, accepted, missing_ok=False):
        for redirect in range(5):
            url = safe_url(url)
            for attempt in range(3):
                self.sleep(self.pause)
                try:
                    with self.session.get(url, headers={"User-Agent": AGENT}, timeout=(5, 20),
                                          stream=True, allow_redirects=False) as response:
                        if response.status_code in {429, 500, 502, 503, 504}:
                            if attempt == 2:
                                raise SyncError("source_temporarily_unavailable")
                            retry = response.headers.get("Retry-After", "")
                            if retry and (not retry.isdigit() or int(retry) > 5):
                                raise SyncError("source_retry_deferred")
                            self.sleep(int(retry) if retry else 2 ** attempt)
                            continue
                        if response.status_code in {301, 302, 303, 307, 308}:
                            target = safe_url(urljoin(url, response.headers.get("Location", "")))
                            if not response.headers.get("Location"):
                                raise SyncError("redirect_without_location")
                            # robots requests must not escape to another host.
                            if missing_ok and urlsplit(target).netloc != urlsplit(url).netloc:
                                raise SyncError("robots_cross_host_redirect")
                            if not missing_ok:
                                self._check_robots(target)
                            url = target
                            break
                        if missing_ok and response.status_code == 404:
                            return b"", url
                        if response.status_code != 200:
                            raise SyncError(f"source_http_{response.status_code}")
                        media = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                        if media not in accepted:
                            raise SyncError("unexpected_source_content_type")
                        length = response.headers.get("Content-Length")
                        if length and (not length.isdigit() or int(length) > limit):
                            raise SyncError("source_body_too_large")
                        body, started = bytearray(), time.monotonic()
                        for block in response.iter_content(65536):
                            body.extend(block)
                            if len(body) > limit or time.monotonic() - started > 45:
                                raise SyncError("source_body_limit_exceeded")
                        return bytes(body), url
                except requests.exceptions.SSLError as exc:
                    raise SyncError("source_tls_validation_failed") from exc
                except requests.RequestException as exc:
                    if attempt == 2:
                        raise SyncError("source_transport_failed") from exc
                    self.sleep(2 ** attempt)
            else:
                raise SyncError("source_retry_exhausted")
        raise SyncError("too_many_source_redirects")

    def _check_robots(self, url):
        parts = urlsplit(safe_url(url))
        origin = f"https://{parts.netloc}"
        if origin not in self.robots:
            body, _ = self._request(origin + "/robots.txt", 200_000,
                                    {"text/plain", "text/html"}, missing_ok=True)
            # A challenge/HTML error page must not masquerade as an empty policy.
            text = body.decode("utf-8", errors="replace")
            if body and ("<html" in text.lower() or "user-agent:" not in text.lower()):
                raise SyncError("unrecognized_robots_policy")
            policy = RobotFileParser()
            policy.parse(text.splitlines() if body else ["User-agent: *", "Allow: /"])
            self.robots[origin] = policy
        policy = self.robots[origin]
        if not policy.can_fetch(AGENT, url):
            raise SyncError("robots_disallows_source")
        delay = policy.crawl_delay(AGENT)
        if delay:
            if delay > 5:
                raise SyncError("source_crawl_delay_requires_configuration")
            self.sleep(delay)

    def get(self, url, kind):
        url = safe_url(url)
        self._check_robots(url)
        if kind == "html":
            return self._request(url, 2_000_000, {"text/html", "application/xhtml+xml"})
        if kind != "pdf":
            raise SyncError("unknown_fetch_kind")
        body, final = self._request(url, 20_000_000, {"application/pdf", "application/octet-stream"})
        if not body.startswith(b"%PDF-") or b"%%EOF" not in body[-2048:]:
            raise SyncError("invalid_pdf_envelope")
        return body, final


class _Tables(HTMLParser):
    """Read table cells and links; never execute page scripts or source text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.links = [], []
        self.table = self.row = self.cell = self.anchor = None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.table = []
        elif tag == "tr" and self.depth == 1:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None and self.depth == 1:
            self.cell = {"text": [], "links": [], "header": tag == "th"}
        elif tag == "a":
            self.anchor = {"href": attrs.get("href", ""), "rel": attrs.get("rel", ""), "text": []}
            self.links.append(self.anchor)
            if self.cell is not None:
                self.cell["links"].append(self.anchor)

    def handle_endtag(self, tag):
        if tag == "a":
            self.anchor = None
        elif tag in {"td", "th"} and self.cell is not None and self.depth == 1:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None and self.depth == 1:
            self.table.append(self.row)
            self.row = None
        elif tag == "table":
            if self.depth == 1:
                self.tables.append(self.table)
                self.table = self.row = self.cell = None
            self.depth = max(0, self.depth - 1)

    def handle_data(self, text):
        if self.cell is not None:
            self.cell["text"].append(text)
        if self.anchor is not None:
            self.anchor["text"].append(text)


def _text(parts):
    return " ".join(" ".join(parts).split())


@dataclass(frozen=True)
class Candidate:
    identity: str
    series: str
    number: str | None
    year: int | None
    kind: str
    label: str
    subject: str
    pdf_url: str
    listing_url: str
    language: str = "en"

    def to_dict(self):
        return asdict(self)


def parse_listing(html, listing_url, series):
    """Match semantic columns, not positions (CGST tax has an extra serial column)."""
    parser = _Tables()
    parser.feed(html)
    matches = []
    for table in parser.tables:
        if not table:
            continue
        headings = [_text(c["text"]).casefold() for c in table[0]]
        identity = [i for i, name in enumerate(headings) if re.search(r"(?:notification|ntfn).*no", name)]
        if "english" in headings and "subject" in headings and len(identity) == 1:
            matches.append((table, identity[0], headings.index("english"), headings.index("subject")))
    if len(matches) != 1:
        raise SyncError("notification_table_missing_or_ambiguous")
    table, identity_col, english_col, subject_col = matches[0]
    candidates = []
    for cells in table[1:]:
        if len(cells) != len(table[0]):
            raise SyncError("notification_row_shape_changed")
        label, subject = _text(cells[identity_col]["text"]), _text(cells[subject_col]["text"])
        match = re.match(r"^(\d{1,3})\s*/\s*(\d{4})\s*[-–—]?\s*Central\s+Tax(\s*\(\s*Rate\s*\))?(?=\s|,|$)", label, re.I)
        corrigendum = bool(re.search(r"\bcorrigend(?:um|a)\b", label, re.I))
        if not match and not corrigendum:
            raise SyncError("unrecognized_notification_identity")
        number, year = (str(int(match[1])), int(match[2])) if match else (None, None)
        if match and (int(number) == 0 or bool(match[3]) != (series == "central_tax_rate")):
            raise SyncError("notification_series_or_number_mismatch")
        english = cells[english_col]["links"]
        if not english:
            raise SyncError("english_pdf_missing")
        for link in english:
            url = safe_url(urljoin(listing_url, link["href"]))
            if not urlsplit(url).path.lower().endswith(".pdf"):
                raise SyncError("english_link_not_original_pdf")
            corrected = corrigendum or bool(re.search(r"corrigend(?:um|a)", _text(link["text"]), re.I))
            kind = "corrigendum" if corrected else "notification"
            if kind == "notification" and not match:
                raise SyncError("notification_identity_required")
            key = f"{series}:{number}/{year}:en" if kind == "notification" else f"{series}:corrigendum:en:{hashlib.sha256(url.encode()).hexdigest()}"
            candidates.append(Candidate(key, series, number, year, kind, label, subject, url, listing_url))
    if not candidates:
        raise SyncError("empty_notification_listing")
    next_links = {safe_url(urljoin(listing_url, a["href"])) for a in parser.links if "next" in a["rel"].split()}
    if len(next_links) > 1:
        raise SyncError("ambiguous_next_page")
    next_url = next(iter(next_links), None)
    current = urlsplit(listing_url)
    current_page = parse_qs(current.query).get("page", ["0"])[0]
    for anchor in parser.links:
        target = urlsplit(urljoin(listing_url, anchor["href"]))
        query = parse_qs(target.query)
        if (not next_url and target.netloc == current.netloc and target.path == current.path
                and set(query) == {"page"} and len(query["page"]) == 1
                and query["page"][0].isdigit() and current_page.isdigit()
                and int(query["page"][0]) > int(current_page)):
            raise SyncError("pagination_next_link_missing")
    if next_url:
        future = urlsplit(next_url)
        query = parse_qs(future.query, keep_blank_values=True)
        if (future.hostname != current.hostname or future.path != current.path or set(query) != {"page"}
                or len(query["page"]) != 1 or not query["page"][0].isdigit()):
            raise SyncError("unsafe_pagination_link")
    return candidates, next_url


def discover(client, sources, max_pages=1, since_year=2025):
    if not 1 <= max_pages <= 30 or not 2017 <= since_year <= 2100:
        raise SyncError("invalid_discovery_bounds")
    if not sources or len(set(sources)) != len(sources) or any(s not in SOURCES for s in sources):
        raise SyncError("unsupported_or_duplicate_source")
    rows, scans, errors = {}, [], []
    for name in sources:
        url, series = SOURCES[name]
        seen_urls, seen_bodies = set(), set()
        scan = {"source": name, "pages": 0, "complete_scan": False, "deferred_next_page": None}
        try:
            for _ in range(max_pages):
                if url in seen_urls:
                    raise SyncError("pagination_cycle")
                seen_urls.add(url)
                body, final_url = client.get(url, "html")
                signature = hashlib.sha256(body).hexdigest()
                if signature in seen_bodies:
                    raise SyncError("pagination_repeated_body")
                seen_bodies.add(signature)
                page, next_url = parse_listing(body.decode("utf-8-sig", errors="strict"), final_url, series)
                scan["pages"] += 1
                for row in page:
                    if row.year is not None and row.year < since_year:
                        continue
                    if row.identity in rows and rows[row.identity].pdf_url != row.pdf_url:
                        raise SyncError("ambiguous_identity_multiple_pdfs")
                    rows[row.identity] = row
                scan["deferred_next_page"] = next_url
                if next_url is None:
                    scan["complete_scan"] = True
                    break
                url = next_url
        except (SyncError, UnicodeError) as exc:
            errors.append({"source": name, "error": str(exc) if isinstance(exc, SyncError) else "invalid_listing_encoding"})
        scans.append(scan)
    return {"coverage": COVERAGE, "current_law_verified": False, "sources": scans,
            "errors": errors, "candidates": [row.to_dict() for row in rows.values()],
            "bounded_scan": any(not s["complete_scan"] for s in scans)}
