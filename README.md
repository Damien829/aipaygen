# AiPayGent MCP Server

<!-- mcp-name: io.github.djautomd-lab/aipaygent -->

36 Claude-powered AI tools available as an MCP server. Connect directly as a remote server or run locally.

## Remote (no setup)

Connect your MCP client to:
```
https://mcp.aipaygent.xyz/mcp
```

## Local (stdio)

```bash
pip install aipaygent-mcp
aipaygent-mcp
```

Requires `ANTHROPIC_API_KEY` in your environment.

## Tools

| Tool | Description |
|------|-------------|
| `research` | Research any topic — summary, key points, sources |
| `summarize` | Compress text (short / medium / detailed) |
| `analyze` | Structured analysis with findings and confidence |
| `translate` | Translate to any language |
| `social` | Platform-optimized posts for Twitter, LinkedIn, Instagram |
| `write` | Articles, copy, content to spec |
| `code` | Generate code in any language |
| `extract` | Pull structured JSON from unstructured text |
| `qa` | Q&A over a document with source quote |
| `classify` | Classify text into your categories |
| `sentiment` | Polarity, score, emotions, key phrases |
| `keywords` | Extract keywords and topics |
| `compare` | Compare two texts with similarity score |
| `transform` | Rewrite, reformat, expand, condense |
| `chat` | Stateless multi-turn Claude chat |
| `plan` | Step-by-step action plan for any goal |
| `decide` | Decision framework with pros, cons, recommendation |
| `proofread` | Grammar corrections with quality score |
| `explain` | Explain any concept at any level |
| `questions` | Generate FAQ, interview, quiz questions |
| `outline` | Hierarchical outline with subsections |
| `email` | Compose professional emails |
| `sql` | Natural language to SQL |
| `regex` | Regex pattern from plain English |
| `mock` | Generate realistic mock data |
| `score` | Score content on a custom rubric |
| `timeline` | Extract chronological timeline from text |
| `action` | Extract action items and owners |
| `pitch` | Generate elevator pitch (15s / 30s / 60s) |
| `debate` | Arguments for and against any position |
| `headline` | Generate headline variations |
| `fact` | Extract factual claims with verifiability scores |
| `rewrite` | Rewrite for a target audience or brand voice |
| `tag` | Auto-tag content with taxonomy or free-form |
| `pipeline` | Chain up to 5 tools with `{{prev}}` output passing |
| `batch` | Run up to 5 tools in one call |

## Claude Desktop Config

```json
{
  "mcpServers": {
    "aipaygent": {
      "command": "aipaygent-mcp"
    }
  }
}
```

## Links

- REST API: https://api.aipaygent.xyz
- Discover: https://api.aipaygent.xyz/discover
- OpenAPI: https://api.aipaygent.xyz/openapi.json
