# Lesson 04: Building the Marketplace

## What You Will Build

A complete agent marketplace: listing agents with categories and pricing, full-text search, reviews and ratings, seller analytics, payment splits (95/5), and a leaderboard. This turns your API from a single product into a platform.

## The Marketplace Schema

The marketplace table is the heart of the platform. Notice how it tracks both metadata (name, description, category) and performance metrics (call_count, avg_rating, total_revenue) directly on the listing:

```python
def init_memory_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS marketplace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id TEXT UNIQUE NOT NULL,
                agent_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                endpoint TEXT NOT NULL,
                price_usd REAL NOT NULL,
                category TEXT,
                capabilities TEXT,
                call_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                avg_rating REAL DEFAULT 0.0,
                review_count INTEGER DEFAULT 0,
                total_revenue REAL DEFAULT 0.0,
                is_verified INTEGER DEFAULT 0,
                wallet_address TEXT DEFAULT '',
                pricing_models TEXT DEFAULT '{}',
                tags TEXT DEFAULT '[]',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_mp_category ON marketplace(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mp_active ON marketplace(is_active)")
```

Denormalizing `avg_rating` and `review_count` onto the listing avoids a JOIN on every search query. When a review is added, we update these counters. This is a deliberate trade-off: slightly more complex writes for dramatically faster reads.

## Listing an Agent

Any developer with an API key can list their agent. The function handles both creating new listings and updating existing ones using the agent_id + name as a natural key:

```python
import uuid as _uuid

def marketplace_list_service(agent_id: str, name: str, description: str,
                              endpoint: str, price_usd: float,
                              category: str = "general",
                              capabilities: list = None,
                              wallet_address: str = "",
                              tags: list = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    caps_str = json.dumps(capabilities or [])
    tags_str = json.dumps(tags or [])
    listing_id = str(_uuid.uuid4())
    
    with _conn() as c:
        existing = c.execute(
            "SELECT listing_id FROM marketplace WHERE agent_id=? AND name=?",
            (agent_id, name)
        ).fetchone()
        
        if existing:
            listing_id = existing["listing_id"]
            c.execute("""
                UPDATE marketplace SET description=?, endpoint=?, price_usd=?,
                    category=?, capabilities=?, wallet_address=?,
                    tags=?, is_active=1, updated_at=?
                WHERE listing_id=?
            """, (description, endpoint, price_usd, category, caps_str,
                  wallet_address, tags_str, now, listing_id))
        else:
            c.execute("""
                INSERT INTO marketplace (listing_id, agent_id, name, description,
                    endpoint, price_usd, category, capabilities, wallet_address,
                    tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (listing_id, agent_id, name, description, endpoint,
                  price_usd, category, caps_str, wallet_address,
                  tags_str, now, now))
    
    return {"listing_id": listing_id, "listed": True}
```

The `wallet_address` field is the seller's API key — this is how payments get routed to the right person.

## Search with Sorting

The search function supports full-text matching across names, descriptions, capabilities, and tags. Sorting by popularity, newest, price, or rating lets the front end provide different browsing experiences:

```python
def marketplace_search(query="", category=None, max_price=None,
                       min_price=None, sort="popular",
                       page=1, per_page=20):
    conditions = ["is_active = 1"]
    params = []
    
    if query:
        conditions.append(
            "(name LIKE ? OR description LIKE ? OR capabilities LIKE ? OR tags LIKE ?)"
        )
        q = f"%{query}%"
        params.extend([q, q, q, q])
    if category:
        conditions.append("category = ?")
        params.append(category)
    if max_price is not None:
        conditions.append("price_usd <= ?")
        params.append(max_price)

    where = " AND ".join(conditions)
    sort_sql = {
        "popular": "call_count DESC",
        "newest": "created_at DESC",
        "price_low": "price_usd ASC",
        "rating": "avg_rating DESC",
    }.get(sort, "call_count DESC")

    with _conn() as c:
        total = c.execute(
            f"SELECT COUNT(*) FROM marketplace WHERE {where}", params
        ).fetchone()[0]
        offset = (page - 1) * per_page
        rows = c.execute(
            f"SELECT * FROM marketplace WHERE {where} "
            f"ORDER BY {sort_sql} LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()
    
    return [dict(r) for r in rows], total
```

