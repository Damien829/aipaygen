# Skill Harvester Design

## Goal
Build `skill_harvester.py` — a multi-source crawler that discovers external tools/APIs and absorbs them as skills into `skills.db` via the existing absorption pipeline.

## Sources
1. **MCP Registries**: mcp.so, smithery.ai, mcpindex.net, glama.ai
2. **GitHub Awesome Lists**: awesome-mcp-servers, awesome-ai-agents, public-apis
3. **API Directories**: apis.guru, Postman public collections

## Architecture
- Single file `skill_harvester.py` with `SkillHarvester` class
- Per-source harvest methods
- Dedup by skill name before absorbing
- Logging to `harvest_log.db`
- Conservative rate limiting (1 req/sec, robots.txt)

## Modes
- Batch: `python skill_harvester.py --batch`
- Scheduled: APScheduler daily at 4 AM

## Integration
- Register scheduler job in `app.py`
- Reuse existing `skills.db` schema and absorption logic
