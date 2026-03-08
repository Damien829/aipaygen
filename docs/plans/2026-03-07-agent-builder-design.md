# Agent Builder Design

## Overview
"Build Your Own AI Agent" feature for AiPayGen. Three tiers: templates (beginners), web UI builder (intermediate), API (developers). Agents run on-demand or on schedules (loop/cron/event).

## Data Model
- `agents_custom` table: id, creator_key, name, avatar_url, system_prompt, tools (JSON), model, memory_enabled, knowledge_base (JSON), template_id, schedule (JSON), price_per_use, marketplace, is_public, status, created_at, updated_at
- `agent_templates` table: same shape + category, description
- `agent_runs` table: id, agent_id, task, result, status, triggered_by, created_at

## Scheduling
- Loop: APScheduler IntervalTrigger
- Cron: APScheduler CronTrigger
- Event: webhook/message triggers
- All run as background thread in Flask app

## Endpoints
- GET /builder — visual builder page
- GET /builder/templates — browse templates
- POST /agents/build — create agent
- GET/PUT/DELETE /agents/{id} — manage
- POST /agents/{id}/run — execute task
- POST /agents/{id}/schedule — set schedule
- GET /agents/{id}/runs — execution history

## MCP Tools (99 -> 106)
create_agent, list_my_agents, run_agent, schedule_agent, pause_agent, get_agent_runs, delete_agent

## Templates (10 starters)
Research Agent, Crypto Tracker, Content Writer, Customer Support, Social Media Manager, Code Helper, Data Analyst, News Monitor, Personal Assistant, Sales Bot

## Monetization
Free by default, optional per-use pricing on marketplace. Platform takes cut on paid agents.
