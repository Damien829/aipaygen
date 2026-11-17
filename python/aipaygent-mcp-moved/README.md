# aipaygent-mcp has moved to aipaygen-mcp

This project was renamed **AIPayGen** (aipaygen.com). The package is now
[`aipaygen-mcp`](https://pypi.org/project/aipaygen-mcp/), and the old service at aipaygent.xyz is
no longer running.

This final release keeps existing setups working: the `aipaygent-mcp` command now runs
`aipaygen-mcp`. Please switch your MCP client config to the new name:

```
uvx aipaygen-mcp
```

or, with Node: `npx -y aipaygen-mcp`. Docs: https://aipaygen.com/docs
