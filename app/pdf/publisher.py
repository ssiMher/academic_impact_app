"""Resolve publisher download entry points from DOI and URL metadata."""

from dataclasses import dataclass
from typing import Optional

from app.pdf.arxiv import extract_arxiv_identifier


@dataclass(frozen=True)
class PublisherInfo:
    source: str
    publisher: str
    landing_url: str
    fallback_url: str
    access_hint: str


def normalize_doi(value: Optional[str]) -> str:
    doi = (value or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi.strip()


def classify_publisher_from_doi_or_url(
    doi: Optional[str],
    url: Optional[str],
) -> PublisherInfo:
    normalized_doi = normalize_doi(doi)
    url_value = (url or "").strip()
    url_lower = url_value.lower()
    if not normalized_doi:
        for prefix in ("https://doi.org/", "http://doi.org/"):
            if url_lower.startswith(prefix):
                normalized_doi = url_value[len(prefix) :].strip()
                break
    doi_lower = normalized_doi.lower()
    fallback = f"https://doi.org/{normalized_doi}" if normalized_doi else ""

    if doi_lower.startswith("10.48550/arxiv.") or extract_arxiv_identifier(url_value):
        return PublisherInfo(
            source="arxiv",
            publisher="arXiv",
            landing_url=url_value or fallback,
            fallback_url=fallback,
            access_hint="开放获取预印本",
        )
    if doi_lower.startswith("10.1145/") or "dl.acm.org" in url_lower or "10.1145/" in url_lower:
        return PublisherInfo(
            source="acm_dl",
            publisher="ACM Digital Library",
            landing_url=(
                url_value
                if "dl.acm.org" in url_lower
                else f"https://dl.acm.org/doi/{normalized_doi}"
            ),
            fallback_url=fallback,
            access_hint="通常需要 ACM 或学校/机构权限",
        )
    if doi_lower.startswith("10.1109/") or "ieeexplore.ieee.org" in url_lower or "10.1109/" in url_lower:
        return PublisherInfo(
            source="ieee_xplore",
            publisher="IEEE Xplore",
            landing_url=url_value if "ieeexplore.ieee.org" in url_lower else fallback,
            fallback_url=fallback,
            access_hint="通常需要 IEEE 或学校/机构权限",
        )
    if doi_lower.startswith("10.1007/") or "link.springer.com" in url_lower:
        return PublisherInfo(
            source="springer",
            publisher="Springer",
            landing_url=url_value if "springer" in url_lower else fallback,
            fallback_url=fallback,
            access_hint="可能需要 Springer 或学校/机构权限",
        )
    if doi_lower.startswith("10.1016/") or "sciencedirect.com" in url_lower:
        return PublisherInfo(
            source="elsevier",
            publisher="Elsevier / ScienceDirect",
            landing_url=url_value if "sciencedirect.com" in url_lower else fallback,
            fallback_url=fallback,
            access_hint="可能需要 Elsevier 或学校/机构权限",
        )
    if "usenix.org" in url_lower:
        return PublisherInfo(
            source="usenix",
            publisher="USENIX",
            landing_url=url_value,
            fallback_url=fallback,
            access_hint="请在 USENIX 论文页面确认 PDF 访问方式",
        )
    if "openreview.net" in url_lower:
        return PublisherInfo(
            source="openreview",
            publisher="OpenReview",
            landing_url=url_value,
            fallback_url=fallback,
            access_hint="请在 OpenReview 页面查看公开 PDF",
        )
    return PublisherInfo(
        source="publisher",
        publisher="Publisher",
        landing_url=url_value or fallback,
        fallback_url=fallback,
        access_hint="请通过 DOI 或出版社页面确认访问权限",
    )
