"""The old entry point. Says the package moved (on stderr, so the MCP stream on stdout stays clean)
and runs the new one."""
import sys


def main():
    sys.stderr.write("aipaygent-mcp has moved to aipaygen-mcp. Please update your config: uvx aipaygen-mcp\n")
    from aipaygen_mcp.bridge import main as run
    return run()


if __name__ == "__main__":
    main()
