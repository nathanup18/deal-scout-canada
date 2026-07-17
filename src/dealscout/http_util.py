"""Shared HTTP session and page-text extraction."""

import logging

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("dealscout")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 deal-scout-canada")


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def fetch(sess: requests.Session, url: str, timeout: int = 90) -> str:
    resp = sess.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def page_text(html: str, include_attrs: bool = False) -> str:
    """Visible text; optionally append img alts + link hrefs (some portfolio
    grids carry company names only in attributes)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    if include_attrs:
        alts = [img.get("alt", "") for img in soup.find_all("img")]
        hrefs = [a.get("href", "") for a in soup.find_all("a")]
        text += "\nIMG_ALTS: " + " | ".join(a for a in alts if a)
        text += "\nHREFS: " + " | ".join(h for h in hrefs if h)
    return text
