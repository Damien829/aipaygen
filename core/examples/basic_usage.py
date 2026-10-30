"""
Example: Using aipaygen-mcp tools programmatically.

This shows how the tool functions work under the hood.
For normal usage, just install the package and connect via your MCP client.
"""

import os
from aipaygen_mcp.server import research, get_weather, web_search

# Optionally set an API key for authenticated access
# os.environ["AIPAYGEN_API_KEY"] = "apk_your_key_here"

# Research a topic
result = research("What is the Model Context Protocol?")
print("Research result:", result)

# Get weather (free tier, no key needed)
weather = get_weather("London")
print("Weather:", weather)

# Web search
results = web_search("MCP servers for Claude", n_results=5)
print("Search results:", results)
