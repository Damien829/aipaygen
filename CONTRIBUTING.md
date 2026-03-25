# Contributing to aipaygen-mcp

Thanks for your interest in contributing. This guide covers the basics.

## Getting started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/aipaygen.git
   cd aipaygen
   ```
3. Install in development mode:
   ```bash
   pip install -e ".[dev]"
   ```
4. Create a branch for your change:
   ```bash
   git checkout -b my-feature
   ```

## What to contribute

- **New tools**: Add MCP tool wrappers for new API endpoints
- **Bug fixes**: Fix issues with existing tool definitions or error handling
- **Documentation**: Improve docstrings, examples, or README
- **Tests**: Increase test coverage
- **Compatibility**: Improve support for different MCP clients

## Adding a new tool

1. Open `src/aipaygen_mcp/server.py`
2. Add your tool function with the `@mcp.tool()` decorator:
   ```python
   @mcp.tool()
   def my_tool(param: str) -> dict:
       """Clear description of what this tool does."""
       return _call("endpoint", {"param": param})
   ```
3. Write a docstring that clearly explains what the tool does and its parameters — this is what AI agents see when they discover tools
4. Add tests in `tests/`

## Code style

- Keep it simple. Each tool is a thin wrapper — no complex logic in the client.
- Use type hints for all function parameters.
- Write clear, concise docstrings. They serve as tool descriptions for AI agents.
- No additional dependencies beyond `mcp` unless absolutely necessary.

## Pull requests

1. Keep PRs focused — one feature or fix per PR
2. Include a short description of what changed and why
3. Make sure `pytest` passes
4. Update the README tool table if you added new tools

## Reporting issues

Open an issue with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and MCP client (Claude Desktop, Cursor, etc.)

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be respectful and constructive.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
