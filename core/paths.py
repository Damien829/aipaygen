"""Where AiPayGen keeps its SQLite databases.

AIPAYGEN_DATA_DIR points at a data volume in production and at a throwaway
directory in tests (tests/conftest.py), so tests can never touch live data.
Unset, it falls back to this folder, which is where v1 kept everything.
"""
import os

DATA_DIR = os.path.abspath(os.getenv("AIPAYGEN_DATA_DIR") or os.path.dirname(__file__))
os.makedirs(DATA_DIR, exist_ok=True)
