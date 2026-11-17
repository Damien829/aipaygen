# AIPayGen

[AIPayGen](https://aipaygen.com) gives AI agents 100+ tools they pay for per call, and gives websites
[AI Terms](https://aipaygen.com/ai-terms): a way to say what AI may do with their pages, per use, and to be
paid when a use has a price.

This repository holds the open-source MCP packages. The hosted service itself is not open source.

| Package | Install | Source |
|---|---|---|
| `aipaygen-mcp` on npm | `npx -y aipaygen-mcp` | [npm/aipaygen-mcp](npm/aipaygen-mcp) |
| `aipaygen-mcp` on PyPI | `uvx aipaygen-mcp` | [python/aipaygen-mcp](python/aipaygen-mcp) |
| `aipaygent-mcp` on PyPI (old name, forwards to the above) | | [python/aipaygent-mcp-moved](python/aipaygent-mcp-moved) |

Both packages relay a stdio MCP client (Claude Desktop, Cursor, Claude Code, VS Code, Windsurf and others) to
the hosted server at `https://mcp.aipaygen.com/mcp`. You can also point a client at that URL directly.

```json
{ "mcpServers": { "aipaygen": { "command": "npx", "args": ["-y", "aipaygen-mcp"] } } }
```

Tools, prices and docs: [aipaygen.com/tools](https://aipaygen.com/tools) and [aipaygen.com/docs](https://aipaygen.com/docs).

## For websites

The site integrations (WordPress, Cloudflare Workers, Nginx, Apache, Caddy, Next.js, Express, Django), the
AI Terms spec, its JSON Schema, test vectors and a Python reader are in
[Damien829/pay-per-crawl](https://github.com/Damien829/pay-per-crawl).

## Contact

Questions, bugs and security reports: hello@aipaygen.com, or open an issue here.

## License

MIT ([LICENSE](LICENSE)) for everything in this repository.

## Name and trademarks

AIPayGen™ and the AIPayGen logo are trademarks of AIPayGen. The licence covers the code, not the name: please
don't use the name or logo for another product or package, or in a way that suggests we run or endorse it.
Saying that your tool "works with AIPayGen" is fine.
