"""AiPayGent LlamaIndex package entry point."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from llamaindex_tool import AiPayGentToolSpec  # noqa: F401

__all__ = ['AiPayGentToolSpec']
__version__ = '1.0.0'