Yes, `LIKE` queries are slow at scale. At 10,000 listings, you would migrate to SQLite FTS5. At the marketplace stage (under 1,000 listings), this is perfectly fine.

## Reviews and Ratings

Reviews use a separate table with a CHECK constraint on the rating:

```python
c.execute("""CREATE TABLE IF NOT EXISTS marketplace_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT UNIQUE NOT NULL,
    listing_id TEXT NOT NULL,
    reviewer_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
    review_text TEXT DEFAULT '',
    verified INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
)""")

def marketplace_add_review(listing_id, reviewer_id, rating,
                           review_text="", verified=False):
    now = datetime.now(timezone.utc).isoformat()
    review_id = str(_uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO marketplace_reviews "
            "(review_id, listing_id, reviewer_id, rating, review_text, verified, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (review_id, listing_id, reviewer_id, rating, review_text,
             1 if verified else 0, now)
        )
        # Update denormalized avg_rating and review_count
        row = c.execute(
            "SELECT AVG(rating), COUNT(*) FROM marketplace_reviews WHERE listing_id = ?",
            (listing_id,)
        ).fetchone()
        c.execute(
            "UPDATE marketplace SET avg_rating = ?, review_count = ? WHERE listing_id = ?",
            (round(row[0], 2), row[1], listing_id)
        )
    return {"review_id": review_id, "rating": rating}
```

The `verified` flag marks reviews from users who actually called the agent. Trust signals matter for marketplace quality.

## Payment Splits: 95/5

When someone calls a marketplace agent, the platform takes 5% and the seller gets 95%. Payments are queued for batch settlement:

```python
def queue_seller_payment(seller_wallet: str, seller_amount: float,
                         platform_fee: float, listing_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO payment_splits "
            "(listing_id, seller_wallet, seller_amount, platform_fee, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (listing_id, seller_wallet, seller_amount, platform_fee, now),
        )
    return {"seller_amount": seller_amount, "platform_fee": platform_fee,
            "status": "pending"}

def run_batch_payouts() -> dict:
    """Process pending seller payments, grouped by seller."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, seller_wallet, seller_amount, platform_fee "
            "FROM payment_splits WHERE status = 'pending'"
        ).fetchall()
        
        seller_totals = {}
        ids = []
        for r in rows:
            r = dict(r)
            wallet = r["seller_wallet"]
            if wallet not in seller_totals:
                seller_totals[wallet] = 0.0
            seller_totals[wallet] += r["seller_amount"]
            ids.append(r["id"])
        
        if ids:
            placeholders = ",".join("?" for _ in ids)
            c.execute(
                f"UPDATE payment_splits SET status = 'processed' "
                f"WHERE id IN ({placeholders})", ids
            )
    
    return {"sellers_paid": len(seller_totals),
            "total_amount": sum(seller_totals.values())}
```

## Agent Certification

Quality control for the marketplace. Agents that meet thresholds (50+ calls, 4.0+ rating, 7+ days listed) earn a verified badge:

```python
def certify_agent(listing_id: str) -> dict:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM marketplace WHERE listing_id = ?", (listing_id,)
        ).fetchone()
        agent = dict(row)
        
        if agent.get("call_count", 0) < 50:
            return {"certified": False, "reason": "Insufficient calls (need 50)"}
        if agent.get("avg_rating", 0) < 4.0:
            return {"certified": False, "reason": "Rating too low (need 4.0)"}
        
        c.execute(
            "UPDATE marketplace SET is_verified = 1 WHERE listing_id = ?",
            (listing_id,)
        )
    return {"certified": True}
```

## Exercise

1. Create the marketplace tables (listings, reviews, payment_splits).
2. Implement `marketplace_list_service` and `marketplace_search`.
3. Build API endpoints: `POST /marketplace/list`, `GET /marketplace/search?q=trading`.
4. Add reviews: `POST /marketplace/review` with rating 1-5.
5. Test the payment split flow: call an agent, verify 95% goes to seller, 5% to platform.

Next lesson: making your agents discoverable to the world.
