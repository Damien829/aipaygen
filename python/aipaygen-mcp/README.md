# aipaygen-mcp

Use [AIPayGen Site Intel](https://aipaygen.com) from any stdio MCP client.
This package relays to the hosted server at `https://mcp.aipaygen.com/mcp`
and has no dependencies.

**Version 2.0 replaces the old 65+ tool package.** The tools are now focused
on website and company intelligence:

| Tool | Price |
|---|---|
| `dns_lookup` | $0.001 |
| `security_headers` | $0.001 |
| `domain_whois` | $0.002 |
| `email_security` | $0.002 |
| `site_metadata` | $0.002 |
| `page_to_markdown` | $0.002 |
| `ssl_certificates` | $0.003 |
| `tech_stack` | $0.003 |
| `company_profile` | $0.01 |
| `domain_report` | $0.02 |

Free: `pricing`, `create_api_key`, `account_balance`. Failed calls are never charged.

## Setup

```json
{
  "mcpServers": {
    "aipaygen": {
      "command": "uvx",
      "args": ["aipaygen-mcp"],
      "env": { "AIPAYGEN_API_KEY": "apg_..." }
    }
  }
}
```

No key yet? Call the `create_api_key` tool for free trial credits, or get one
at https://aipaygen.com.

If your client supports remote servers, you can skip this package and connect
to `https://mcp.aipaygen.com/mcp` directly with an
`Authorization: Bearer apg_...` header.
