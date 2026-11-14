"""
Example: Pointing aipaygen-mcp at a self-hosted backend.

Set AIPAYGEN_BASE_URL to your own server before importing.
"""

import os

# Point at your own backend
os.environ["AIPAYGEN_BASE_URL"] = "http://localhost:5001"

from aipaygen_mcp.server import research

result = research("test query")
print(result)
