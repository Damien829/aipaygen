"""PyPI package setup for aipaygen-langchain."""
from setuptools import setup, find_packages
import os

# Read the langchain_tool.py from the parent directory
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

setup(
    name="aipaygen-langchain",
    version="1.0.0",
    description="LangChain tool for AiPayGen — AI agent marketplace with 123 endpoints via x402",
    long_description=open(os.path.join(HERE, "langchain_tool.py")).read().split('"""')[1].strip(),
    long_description_content_type="text/x-rst",
    author="AiPayGen",
    url="https://api.aipaygen.com",
    py_modules=["aipaygen_langchain"],
    package_data={"": ["langchain_tool.py"]},
    install_requires=[
        "langchain-core>=0.1.0",
        "requests>=2.28.0",
    ],
    extras_require={
        "dev": ["langchain>=0.1.0", "langchain-openai>=0.1.0"],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Libraries",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires=">=3.8",
    keywords="langchain ai agent x402 claude anthropic marketplace usdc base web3",
    project_urls={
        "Homepage": "https://api.aipaygen.com",
        "OpenAPI": "https://api.aipaygen.com/openapi.json",
        "llms.txt": "https://api.aipaygen.com/llms.txt",
    },
)
