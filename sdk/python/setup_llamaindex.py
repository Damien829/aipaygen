"""PyPI package setup for aipaygent-llamaindex."""
from setuptools import setup

setup(
    name="aipaygent-llamaindex",
    version="1.0.0",
    description="LlamaIndex tool spec for AiPayGent — AI agent marketplace with 123 endpoints via x402",
    author="AiPayGent",
    url="https://api.aipaygent.xyz",
    py_modules=["aipaygent_llamaindex"],
    install_requires=[
        "llama-index-core>=0.10.0",
        "requests>=2.28.0",
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires=">=3.9",
    keywords="llamaindex llama-index ai agent x402 claude anthropic marketplace",
    project_urls={
        "Homepage": "https://api.aipaygent.xyz",
        "OpenAPI": "https://api.aipaygent.xyz/openapi.json",
    },
)
