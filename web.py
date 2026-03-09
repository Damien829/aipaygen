import re
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from ddgs import DDGS
from security import validate_url, SSRFError

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AiPayGen/1.0; +https://aipaygen.com)"
}

STRIP_TAGS = ["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]


def scrape_url(url: str, timeout: int = 10) -> dict:
    try:
        url = validate_url(url, allow_http=True)
    except SSRFError as e:
        return {"error": f"SSRF blocked: {e}", "url": url, "blocked": True}
    try:
        resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return {"error": "timeout", "url": url}
    except requests.exceptions.HTTPError as e:
        return {"error": f"http_{e.response.status_code}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(STRIP_TAGS):
        tag.decompose()

    body = soup.find("main") or soup.find("article") or soup.find("body") or soup
    text = md(str(body), strip=["a", "img"]).strip()
    text = re.sub(r'\n{3,}', '\n\n', text)

    return {
        "url": url,
        "text": text,
        "word_count": len(text.split()),
    }


def search_web(query: str, n: int = 5) -> dict:
    results = []
    try:
        with DDGS() as ddgs:
            raw = ddgs.text(query, max_results=n)
            for r in raw:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
    except Exception as e:
        return {"error": str(e), "query": query, "results": []}

    return {"query": query, "results": results}
