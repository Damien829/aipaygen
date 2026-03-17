"""Scraping Tools — web, YouTube, Twitter, Instagram, TikTok, LinkedIn, Facebook Ads."""

from typing import Annotated
from pydantic import Field

from mcp_tools import mcp, metered_tool, _premium_gate, _apify_run, _log
import requests as _mcp_requests


@metered_tool("scraping")
def scrape_google_maps(query: Annotated[str, Field(description="Search query for businesses on Google Maps")], max_results: Annotated[int, Field(description="Maximum number of results to return")] = 5) -> dict:
    """Scrape Google Maps for businesses matching a query. Returns name, address, rating, phone, website."""
    gate = _premium_gate("scrape_google_maps", "$0.02/call")
    if gate:
        return gate
    results = _apify_run("nwua9Gu5YrADL7ZDj",
                         {"searchStringsArray": [query], "maxCrawledPlacesPerSearch": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_tweets(query: Annotated[str, Field(description="Search query or hashtag for tweets")], max_results: Annotated[int, Field(description="Maximum number of tweets to return")] = 20) -> dict:
    """Scrape Twitter/X tweets by search query or hashtag. Returns text, author, likes, retweets, date."""
    gate = _premium_gate("scrape_tweets", "$0.01/call")
    if gate:
        return gate
    results = _apify_run("61RPP7dywgiy0JPD0",
                         {"searchTerms": [query], "maxItems": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_website(url: Annotated[str, Field(description="Website URL to crawl")], max_pages: Annotated[int, Field(description="Maximum number of pages to crawl")] = 3) -> dict:
    """Crawl any website and extract text content. Returns page URL, title, and text per page."""
    gate = _premium_gate("scrape_website", "$0.01/call")
    if gate:
        return gate
    results = _apify_run("aYG0l9s7dbB7j3gbS",
                         {"startUrls": [{"url": url}], "maxCrawlPages": max_pages},
                         max_pages)
    return {"url": url, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_youtube(query: Annotated[str, Field(description="YouTube search keywords")], max_results: Annotated[int, Field(description="Maximum number of videos to return")] = 5) -> dict:
    """Search YouTube and return video metadata — title, channel, views, duration, description, URL."""
    gate = _premium_gate("scrape_youtube", "$0.02/call")
    if gate:
        return gate
    results = _apify_run("h7sDV53CddomktSi5",
                         {"searchKeywords": query, "maxResults": max_results},
                         max_results)
    return {"query": query, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_instagram(username: Annotated[str, Field(description="Instagram username to scrape posts from")], max_posts: Annotated[int, Field(description="Maximum number of posts to return")] = 5) -> dict:
    """Scrape Instagram profile posts. Returns caption, likes, comments, date, media URL."""
    gate = _premium_gate("scrape_instagram", "$0.01/call")
    if gate:
        return gate
    results = _apify_run("shu8hvrXbJbY3Eb9W",
                         {"username": [username], "resultsLimit": max_posts},
                         max_posts)
    return {"username": username, "count": len(results), "results": results}


@metered_tool("scraping")
def scrape_tiktok(username: Annotated[str, Field(description="TikTok username to scrape videos from")], max_videos: Annotated[int, Field(description="Maximum number of videos to return")] = 5) -> dict:
    """Scrape TikTok profile videos. Returns caption, views, likes, shares, date."""
    gate = _premium_gate("scrape_tiktok", "$0.02/call")
    if gate:
        return gate
    results = _apify_run("GdWCkxBtKWOsKjdch",
                         {"profiles": [username], "resultsPerPage": max_videos},
                         max_videos)
    return {"username": username, "count": len(results), "results": results}


@metered_tool("premium")
def scrape_linkedin(url: Annotated[str, Field(description="LinkedIn profile or company URL")]) -> dict:
    """Scrape a LinkedIn profile or company page for public data."""
    gate = _premium_gate("scrape_linkedin", "$0.02/call")
    if gate:
        return gate
    try:
        resp = _mcp_requests.post("http://localhost:5001/scrape/linkedin", json={"url": url}, timeout=30)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("premium")
def scrape_facebook_ads(query: Annotated[str, Field(description="Search query for Facebook ads")], max_results: Annotated[int, Field(description="Max ads to return")] = 10) -> dict:
    """Search the Facebook Ad Library for active advertisements."""
    gate = _premium_gate("scrape_facebook_ads", "$0.02/call")
    if gate:
        return gate
    try:
        resp = _mcp_requests.post("http://localhost:5001/scrape/facebook-ads", json={"query": query, "max_results": max_results}, timeout=30)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}
