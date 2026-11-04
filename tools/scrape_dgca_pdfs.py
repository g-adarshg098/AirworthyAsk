"""Find and download PDFs linked from a DGCA portal section."""

from __future__ import annotations

import argparse
import hashlib
import re
import tempfile
import time
from collections import deque
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests

DEFAULT_URL = "https://www.dgca.gov.in/digigov-portal/"
DEFAULT_OUTPUT = Path("data/raw/dgca_pdfs")
DGCA_DOCUMENT_BASE = "https://public-prd-dgca.s3.ap-south-1.amazonaws.com/"
USER_AGENT = "AirworthyAsk/1.0 (public document downloader)"
TIMEOUT = 30
CHUNK_SIZE = 64 * 1024


class DocumentLinkParser(HTMLParser):
    """Collect normal, data-url, and base links from portal HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.base_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.lower() == "base" and attributes.get("href"):
            self.base_url = attributes["href"]
            return
        for attribute in ("href", "data-url"):
            value = attributes.get(attribute)
            if value:
                self.links.append(value.strip())


def parse_document_links(
    html: str,
    page_url: str,
    portal_base: str | None = None,
) -> tuple[set[str], set[str]]:
    """Return absolute PDF and HTML-page URLs found in a document."""
    parser = DocumentLinkParser()
    parser.feed(html)
    base_url = urljoin(page_url, parser.base_url or page_url)
    portal_base_url = urljoin(page_url, portal_base) if portal_base else None
    pdf_urls: set[str] = set()
    page_urls: set[str] = set()

    for link in parser.links:
        link_path = urlsplit(link).path
        is_portal_rooted = (
            parser.base_url is None and portal_base_url is not None and link_path.startswith("jsp/")
        )
        link_base = portal_base_url if is_portal_rooted else base_url
        absolute_url, _fragment = urldefrag(urljoin(link_base, link))
        path = urlsplit(absolute_url).path.lower()
        if path.endswith(".pdf"):
            pdf_urls.add(absolute_url)
        elif _is_html_page(path):
            page_urls.add(absolute_url)

    return pdf_urls, page_urls


def _is_html_page(path: str) -> bool:
    return not Path(path).suffix or path.endswith("/") or path.endswith((".html", ".htm", ".jsp"))


def _is_in_scope(url: str, origin: str, portal_path: str) -> bool:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}" == origin and (
        parsed.path == portal_path.rstrip("/") or parsed.path.startswith(portal_path)
    )


def _safe_filename(url: str) -> str:
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1]) or "document.pdf"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        name = "document.pdf"
    if name.split(".", maxsplit=1)[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = f"_{name}"
    return name


def _download_url(url: str) -> str:
    """Map DGCA portal document paths to their public object-storage URLs."""
    parsed = urlsplit(url)
    portal_document_prefix = "/digigov-portal/jsp/dgca/"
    if (
        parsed.hostname in {"www.dgca.gov.in", "dgca.gov.in"}
        and parsed.path.startswith(portal_document_prefix)
        and parsed.path.lower().endswith(".pdf")
    ):
        object_key = unquote(parsed.path[len(portal_document_prefix) :])
        object_path = quote(object_key, safe="/")
        base = urlsplit(DGCA_DOCUMENT_BASE)
        return urlunsplit((base.scheme, base.netloc, f"{base.path}{object_path}", parsed.query, ""))
    return url


def _load_robots(session: requests.Session, origin: str) -> RobotFileParser | None:
    robots_url = f"{origin}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = session.get(robots_url, timeout=TIMEOUT)
        if response.status_code == 404:
            parser.parse([])
        else:
            response.raise_for_status()
            parser.parse(response.text.splitlines())
    except requests.RequestException as exc:
        print(f"Warning: could not read robots.txt ({exc}); continuing with delays.")
        return None
    return parser


def _download_pdf(
    session: requests.Session,
    url: str,
    output_dir: Path,
    used_names: set[str],
) -> Path | None:
    filename = _safe_filename(url)
    if filename.casefold() in used_names:
        stem, suffix = Path(filename).stem, Path(filename).suffix
        short_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
        filename = f"{stem}_{short_hash}{suffix}"
    target = output_dir / filename
    if target.exists():
        print(f"Already exists; skipped {target}")
        used_names.add(filename.casefold())
        return None

    temporary_path: Path | None = None
    try:
        with session.get(_download_url(url), stream=True, timeout=TIMEOUT) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=output_dir, suffix=".part", delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                signature = bytearray()
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    if len(signature) < 5:
                        signature.extend(chunk[: 5 - len(signature)])
                    temporary_file.write(chunk)
                if bytes(signature) != b"%PDF-":
                    raise ValueError(f"Response is empty or not a PDF: {url}")
        temporary_path.replace(target)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    used_names.add(filename.casefold())
    print(f"Downloaded {target}")
    return target


def scrape_and_download(
    start_url: str = DEFAULT_URL,
    output_dir: Path = DEFAULT_OUTPUT,
    max_pages: int = 100,
    delay: float = 1.0,
) -> int:
    """Crawl same-origin portal pages and download discovered PDF files."""
    start_url, _fragment = urldefrag(start_url)
    start = urlsplit(start_url)
    if start.scheme not in {"http", "https"} or not start.netloc:
        raise ValueError("The start URL must be an absolute HTTP or HTTPS URL.")
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1.")
    if delay < 0:
        raise ValueError("delay cannot be negative.")

    origin = f"{start.scheme}://{start.netloc}"
    portal_path = start.path if start.path.endswith("/") else f"{start.path}/"
    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    robots = _load_robots(session, origin)
    queue = deque([start_url])
    visited: set[str] = set()
    pdf_urls: set[str] = set()

    while queue and len(visited) < max_pages:
        page_url = queue.popleft()
        if page_url in visited or not _is_in_scope(page_url, origin, portal_path):
            continue
        visited.add(page_url)
        if robots is not None and not robots.can_fetch(USER_AGENT, page_url):
            print(f"Blocked by robots.txt: {page_url}")
            continue

        if len(visited) > 1 and delay:
            time.sleep(delay)
        try:
            response = session.get(page_url, timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"Could not scan {page_url}: {exc}")
            continue
        portal_base = f"{origin}{portal_path}"
        found_pdfs, found_pages = parse_document_links(
            response.text,
            response.url,
            portal_base,
        )
        pdf_urls.update(url for url in found_pdfs if _is_in_scope(url, origin, portal_path))
        for linked_page in found_pages:
            if _is_in_scope(linked_page, origin, portal_path) and linked_page not in visited:
                queue.append(linked_page)
        print(f"Scanned {page_url}")

    used_names: set[str] = set()
    downloaded = 0
    for index, pdf_url in enumerate(sorted(pdf_urls)):
        if robots is not None and not robots.can_fetch(USER_AGENT, pdf_url):
            print(f"Blocked by robots.txt: {pdf_url}")
            continue
        if index and delay:
            time.sleep(delay)
        try:
            if _download_pdf(session, pdf_url, output_dir, used_names) is not None:
                downloaded += 1
        except (requests.RequestException, ValueError) as exc:
            print(f"Could not download {pdf_url}: {exc}")

    print(f"Scanned {len(visited)} page(s); downloaded {downloaded} PDF(s).")
    return downloaded


def main() -> None:
    argument_parser = argparse.ArgumentParser(
        description="Find and download PDFs linked from the DGCA portal."
    )
    argument_parser.add_argument("--url", default=DEFAULT_URL, help="Portal page to start from.")
    argument_parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="Directory for downloaded PDFs."
    )
    argument_parser.add_argument(
        "--max-pages", type=int, default=100, help="Maximum same-origin HTML pages to scan."
    )
    argument_parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between requests.")
    args = argument_parser.parse_args()
    scrape_and_download(args.url, args.output, args.max_pages, args.delay)


if __name__ == "__main__":
    main()
