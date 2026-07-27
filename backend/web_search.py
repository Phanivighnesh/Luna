"""
Web search — the one feature in Luna that legitimately needs live internet
access, since no local model has today's information baked in.

Uses DuckDuckGo's HTML/lite endpoints (no API key required). These are
scraped, unofficial interfaces, so they can start blocking automated
requests at any time (a 403 usually means their bot detection triggered on
something about the request shape, not that the code is broken).

NOT CERTAIN this fully eliminates 403s long-term — DuckDuckGo's blocking
behavior isn't publicly documented and can change without notice. If it
starts failing again, the diagnostic info returned below (status code +
response snippet) is the first thing to check.
"""

import httpx
import re
from urllib.parse import urlparse, parse_qs, unquote
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://duckduckgo.com/",
}

PRIMARY_URL = "https://html.duckduckgo.com/html/"
FALLBACK_URL = "https://lite.duckduckgo.com/lite/"


def _clean_text(text: str) -> str:
    """get_text(strip=True) with no separator concatenates adjacent tags'
    text with zero space between them (e.g. 'Amazon.com' + 'intel' + 'i7'
    running together). Using separator=' ' fixes that, at the cost of
    sometimes-doubled spaces, which this collapses."""
    return re.sub(r"\s+", " ", text).strip()


def _clean_result_url(href: str) -> str:
    """DuckDuckGo's HTML results wrap destination links in a redirect like
    '//duckduckgo.com/l/?uddg=<url-encoded-real-url>&rut=...'. Decode that
    back to the actual destination instead of showing the wrapper."""
    if not href:
        return href
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        real = parse_qs(parsed.query).get("uddg", [None])[0]
        if real:
            return unquote(real)
    return href


async def _try_fetch(client: httpx.AsyncClient, url: str, query: str):
    return await client.get(url, params={"q": query})


def _parse_html_endpoint(soup: BeautifulSoup, max_results: int):
    results = []
    for block in soup.select(".result__body")[:max_results]:
        title_el = block.select_one(".result__a")
        snippet_el = block.select_one(".result__snippet")
        if title_el:
            results.append({
                "title": _clean_text(title_el.get_text(separator=" ", strip=True)),
                "snippet": _clean_text(snippet_el.get_text(separator=" ", strip=True)) if snippet_el else "",
                "url": _clean_result_url(title_el.get("href", "")),
            })
    return results


def _parse_lite_endpoint(soup: BeautifulSoup, max_results: int):
    # lite.duckduckgo.com uses a plain table layout; result links carry the
    # "result-link" class. Structure is minimal by design (built for very
    # low-bandwidth/text browsers), which is exactly why it's used as a fallback.
    results = []
    for a in soup.select("a.result-link")[:max_results]:
        results.append({
            "title": _clean_text(a.get_text(separator=" ", strip=True)),
            "snippet": "",
            "url": _clean_result_url(a.get("href", "")),
        })
    return results


async def search_web(query: str, max_results: int = 5):
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=HEADERS, follow_redirects=True) as client:
            resp = await _try_fetch(client, PRIMARY_URL, query)
            source = "html"

            if resp.status_code != 200:
                resp = await _try_fetch(client, FALLBACK_URL, query)
                source = "lite"

            if resp.status_code != 200:
                snippet = resp.text[:200].replace("\n", " ").strip()
                return [{
                    "title": "Search failed",
                    "snippet": f"HTTP {resp.status_code} from DuckDuckGo (tried both endpoints). "
                               f"Response start: {snippet or '(empty body)'}",
                    "url": "",
                }]

            soup = BeautifulSoup(resp.text, "html.parser")
            results = _parse_html_endpoint(soup, max_results) if source == "html" else []
            if not results:
                results = _parse_lite_endpoint(soup, max_results)

            if not results:
                return [{"title": "No results found", "snippet": f"(source: {source} endpoint, HTTP {resp.status_code})", "url": ""}]
            return results
    except Exception as e:
        return [{"title": "Search error", "snippet": str(e), "url": ""}]


def format_results_for_chat(results: list) -> str:
    lines = []
    for r in results:
        line = f"• {r['title']}"
        if r.get("snippet"):
            line += f" — {r['snippet']}"
        if r.get("url"):
            line += f"\n  {r['url']}"
        lines.append(line)
    return "\n".join(lines)
