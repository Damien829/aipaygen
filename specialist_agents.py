"""
8 specialist agents that self-register in the agent registry and list
their services in the marketplace at startup. Idempotent — safe to call
multiple times.
"""
from agent_memory import register_agent, marketplace_list_service

BASE = "https://api.aipaygent.xyz"

_AGENTS = [
    {
        "agent_id": "agent-datafeed-v1",
        "name": "DataFeedAgent",
        "description": "Real-time data: weather, crypto prices, exchange rates, country info, IP geo, news.",
        "capabilities": ["weather", "crypto", "exchange-rates", "country-info", "ip-geo", "news"],
        "endpoint": f"{BASE}/data/weather",
        "services": [
            {"name": "Live Weather Data", "description": "Current weather for any city via Open-Meteo.", "endpoint": f"{BASE}/data/weather", "price_usd": 0.0, "category": "data"},
            {"name": "Crypto Prices", "description": "Real-time prices for bitcoin, ethereum, and 10k+ tokens.", "endpoint": f"{BASE}/data/crypto", "price_usd": 0.0, "category": "data"},
            {"name": "Exchange Rates", "description": "Live currency exchange rates for 160+ currencies.", "endpoint": f"{BASE}/data/exchange-rates", "price_usd": 0.0, "category": "data"},
            {"name": "Country Info", "description": "Country facts: capital, population, languages, currencies.", "endpoint": f"{BASE}/data/country", "price_usd": 0.0, "category": "data"},
            {"name": "IP Geolocation", "description": "Geolocate any IP address: city, country, ISP, lat/lon.", "endpoint": f"{BASE}/data/ip", "price_usd": 0.0, "category": "data"},
        ],
    },
    {
        "agent_id": "agent-search-v1",
        "name": "SearchAgent",
        "description": "Web search via DuckDuckGo, AI research, Hacker News trending.",
        "capabilities": ["web-search", "research", "news"],
        "endpoint": f"{BASE}/web/search",
        "services": [
            {"name": "Web Search", "description": "DuckDuckGo instant answers + related results.", "endpoint": f"{BASE}/web/search", "price_usd": 0.02, "category": "search"},
            {"name": "AI Research", "description": "Claude-powered deep research on any topic.", "endpoint": f"{BASE}/research", "price_usd": 0.01, "category": "search"},
            {"name": "Tech News", "description": "Top Hacker News stories right now.", "endpoint": f"{BASE}/data/news", "price_usd": 0.0, "category": "search"},
        ],
    },
    {
        "agent_id": "agent-coderun-v1",
        "name": "CodeRunnerAgent",
        "description": "Execute Python code, generate code from description, generate test cases.",
        "capabilities": ["python-execution", "code-generation", "test-generation"],
        "endpoint": f"{BASE}/code/run",
        "services": [
            {"name": "Run Python Code", "description": "Execute Python snippets in a sandbox, get stdout/stderr.", "endpoint": f"{BASE}/code/run", "price_usd": 0.05, "category": "code"},
            {"name": "Code Generation", "description": "Claude generates code from a plain English description.", "endpoint": f"{BASE}/code", "price_usd": 0.05, "category": "code"},
            {"name": "Test Case Generator", "description": "Auto-generate unit tests and edge cases for any function.", "endpoint": f"{BASE}/test-cases", "price_usd": 0.03, "category": "code"},
        ],
    },
    {
        "agent_id": "agent-scraper-v1",
        "name": "ScraperAgent",
        "description": "Web scraping: Google Maps, Twitter, Instagram, LinkedIn, YouTube, TikTok, generic web.",
        "capabilities": ["google-maps", "twitter", "instagram", "linkedin", "youtube", "web-crawl"],
        "endpoint": f"{BASE}/scrape/web",
        "services": [
            {"name": "Google Maps Scraper", "description": "Scrape places, ratings, addresses from Google Maps.", "endpoint": f"{BASE}/scrape/google-maps", "price_usd": 0.10, "category": "scraping"},
            {"name": "Tweet Scraper", "description": "Scrape tweets by keyword or hashtag.", "endpoint": f"{BASE}/scrape/tweets", "price_usd": 0.05, "category": "scraping"},
            {"name": "Instagram Scraper", "description": "Scrape Instagram profile posts and metadata.", "endpoint": f"{BASE}/scrape/instagram", "price_usd": 0.05, "category": "scraping"},
            {"name": "LinkedIn Scraper", "description": "Scrape LinkedIn profile data.", "endpoint": f"{BASE}/scrape/linkedin", "price_usd": 0.15, "category": "scraping"},
            {"name": "Web Crawler", "description": "Crawl any website and extract structured content.", "endpoint": f"{BASE}/scrape/web", "price_usd": 0.05, "category": "scraping"},
        ],
    },
    {
        "agent_id": "agent-nlp-v1",
        "name": "NLPAgent",
        "description": "NLP services: sentiment analysis, keyword extraction, classification, data extraction.",
        "capabilities": ["sentiment", "keywords", "classify", "extract", "fact-check"],
        "endpoint": f"{BASE}/sentiment",
        "services": [
            {"name": "Sentiment Analysis", "description": "Deep sentiment: polarity, emotions, key phrases.", "endpoint": f"{BASE}/sentiment", "price_usd": 0.01, "category": "nlp"},
            {"name": "Keyword Extraction", "description": "Extract keywords, topics, tags, entities from text.", "endpoint": f"{BASE}/keywords", "price_usd": 0.01, "category": "nlp"},
            {"name": "Text Classification", "description": "Classify text into your custom categories.", "endpoint": f"{BASE}/classify", "price_usd": 0.01, "category": "nlp"},
            {"name": "Data Extraction", "description": "Extract structured data from unstructured text.", "endpoint": f"{BASE}/extract", "price_usd": 0.02, "category": "nlp"},
        ],
    },
    {
        "agent_id": "agent-content-v1",
        "name": "ContentAgent",
        "description": "Content creation: articles, emails, social posts, outlines, rewrites.",
        "capabilities": ["writing", "email", "social-media", "outline", "rewrite"],
        "endpoint": f"{BASE}/write",
        "services": [
            {"name": "Content Writer", "description": "Claude writes articles, blog posts, copy to your spec.", "endpoint": f"{BASE}/write", "price_usd": 0.05, "category": "content"},
            {"name": "Email Composer", "description": "Professional emails with subject, body, tone control.", "endpoint": f"{BASE}/email", "price_usd": 0.03, "category": "content"},
            {"name": "Social Media Posts", "description": "Platform-optimized posts for Twitter, LinkedIn, Instagram.", "endpoint": f"{BASE}/social", "price_usd": 0.03, "category": "content"},
            {"name": "Outline Generator", "description": "Hierarchical outlines for any topic or document.", "endpoint": f"{BASE}/outline", "price_usd": 0.02, "category": "content"},
        ],
    },
    {
        "agent_id": "agent-analytics-v1",
        "name": "AnalyticsAgent",
        "description": "Data analytics: analysis, comparison, diagram generation, workflow orchestration.",
        "capabilities": ["analyze", "compare", "diagram", "workflow"],
        "endpoint": f"{BASE}/analyze",
        "services": [
            {"name": "Content Analysis", "description": "Claude analyzes text: findings, sentiment, confidence.", "endpoint": f"{BASE}/analyze", "price_usd": 0.02, "category": "analytics"},
            {"name": "Text Comparison", "description": "Compare two texts: similarities, differences, recommendation.", "endpoint": f"{BASE}/compare", "price_usd": 0.02, "category": "analytics"},
            {"name": "Diagram Generator", "description": "Generate Mermaid diagrams from plain English.", "endpoint": f"{BASE}/diagram", "price_usd": 0.03, "category": "analytics"},
            {"name": "Agentic Workflow", "description": "Multi-step reasoning with Claude Sonnet for complex goals.", "endpoint": f"{BASE}/workflow", "price_usd": 0.20, "category": "analytics"},
        ],
    },
    {
        "agent_id": "agent-knowledge-v1",
        "name": "KnowledgeAgent",
        "description": "Knowledge services: RAG, fact extraction, shared knowledge base, entity enrichment.",
        "capabilities": ["rag", "fact-check", "knowledge-base", "enrichment"],
        "endpoint": f"{BASE}/rag",
        "services": [
            {"name": "RAG Document Q&A", "description": "Provide documents + query, get grounded answer with citations.", "endpoint": f"{BASE}/rag", "price_usd": 0.05, "category": "knowledge"},
            {"name": "Fact Extractor", "description": "Extract factual claims with verifiability scores.", "endpoint": f"{BASE}/fact", "price_usd": 0.02, "category": "knowledge"},
            {"name": "Knowledge Base Search", "description": "Search the shared agent knowledge base.", "endpoint": f"{BASE}/knowledge/search", "price_usd": 0.0, "category": "knowledge"},
            {"name": "Entity Enrichment", "description": "One call to enrich an IP, crypto, country, or company.", "endpoint": f"{BASE}/enrich", "price_usd": 0.05, "category": "knowledge"},
        ],
    },
]


def bootstrap_all_agents():
    """Register all 8 specialist agents and their marketplace listings. Idempotent."""
    for agent in _AGENTS:
        register_agent(
            agent_id=agent["agent_id"],
            name=agent["name"],
            description=agent["description"],
            capabilities=agent["capabilities"],
            endpoint=agent["endpoint"],
        )
        for svc in agent["services"]:
            marketplace_list_service(
                agent_id=agent["agent_id"],
                name=svc["name"],
                description=svc["description"],
                endpoint=svc["endpoint"],
                price_usd=svc["price_usd"],
                category=svc["category"],
                capabilities=agent["capabilities"],
            )
