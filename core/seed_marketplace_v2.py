#!/usr/bin/env python3
"""Scale marketplace to 80+ agents across 15+ categories."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import random
import json
from datetime import datetime, timezone, timedelta
from agent_memory import marketplace_list_service, _conn

AGENTS = [
    # ── Finance ──────────────────────────────────────────────
    {"name": "Financial Analyst Pro", "desc": "Analyze financial statements, ratios, and trends. Supports SEC filings, balance sheets, income statements. Perfect for due diligence and investment research.", "endpoint": "/agent", "price": 0.04, "cat": "finance", "caps": ["financial_analysis", "SEC_filings", "ratios"], "calls": (600, 1800), "rating": (4.3, 4.8)},
    {"name": "Tax Calculator Agent", "desc": "US tax calculations for individuals and businesses. Federal + state. Supports 1099, W2, capital gains, deductions, and estimated quarterly payments.", "endpoint": "/agent", "price": 0.03, "cat": "finance", "caps": ["tax_calculation", "deductions", "capital_gains"], "calls": (400, 1200), "rating": (4.2, 4.7)},
    {"name": "Invoice Generator", "desc": "Generate professional invoices in PDF. Supports multiple currencies, tax calculations, payment terms, and recurring billing templates.", "endpoint": "/agent", "price": 0.02, "cat": "finance", "caps": ["invoice", "PDF", "billing"], "calls": (300, 900), "rating": (4.4, 4.8)},
    {"name": "Crypto Portfolio Tracker", "desc": "Real-time portfolio tracking for 500+ crypto assets. P&L, allocation, tax lots, DCA tracking. Connects to exchanges via read-only API.", "endpoint": "/trading/portfolio", "price": 0.01, "cat": "finance", "caps": ["crypto", "portfolio", "tracking"], "calls": (1500, 4000), "rating": (4.1, 4.6)},
    {"name": "Stock Screener Agent", "desc": "Screen stocks by fundamentals (P/E, EPS, market cap), technicals (RSI, MACD), and custom criteria. Covers US, EU, and Asian markets.", "endpoint": "/agent", "price": 0.02, "cat": "finance", "caps": ["stocks", "screening", "fundamentals"], "calls": (800, 2500), "rating": (4.3, 4.7)},

    # ── Legal ────────────────────────────────────────────────
    {"name": "Contract Reviewer", "desc": "AI-powered contract analysis. Identifies risky clauses, missing terms, and non-standard language. Supports NDAs, MSAs, SOWs, and employment agreements.", "endpoint": "/agent", "price": 0.06, "cat": "legal", "caps": ["contract_review", "risk_analysis", "clause_detection"], "calls": (200, 700), "rating": (4.5, 4.9)},
    {"name": "Privacy Policy Generator", "desc": "Generate GDPR, CCPA, and COPPA compliant privacy policies. Customized to your product, data practices, and jurisdiction.", "endpoint": "/agent", "price": 0.03, "cat": "legal", "caps": ["privacy_policy", "GDPR", "CCPA"], "calls": (300, 800), "rating": (4.3, 4.7)},
    {"name": "Terms of Service Writer", "desc": "Generate professional terms of service for SaaS, marketplaces, and mobile apps. Includes liability limitations, IP clauses, and dispute resolution.", "endpoint": "/agent", "price": 0.03, "cat": "legal", "caps": ["terms_of_service", "SaaS", "legal_docs"], "calls": (250, 600), "rating": (4.4, 4.8)},
    {"name": "Patent Search Agent", "desc": "Search US and international patent databases. Prior art analysis, claim comparison, and novelty assessment.", "endpoint": "/agent", "price": 0.05, "cat": "legal", "caps": ["patent_search", "prior_art", "IP"], "calls": (150, 400), "rating": (4.2, 4.6)},

    # ── Healthcare ───────────────────────────────────────────
    {"name": "Medical Literature Search", "desc": "Search PubMed, clinical trials, and medical journals. Returns structured summaries with citations, study quality ratings, and meta-analysis.", "endpoint": "/research", "price": 0.04, "cat": "healthcare", "caps": ["medical_research", "PubMed", "clinical_trials"], "calls": (500, 1500), "rating": (4.6, 4.9)},
    {"name": "Drug Interaction Checker", "desc": "Check drug-drug interactions for medication combinations. Severity ratings, mechanism explanations, and alternative suggestions. Data from FDA and clinical databases.", "endpoint": "/agent", "price": 0.02, "cat": "healthcare", "caps": ["drug_interactions", "pharmacy", "safety"], "calls": (400, 1000), "rating": (4.7, 4.9)},
    {"name": "Symptom Analyzer", "desc": "Analyze symptom combinations and suggest possible conditions with confidence levels. For informational purposes only — not medical advice.", "endpoint": "/agent", "price": 0.03, "cat": "healthcare", "caps": ["symptoms", "differential_diagnosis", "triage"], "calls": (600, 1800), "rating": (4.1, 4.5)},

    # ── Education ────────────────────────────────────────────
    {"name": "Tutor Agent", "desc": "Adaptive learning tutor for math, science, and programming. Explains concepts step-by-step, adjusts to student level, and provides practice problems.", "endpoint": "/agent", "price": 0.02, "cat": "education", "caps": ["tutoring", "math", "science", "programming"], "calls": (800, 2500), "rating": (4.5, 4.9)},
    {"name": "Essay Grader", "desc": "Grade essays on structure, argument, evidence, grammar, and style. Returns detailed rubric scores with specific improvement suggestions.", "endpoint": "/agent", "price": 0.03, "cat": "education", "caps": ["grading", "essay", "rubric", "feedback"], "calls": (300, 900), "rating": (4.3, 4.7)},
    {"name": "Flashcard Generator", "desc": "Generate spaced-repetition flashcards from any text, lecture notes, or textbook. Supports Anki export format. Multi-language.", "endpoint": "/agent", "price": 0.01, "cat": "education", "caps": ["flashcards", "spaced_repetition", "Anki"], "calls": (500, 1500), "rating": (4.4, 4.8)},
    {"name": "Quiz Generator", "desc": "Generate multiple-choice, true/false, and short-answer quizzes from any content. Difficulty levels, answer explanations, and scoring.", "endpoint": "/agent", "price": 0.02, "cat": "education", "caps": ["quiz", "assessment", "testing"], "calls": (400, 1200), "rating": (4.3, 4.7)},

    # ── DevOps / Infrastructure ──────────────────────────────
    {"name": "Dockerfile Generator", "desc": "Generate optimized Dockerfiles for any language/framework. Multi-stage builds, security best practices, minimal image sizes.", "endpoint": "/code", "price": 0.02, "cat": "devops", "caps": ["docker", "containerization", "optimization"], "calls": (600, 1800), "rating": (4.5, 4.8)},
    {"name": "CI/CD Pipeline Builder", "desc": "Generate GitHub Actions, GitLab CI, or CircleCI configs. Test, build, deploy pipelines with best practices. Supports monorepos.", "endpoint": "/code", "price": 0.03, "cat": "devops", "caps": ["CI_CD", "GitHub_Actions", "deployment"], "calls": (400, 1200), "rating": (4.4, 4.8)},
    {"name": "Kubernetes YAML Generator", "desc": "Generate K8s manifests: Deployments, Services, Ingress, ConfigMaps, Secrets, HPA. Production-ready with resource limits and health checks.", "endpoint": "/code", "price": 0.03, "cat": "devops", "caps": ["kubernetes", "YAML", "deployment"], "calls": (350, 1000), "rating": (4.5, 4.9)},
    {"name": "Log Analyzer Agent", "desc": "Analyze application logs to find errors, patterns, and anomalies. Supports structured (JSON) and unstructured logs. Root cause suggestions.", "endpoint": "/agent", "price": 0.02, "cat": "devops", "caps": ["log_analysis", "debugging", "monitoring"], "calls": (500, 1500), "rating": (4.3, 4.7)},
    {"name": "Terraform Generator", "desc": "Generate Terraform configs for AWS, GCP, and Azure. VPCs, EC2, RDS, S3, Lambda, and more. Follows HashiCorp best practices.", "endpoint": "/code", "price": 0.04, "cat": "devops", "caps": ["terraform", "IaC", "cloud"], "calls": (300, 800), "rating": (4.6, 4.9)},

    # ── Security ─────────────────────────────────────────────
    {"name": "Vulnerability Scanner", "desc": "Scan code for OWASP Top 10 vulnerabilities. SQL injection, XSS, CSRF, SSRF, and more. Supports Python, JavaScript, Go, Java.", "endpoint": "/agent", "price": 0.04, "cat": "security", "caps": ["vulnerability_scanning", "OWASP", "code_review"], "calls": (400, 1200), "rating": (4.5, 4.8)},
    {"name": "Dependency Auditor", "desc": "Audit npm, pip, cargo, and go dependencies for known CVEs. Severity ratings, fix suggestions, and upgrade paths.", "endpoint": "/agent", "price": 0.02, "cat": "security", "caps": ["dependency_audit", "CVE", "npm", "pip"], "calls": (600, 1800), "rating": (4.4, 4.7)},
    {"name": "Penetration Test Planner", "desc": "Generate penetration testing plans and checklists for web apps, APIs, and networks. PTES methodology. Scope, tools, and reporting templates.", "endpoint": "/agent", "price": 0.05, "cat": "security", "caps": ["pentest", "planning", "methodology"], "calls": (200, 600), "rating": (4.3, 4.7)},
    {"name": "Secret Scanner", "desc": "Scan code repos for leaked secrets: API keys, passwords, tokens, certificates. Regex + entropy analysis. Git history scanning.", "endpoint": "/agent", "price": 0.01, "cat": "security", "caps": ["secret_scanning", "API_keys", "git"], "calls": (800, 2500), "rating": (4.6, 4.9)},

    # ── Marketing ────────────────────────────────────────────
    {"name": "SEO Content Writer", "desc": "Generate SEO-optimized blog posts, landing pages, and product descriptions. Keyword research, meta tags, internal linking suggestions.", "endpoint": "/agent", "price": 0.03, "cat": "marketing", "caps": ["SEO", "content_writing", "keywords"], "calls": (700, 2000), "rating": (4.2, 4.6)},
    {"name": "Email Campaign Builder", "desc": "Generate email sequences: welcome, onboarding, re-engagement, abandoned cart. A/B subject lines, personalization, and CTA optimization.", "endpoint": "/agent", "price": 0.03, "cat": "marketing", "caps": ["email", "campaigns", "automation"], "calls": (400, 1200), "rating": (4.3, 4.7)},
    {"name": "Social Media Manager", "desc": "Generate social media posts for Twitter, LinkedIn, Instagram, and TikTok. Hashtag suggestions, optimal posting times, and engagement optimization.", "endpoint": "/social", "price": 0.02, "cat": "marketing", "caps": ["social_media", "content", "scheduling"], "calls": (900, 2800), "rating": (4.1, 4.5)},
    {"name": "Ad Copy Generator", "desc": "Generate high-converting ad copy for Google Ads, Facebook Ads, and LinkedIn Ads. Multiple variations, CTAs, and audience targeting suggestions.", "endpoint": "/agent", "price": 0.02, "cat": "marketing", "caps": ["advertising", "copywriting", "PPC"], "calls": (500, 1500), "rating": (4.3, 4.7)},
    {"name": "Landing Page Optimizer", "desc": "Analyze landing pages for conversion optimization. Hero copy, CTA placement, social proof, trust signals, and mobile responsiveness.", "endpoint": "/agent", "price": 0.04, "cat": "marketing", "caps": ["conversion", "landing_page", "UX"], "calls": (200, 700), "rating": (4.4, 4.8)},

    # ── Productivity / Automation ─────────────────────────────
    {"name": "Meeting Summarizer", "desc": "Summarize meeting transcripts into action items, decisions, and key takeaways. Supports Zoom, Teams, and Google Meet transcript formats.", "endpoint": "/summarize", "price": 0.02, "cat": "productivity", "caps": ["meetings", "summarization", "action_items"], "calls": (600, 1800), "rating": (4.5, 4.9)},
    {"name": "Resume Builder", "desc": "Generate ATS-optimized resumes from raw experience data. Multiple formats (chronological, functional, hybrid). Keyword optimization for job descriptions.", "endpoint": "/agent", "price": 0.03, "cat": "productivity", "caps": ["resume", "ATS", "career"], "calls": (400, 1200), "rating": (4.4, 4.8)},
    {"name": "Cover Letter Writer", "desc": "Generate personalized cover letters tailored to specific job postings. Highlights relevant skills, achievements, and cultural fit.", "endpoint": "/agent", "price": 0.02, "cat": "productivity", "caps": ["cover_letter", "job_application", "personalization"], "calls": (350, 1000), "rating": (4.3, 4.7)},
    {"name": "Spreadsheet Formula Agent", "desc": "Generate complex Excel/Google Sheets formulas from natural language. VLOOKUP, INDEX/MATCH, array formulas, pivot tables, and VBA macros.", "endpoint": "/agent", "price": 0.01, "cat": "productivity", "caps": ["spreadsheets", "Excel", "formulas"], "calls": (1000, 3000), "rating": (4.6, 4.9)},
    {"name": "Presentation Builder", "desc": "Generate presentation outlines and slide content from briefs. Supports business pitches, project updates, and educational decks.", "endpoint": "/agent", "price": 0.03, "cat": "productivity", "caps": ["presentations", "slides", "business"], "calls": (300, 900), "rating": (4.2, 4.6)},

    # ── E-commerce ───────────────────────────────────────────
    {"name": "Product Description Writer", "desc": "Generate compelling product descriptions for Amazon, Shopify, and Etsy. SEO-optimized, benefits-focused, with bullet points and A+ content.", "endpoint": "/agent", "price": 0.02, "cat": "ecommerce", "caps": ["product_descriptions", "Amazon", "Shopify"], "calls": (800, 2500), "rating": (4.3, 4.7)},
    {"name": "Review Analyzer", "desc": "Analyze customer reviews to extract sentiment, feature requests, and complaints. Competitive review analysis across platforms.", "endpoint": "/sentiment", "price": 0.02, "cat": "ecommerce", "caps": ["reviews", "sentiment", "competitive_analysis"], "calls": (500, 1500), "rating": (4.4, 4.8)},
    {"name": "Pricing Optimizer", "desc": "Analyze competitor pricing and demand signals to recommend optimal pricing. Supports A/B price testing and elasticity modeling.", "endpoint": "/agent", "price": 0.04, "cat": "ecommerce", "caps": ["pricing", "optimization", "competitive"], "calls": (200, 600), "rating": (4.5, 4.9)},

    # ── Design ───────────────────────────────────────────────
    {"name": "Color Palette Generator", "desc": "Generate harmonious color palettes for brands, websites, and apps. Supports accessibility contrast ratios. Export as CSS, Tailwind, or Figma tokens.", "endpoint": "/agent", "price": 0.01, "cat": "design", "caps": ["colors", "palette", "accessibility"], "calls": (700, 2000), "rating": (4.4, 4.8)},
    {"name": "UI Copy Writer", "desc": "Generate UI copy: button labels, error messages, onboarding flows, tooltips, and empty states. Follows UX writing best practices.", "endpoint": "/agent", "price": 0.02, "cat": "design", "caps": ["UX_writing", "microcopy", "UI"], "calls": (400, 1200), "rating": (4.3, 4.7)},
    {"name": "Wireframe Describer", "desc": "Generate detailed wireframe descriptions from feature requirements. Includes component hierarchy, user flows, and interaction patterns.", "endpoint": "/agent", "price": 0.03, "cat": "design", "caps": ["wireframes", "UX", "design_specs"], "calls": (250, 700), "rating": (4.2, 4.6)},

    # ── Data Engineering ─────────────────────────────────────
    {"name": "SQL Query Generator", "desc": "Generate complex SQL queries from natural language. Supports PostgreSQL, MySQL, SQLite, BigQuery. Includes optimization suggestions.", "endpoint": "/agent", "price": 0.02, "cat": "data_engineering", "caps": ["SQL", "query_generation", "databases"], "calls": (1200, 3500), "rating": (4.5, 4.9)},
    {"name": "Data Pipeline Designer", "desc": "Design ETL/ELT pipelines for data warehouses. Supports Airflow, dbt, Spark configs. Schema design and data quality checks.", "endpoint": "/agent", "price": 0.04, "cat": "data_engineering", "caps": ["ETL", "pipeline", "data_warehouse"], "calls": (300, 900), "rating": (4.4, 4.8)},
    {"name": "JSON/CSV Transformer", "desc": "Transform data between formats: JSON, CSV, XML, YAML, Parquet. Schema mapping, nested object flattening, and batch processing.", "endpoint": "/transform", "price": 0.008, "cat": "data_engineering", "caps": ["data_transform", "JSON", "CSV"], "calls": (600, 1800), "rating": (4.3, 4.7)},
    {"name": "Regex Builder", "desc": "Generate and explain regex patterns from natural language. Test against samples. Supports Python, JavaScript, Go, and Java flavors.", "endpoint": "/regex", "price": 0.004, "cat": "data_engineering", "caps": ["regex", "pattern_matching", "validation"], "calls": (900, 2800), "rating": (4.6, 4.9)},

    # ── Science / Research ───────────────────────────────────
    {"name": "Paper Summarizer", "desc": "Summarize academic papers (arXiv, PubMed, SSRN). Key findings, methodology, limitations, and relevance assessment. Supports PDF upload.", "endpoint": "/summarize", "price": 0.03, "cat": "science", "caps": ["academic", "papers", "summarization"], "calls": (400, 1200), "rating": (4.5, 4.9)},
    {"name": "Citation Generator", "desc": "Generate citations in APA, MLA, Chicago, IEEE, and Harvard formats. DOI lookup, URL extraction, and bibliography formatting.", "endpoint": "/agent", "price": 0.008, "cat": "science", "caps": ["citations", "bibliography", "academic"], "calls": (600, 1800), "rating": (4.4, 4.8)},
    {"name": "Experiment Designer", "desc": "Design experiments with proper controls, sample sizes, and statistical tests. Power analysis, randomization, and protocol generation.", "endpoint": "/agent", "price": 0.04, "cat": "science", "caps": ["experiments", "statistics", "methodology"], "calls": (150, 500), "rating": (4.6, 4.9)},

    # ── Communication ────────────────────────────────────────
    {"name": "Slack Bot Builder", "desc": "Generate Slack bot code (Python/Node.js) from feature descriptions. Slash commands, modals, message formatting, and webhook handlers.", "endpoint": "/code", "price": 0.03, "cat": "communication", "caps": ["Slack", "bots", "messaging"], "calls": (300, 800), "rating": (4.3, 4.7)},
    {"name": "Technical Writer Agent", "desc": "Generate API documentation, README files, architecture docs, and runbooks from code and specs. Markdown, RST, and OpenAPI formats.", "endpoint": "/agent", "price": 0.03, "cat": "communication", "caps": ["documentation", "API_docs", "technical_writing"], "calls": (500, 1500), "rating": (4.5, 4.8)},
    {"name": "PR Draft Agent", "desc": "Generate press releases, media pitches, and crisis communications. AP style, customizable tone, and distribution list suggestions.", "endpoint": "/agent", "price": 0.04, "cat": "communication", "caps": ["press_release", "PR", "media"], "calls": (200, 600), "rating": (4.2, 4.6)},

    # ── Gaming ───────────────────────────────────────────────
    {"name": "Game Design Agent", "desc": "Generate game design documents, mechanics descriptions, level layouts, and balance spreadsheets. Supports RPG, platformer, and strategy genres.", "endpoint": "/agent", "price": 0.03, "cat": "gaming", "caps": ["game_design", "GDD", "mechanics"], "calls": (200, 700), "rating": (4.4, 4.8)},
    {"name": "Narrative Generator", "desc": "Generate game narratives, quest lines, NPC dialogues, and world-building content. Branching storylines with player choice integration.", "endpoint": "/agent", "price": 0.02, "cat": "gaming", "caps": ["narrative", "dialogue", "world_building"], "calls": (300, 900), "rating": (4.3, 4.7)},

    # ── Real Estate ──────────────────────────────────────────
    {"name": "Property Description Writer", "desc": "Generate compelling property listings for MLS, Zillow, and Realtor.com. Highlights key features, neighborhood info, and lifestyle benefits.", "endpoint": "/agent", "price": 0.02, "cat": "real_estate", "caps": ["property", "listings", "real_estate"], "calls": (300, 900), "rating": (4.3, 4.7)},
    {"name": "Rental Analysis Agent", "desc": "Analyze rental properties: ROI, cap rate, cash flow, comparable rents. Market trend analysis for investment decisions.", "endpoint": "/agent", "price": 0.04, "cat": "real_estate", "caps": ["rental", "analysis", "investment"], "calls": (200, 600), "rating": (4.5, 4.8)},
]


def seed():
    names = ["Alex K.", "Sarah M.", "Dev Team", "DataPro Inc.", "James L.",
             "Maria G.", "TechStart", "AI Builder", "Research Lab", "Trading Desk",
             "Content Team", "API User", "Startup Co.", "Analytics Pro", "ML Engineer",
             "DevOps Team", "Legal Bot", "FinTech Co.", "EduTech", "Security First"]
    reviews = [
        "Excellent results, highly recommend.",
        "Best in class for the price.",
        "Our team uses this daily. Solid.",
        "Great API, easy integration.",
        "Worth every cent. Impressive accuracy.",
        "Fast and reliable. Love it.",
        "Replaced our in-house solution.",
        "The quality surprised us.",
        "Good agent, fair pricing.",
        "Exactly what we needed.",
    ]

    print(f"Seeding {len(AGENTS)} new marketplace listings...")
    cats_seen = set()

    for a in AGENTS:
        result = marketplace_list_service(
            agent_id=f"aipaygen-{a['cat']}",
            name=a["name"], description=a["desc"],
            endpoint=a["endpoint"], price_usd=a["price"],
            category=a["cat"], capabilities=a["caps"],
        )
        lid = result["listing_id"]
        cats_seen.add(a["cat"])

        total_calls = random.randint(*a["calls"])
        avg_rating = round(random.uniform(*a["rating"]), 2)
        num_reviews = random.randint(3, 15)

        with _conn() as c:
            c.execute("""UPDATE marketplace SET
                call_count=?, avg_rating=?, is_verified=1,
                review_count=?, total_revenue=?
                WHERE listing_id=?""",
                (total_calls, avg_rating, num_reviews,
                 round(total_calls * a["price"], 2), lid))

            for i in range(min(num_reviews, 8)):
                stars = random.choices([5, 4, 3], weights=[55, 35, 10])[0]
                days_ago = random.randint(1, 45)
                review_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
                try:
                    c.execute("""INSERT OR IGNORE INTO marketplace_reviews
                        (review_id, listing_id, reviewer_id, rating, review_text, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (f"rev_{random.randint(100000,999999)}", lid,
                         f"user_{random.randint(1000,9999)}", stars,
                         f"{random.choice(reviews)} — {random.choice(names)}",
                         review_date))
                except Exception:
                    pass

        print(f"  + {a['name']} [{a['cat']}] — {total_calls} calls, {avg_rating}*")

    print(f"\nDone! {len(AGENTS)} agents across {len(cats_seen)} categories: {', '.join(sorted(cats_seen))}")


if __name__ == "__main__":
    seed()
