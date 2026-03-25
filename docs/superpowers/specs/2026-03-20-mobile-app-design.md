# AiPayGen Mobile App — Design Spec

**Date:** 2026-03-20
**Status:** Approved
**Platform:** iOS, Android, Web (single Expo codebase)

## Overview

Consumer-facing app that wraps the existing AiPayGen API (api.aipaygen.com) in a polished chat-first interface with an AI workflow builder and marketplace. Two audiences: end users who interact via natural language, and developers who manage API keys and usage. Monetized via x402 USDC micropayments (paid tier) and AdMob ads (free tier).

The killer feature: a workflow builder that lets users chain 250+ AI tools into reusable automations, share them publicly, or sell them on a built-in marketplace.

Name TBD — consumer-friendly brand separate from the AiPayGen backend brand.

## Architecture

```
Expo App (one codebase) → iOS / Android / Web
├── Chat UI (home tab)
├── Explore (tool browser tab)
├── Workflows (builder + marketplace tab)
├── Wallet (payments tab)
├── Profile (settings tab)
├── API Client Layer (REST + SSE to api.aipaygen.com)
├── x402 Payment Signing (wallet-based)
└── Ad Layer (AdMob — free tier only)

Backend: api.aipaygen.com (existing Flask)
- 250+ AI tools, 4121 skills, 27 models, 10 providers
- x402 micropayments, wallet auth (CAIP-122)
- Existing /workflow and /chain endpoints for multi-step execution
- Minimal backend additions: /stream/chat SSE endpoint (added),
  workflow CRUD + marketplace endpoints (to add)
```

The app is a thin client. All AI processing, tool execution, and payment verification happen on the backend.

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Framework | Expo SDK 52 + Expo Router v4 | File-based routing, one codebase for all platforms |
| UI | NativeWind v4 | Tailwind CSS for React Native — fast polish |
| State | Zustand | Lightweight, no boilerplate |
| Data fetching | React Query + fetch | Caching, retry, background refresh |
| Wallet | @coinbase/wallet-sdk + WalletConnect | x402 on Base requires EVM wallet |
| Ads | react-native-google-mobile-ads | AdMob — banner, interstitial, rewarded |
| Auth | Wallet-based (CAIP-122 sign-in) | Uses existing /agents/challenge endpoint |
| Streaming | SSE via fetch + ReadableStream | Token-by-token chat streaming |
| Storage | expo-secure-store + AsyncStorage | Wallet keys (secure) + prefs/chat history (async) |
| Workflow canvas | react-native-reanimated + gesture-handler | Drag-and-drop node editor |
| Icons | lucide-react-native | Clean, consistent icon set |

## Screen Map

### Tab Bar (5 tabs)

```
┌────────┬─────────┬───────────┬────────┬─────────┐
│  Chat  │ Explore │ Workflows │ Wallet │ Profile │
└────────┴─────────┴───────────┴────────┴─────────┘
```

### Chat (Home Tab)
- Conversation list (local storage)
- New chat opens full-screen chat UI
- Text input with send button
- Streaming responses (token-by-token via SSE from POST /stream/chat)
- Smart tool detection: "translate this to Spanish" auto-routes to /translate
- Rich result rendering: code blocks with syntax highlighting, tables, formatted data
- Model selector in header (defaults to llama-local for free, user picks for paid)
- "Save as workflow" button — converts a chat session into a reusable workflow
- Banner ad fixed at bottom (free tier only)

### Explore (Tool Browser Tab)
- Category grid: Research, Code, Finance, Data, Creative, etc. (20 categories from /skills)
- Search bar: type anything, matched to the right tool
- Featured/trending tools section
- Tool detail screen: description, input fields, "Try it" button, results display
- "Add to workflow" button on each tool
- Inline ad between results (free tier only)

### Workflows (Builder + Marketplace Tab)
- Two sub-tabs: **My Workflows** | **Marketplace**

#### My Workflows
- List of user's saved workflows with run count, last run time
- "New Workflow" button → opens builder (3 creation modes, see below)
- Tap workflow → run it, edit it, or publish to marketplace

#### Workflow Builder (3 Creation Modes)

**Mode 1: Visual Canvas (drag-and-drop)**
- Node-based editor: each tool is a draggable node
- Connect nodes with lines to define data flow
- Nodes: tool selector → configure inputs → connect output to next node's input
- Special nodes: Start (trigger/input), Condition (if/else), Loop, Output
- Pinch to zoom, pan to navigate
- Preview panel shows live data flow

