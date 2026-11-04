from pathlib import Path

import pytest
import requests

from tools.scrape_dgca_pdfs import (
    _download_url,
    _is_in_scope,
    _safe_filename,
    parse_document_links,
    scrape_and_download,
)


def test_parse_document_links_resolves_base_and_data_url():
    html = """
    <base href="https://www.dgca.gov.in/digigov-portal/">
    <a href="jsp/rules/CAR.pdf">CAR</a>
    <a data-url="jsp/lists/AMEs.pdf">AMEs</a>
    <a href="jsp/rules/index.jsp">Rules</a>
    <a href="https://example.com/outside.pdf">External PDF</a>
    """

    pdfs, pages = parse_document_links(html, "https://www.dgca.gov.in/digigov-portal/")

    assert pdfs == {
        "https://www.dgca.gov.in/digigov-portal/jsp/rules/CAR.pdf",
        "https://www.dgca.gov.in/digigov-portal/jsp/lists/AMEs.pdf",
        "https://example.com/outside.pdf",
    }
    assert pages == {"https://www.dgca.gov.in/digigov-portal/jsp/rules/index.jsp"}


def test_portal_rooted_pdf_path_resolves_from_portal_root():
    html = '<a href="jsp/dgca/AOP Docs/CAR M.pdf">CAR M</a>'

    pdfs, _pages = parse_document_links(
        html,
        "https://www.dgca.gov.in/digigov-portal/jsp/dgca/InventoryList/"
        "airOperation/certification/AOP_Package/",
        "https://www.dgca.gov.in/digigov-portal/",
    )

    assert pdfs == {"https://www.dgca.gov.in/digigov-portal/jsp/dgca/AOP Docs/CAR M.pdf"}


def test_ordinary_relative_pdf_stays_relative_to_page():
    html = '<a href="attachment.pdf">Attachment</a>'

    pdfs, _pages = parse_document_links(
        html,
        "https://www.dgca.gov.in/digigov-portal/jsp/dgca/AOP_Package/",
        "https://www.dgca.gov.in/digigov-portal/",
    )

    assert pdfs == {"https://www.dgca.gov.in/digigov-portal/jsp/dgca/AOP_Package/attachment.pdf"}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.dgca.gov.in/digigov-portal/documents/CAR.pdf", True),
        ("https://www.dgca.gov.in/digigov-portal-other/CAR.pdf", False),
        ("https://example.com/digigov-portal/CAR.pdf", False),
    ],
)
def test_is_in_scope(url: str, expected: bool):
    assert (
        _is_in_scope(
            url,
            "https://www.dgca.gov.in",
            "/digigov-portal/",
        )
        is expected
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.dgca.gov.in/docs/CAR%20Part%201.pdf", "CAR Part 1.pdf"),
        ("https://www.dgca.gov.in/docs/CON.pdf", "_CON.pdf"),
        ("https://www.dgca.gov.in/docs/%3Fbad%3F.pdf", "_bad_.pdf"),
    ],
)
def test_safe_filename(url: str, expected: str):
    assert _safe_filename(url) == expected


def test_dgca_portal_document_maps_to_public_storage():
    url = (
        "https://www.dgca.gov.in/digigov-portal/jsp/dgca/AOP%20Docs/"
        "CAR%20Section%205%20Series%20F%20Part%20III.pdf"
    )

    assert _download_url(url) == (
        "https://public-prd-dgca.s3.ap-south-1.amazonaws.com/AOP%20Docs/"
        "CAR%20Section%205%20Series%20F%20Part%20III.pdf"
    )


def test_non_document_urls_are_not_rewritten():
    url = "https://www.dgca.gov.in/digigov-portal/jsp/dgca/page.jsp"

    assert _download_url(url) == url


def test_bad_start_urls_are_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="absolute HTTP or HTTPS"):
        scrape_and_download("file:///tmp/index.html", tmp_path, delay=0)


class FakeResponse:
    def __init__(
        self,
        url: str,
        text: str = "",
        content: bytes = b"",
        status_code: int = 200,
    ):
        self.url = url
        self.text = text
        self.content = content
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error for {self.url}")
        return None

    def iter_content(self, chunk_size: int):
        chunks = (
            self.content[index : index + chunk_size] for index in range(0, len(self.content), chunk_size)
        )
        yield from chunks


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.requested: list[str] = []
        self.responses = {
            "https://www.dgca.gov.in/robots.txt": FakeResponse("https://www.dgca.gov.in/robots.txt"),
            "https://www.dgca.gov.in/digigov-portal/": FakeResponse(
                "https://www.dgca.gov.in/digigov-portal/",
                text='<a href="category.jsp">Category</a><a href="4283/4232/servicename">Stale page</a>',
            ),
            "https://www.dgca.gov.in/digigov-portal/category.jsp": FakeResponse(
                "https://www.dgca.gov.in/digigov-portal/category.jsp",
                text='<a data-url="docs/CAR.pdf">CAR</a>'
                '<a href="https://example.com/outside.pdf">External</a>',
            ),
            "https://www.dgca.gov.in/digigov-portal/docs/CAR.pdf": FakeResponse(
                "https://www.dgca.gov.in/digigov-portal/docs/CAR.pdf",
                content=b"%PDF-1.7\nexample",
            ),
            "https://www.dgca.gov.in/digigov-portal/4283/4232/servicename": FakeResponse(
                "https://www.dgca.gov.in/digigov-portal/4283/4232/servicename",
                status_code=404,
            ),
        }

    def get(self, url: str, **_kwargs):
        self.requested.append(url)
        return self.responses[url]


def test_scrape_and_download_stays_in_portal_and_skips_existing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    session = FakeSession()
    monkeypatch.setattr("tools.scrape_dgca_pdfs.requests.Session", lambda: session)

    downloaded = scrape_and_download(output_dir=tmp_path, delay=0)

    assert downloaded == 1
    assert (tmp_path / "CAR.pdf").read_bytes() == b"%PDF-1.7\nexample"
    assert all("example.com" not in url for url in session.requested)
    assert "https://www.dgca.gov.in/digigov-portal/4283/4232/servicename" in session.requested
    assert scrape_and_download(output_dir=tmp_path, delay=0) == 0
