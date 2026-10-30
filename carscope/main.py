#!/usr/bin/env python3
"""Entry point: `python main.py <command>`.

You can also run it as a module: `python -m carscope.cli <command>`.
"""

from carscope.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