**Mode 2: Step-by-Step Wizard**
- Guided form for mobile-friendly workflow creation
- Step 1: Name your workflow + describe what it does
- Step 2: Pick first tool from category grid
- Step 3: Configure inputs (some auto-filled from previous step's output)
- Step 4: Add next tool or finish
- Visual preview of the chain as you build

**Mode 3: Natural Language**
- Text input: "Research a topic, summarize it, translate to Spanish, format as a blog post"
- AI parses the description and builds the workflow automatically
- Uses existing /workflow endpoint to decompose the goal into tool chain
- User reviews and edits the generated workflow before saving
- Can switch to visual canvas to fine-tune

#### Workflow Execution
- Tap "Run" on any workflow
- Input form for required parameters (e.g., "topic", "target language")
- Execution shows step-by-step progress: each tool lights up as it runs
- Output displays at the end with all intermediate results collapsible
- Cost shown upfront (sum of tool prices) before execution
- Each tool in the chain is a separate x402 payment

#### Marketplace
- Browse published workflows by category, popularity, price
- Search workflows by what they do
- Workflow detail page: description, author, run count, rating, price, tool chain preview
- "Use this workflow" → one-tap to add to My Workflows
- Free workflows: anyone can use, creator gets attribution
- Paid workflows: price set by creator in USDC
  - Creator gets 70%
  - AiPayGen gets 30% platform fee
  - Plus tool execution fees on every run (separate x402 payments)
- Rating system: 1-5 stars after running a workflow
- Creator profiles: wallet address as identity, total earnings, published workflows

### Wallet (Payments Tab)
- Connect wallet button (WalletConnect / Coinbase Wallet)
- USDC balance on Base
- Transaction history (x402 payments + workflow marketplace purchases)
- Earnings dashboard (for workflow creators — sales, execution royalties)
- "Watch ad for +3 calls" rewarded video button
- Buy USDC link (Coinbase onramp)

### Profile (Settings Tab)
- Usage stats: calls today, total calls, favorite tools, workflows run
- Creator stats: published workflows, total earnings, ratings
- Settings: theme (dark/light), default model preference, notifications
- Developer mode toggle: shows API key management, docs link, endpoint testing
- About / support / legal

## Monetization

### Free Tier (no wallet)
- 3 free calls per day (enforced server-side by IP; client tracks locally for UX)
- Model restricted to llama-local (self-hosted, $0 cost)
- Can create and save workflows (up to 3)
- Cannot publish to marketplace
- Banner ad on every screen
- Interstitial ad after each free call
- After 3 calls: hard gate → "Connect wallet" or "Watch ad"
- Rewarded video ad: watch 15-30s video → earn +3 calls

### Paid Tier (wallet connected + USDC balance)
- Unlimited calls via x402 micropayments ($0.01-$0.10 per call)
- Zero ads
- All 27 models available (user selects)
- Unlimited workflow creation
- Can publish workflows to marketplace (free or paid)
- Priority routing (no queue)

### Revenue Streams
1. **x402 tool execution** — every API call in chat or workflow pays per-call in USDC
2. **Marketplace platform fee** — 30% of paid workflow sales
3. **AdMob ads** — banner + interstitial + rewarded video (free tier)
4. **Website AdSense** — banner ads on aipaygen.com (already integrated)

### Ad Strategy (AdMob)
- Banner ads: bottom of chat screen, tool detail screens, marketplace browse
- Interstitial ads: full-screen after each free call completes
- Rewarded video ads: user-initiated, grants +3 free calls
- All ads removed when wallet is connected with USDC balance

## Authentication Flow

```
1. App opens → anonymous session (3 free calls/day enforced server-side by IP)
2. User taps "Connect Wallet" → WalletConnect / Coinbase Wallet modal
3. Wallet signs CAIP-122 challenge from POST /agents/challenge
4. App sends signature to POST /agents/verify → receives JWT
5. JWT stored in expo-secure-store, attached to all API calls
6. x402 payments: app constructs payment header per 402 response, wallet signs
7. Marketplace purchases: direct USDC transfer to escrow contract, backend verifies
```

No email/password auth. Wallet IS the identity.

## Data Flow: Chat Message

```
1. User types message → app sends POST /stream/chat with messages array
2. If free tier: check local call count (3/day limit)
   - If exhausted: show "Watch ad or connect wallet" gate
3. If paid tier: backend returns 402 → app reads X-Payment header
   - App constructs x402 payment via facilitator → wallet signs → retries
4. Backend streams response via SSE (text/event-stream)
5. App renders tokens as they arrive
6. On completion: update local chat history (AsyncStorage)
7. If free tier: show interstitial ad
```

## Data Flow: Workflow Execution

```
1. User taps "Run" on a workflow → input form shown
2. App displays cost estimate (sum of tool prices in the chain)
3. User confirms → app sends POST /chain with steps array
4. If paid workflow from marketplace:
   - First payment: workflow price to creator (70%) + platform (30%)
   - Then: each tool step pays via x402
5. Backend executes tools sequentially, returning results
6. App shows step-by-step progress (each step lights up)
7. Final output displayed with all intermediate results collapsible
8. Workflow run count incremented
```

## Backend Additions Required

### Workflow CRUD (new endpoints)
```
POST   /workflows              — create/save a workflow
GET    /workflows               — list user's workflows
GET    /workflows/:id           — get workflow detail
PUT    /workflows/:id           — update workflow
DELETE /workflows/:id           — delete workflow
POST   /workflows/:id/run       — execute a workflow
POST   /workflows/:id/publish   — publish to marketplace
```

### Marketplace (new endpoints)
```
GET    /marketplace/workflows           — browse published workflows
GET    /marketplace/workflows/:id       — workflow detail + reviews
POST   /marketplace/workflows/:id/buy   — purchase a paid workflow
POST   /marketplace/workflows/:id/rate  — rate a workflow (1-5 stars)
GET    /marketplace/creators/:wallet    — creator profile + earnings
```

### Streaming (already added)
```
POST   /stream/chat             — SSE streaming chat (added)
```

### Workflow Data Model
```
workflows table:
  id, creator_wallet, name, description, steps (JSON),
  is_public, price_usdc, category, run_count, avg_rating,
  created_at, updated_at

workflow_ratings table:
  id, workflow_id, rater_wallet, stars, comment, created_at

workflow_purchases table:
  id, workflow_id, buyer_wallet, price_usdc, creator_share,
  platform_share, tx_hash, created_at
```

## File Structure

```
app/
├── (tabs)/
│   ├── _layout.tsx              # Tab navigator with 5 tabs
│   ├── index.tsx                 # Chat tab (home)
│   ├── explore.tsx               # Tool browser
│   ├── workflows.tsx             # Workflows tab (my + marketplace)
│   ├── wallet.tsx                # Wallet & payments
│   └── profile.tsx               # Settings & stats
├── chat/
│   └── [id].tsx                  # Individual chat screen
├── tool/
│   └── [slug].tsx                # Tool detail screen
├── workflow/
│   ├── [id].tsx                  # Workflow detail / run screen
│   ├── builder.tsx               # Visual canvas builder
│   ├── wizard.tsx                # Step-by-step wizard
│   └── natural.tsx               # Natural language builder
├── marketplace/
│   ├── index.tsx                 # Browse marketplace
│   └── [id].tsx                  # Marketplace workflow detail
├── _layout.tsx                   # Root layout (providers, theme)
└── +not-found.tsx                # 404
lib/
├── api.ts                        # API client (fetch + auth headers)
├── x402.ts                       # x402 payment construction & signing
├── wallet.ts                     # Wallet connection & session
├── ads.ts                        # AdMob initialization & helpers
├── workflow.ts                   # Workflow builder logic & serialization
└── store.ts                      # Zustand stores (auth, chat, prefs, workflows)
components/
├── ChatBubble.tsx                # Message bubble (user/assistant)
├── ChatInput.tsx                 # Text input + send button
├── StreamingText.tsx             # Token-by-token text renderer
├── ToolCard.tsx                  # Tool card for explore grid
├── CategoryGrid.tsx              # Category selection grid
├── WalletButton.tsx              # Connect/disconnect wallet
├── AdBanner.tsx                  # Banner ad wrapper
├── AdInterstitial.tsx            # Interstitial ad trigger
├── AdRewarded.tsx                # Rewarded video ad
├── PayGate.tsx                   # "Out of free calls" gate modal
├── workflow/
│   ├── Canvas.tsx                # Drag-and-drop node canvas
│   ├── Node.tsx                  # Individual tool node
│   ├── Connection.tsx            # Line connecting two nodes
│   ├── NodePalette.tsx           # Tool picker sidebar
│   ├── StepCard.tsx              # Wizard mode step card
│   ├── ExecutionProgress.tsx     # Step-by-step run progress
│   └── WorkflowPreview.tsx       # Compact workflow chain preview
├── marketplace/
│   ├── WorkflowListItem.tsx      # Marketplace browse card
│   ├── CreatorBadge.tsx          # Creator wallet + stats
│   ├── RatingStars.tsx           # Star rating display/input
│   └── PriceTag.tsx              # USDC price display
```

## Design Aesthetic

- Dark theme by default (matches existing AiPayGen site — #020408 background)
- Light theme option
- IBM Plex Mono for code, system font (SF Pro / Roboto) for UI text
- Accent color: indigo (#6366f1) — matches existing site
- Workflow canvas: dark grid background, glowing connection lines, color-coded nodes by category
- Smooth animations: message slide-in, tool card press feedback, streaming text cursor, node snap-to-grid
- Premium feel: generous spacing, subtle shadows, rounded corners (12px)

## Error Handling

- Network errors: retry with exponential backoff (React Query handles this)
- 402 responses: automatically trigger x402 payment flow
- Insufficient USDC: show "Top up wallet" prompt with Coinbase onramp link
- Wallet disconnect mid-session: gracefully fall back to free tier
- Streaming interruption: show partial response with "Retry" button
- Workflow step failure: show which step failed, allow retry from that step
- Marketplace purchase failure: refund if tool execution fails after purchase

## Testing Strategy

- Unit tests: Zustand stores, x402 payment construction, API client, workflow serialization
- Component tests: ChatBubble, PayGate, ToolCard, Canvas, Node rendering
- E2E: Detox (mobile) — chat flow, wallet connect, tool execution, workflow build + run
- Web E2E: Playwright — same flows on web build
- Workflow tests: build a 3-step workflow, execute, verify outputs chain correctly
