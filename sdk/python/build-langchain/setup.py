from setuptools import setup

with open("aipaygent_langchain.py") as f:
    content = f.read()
long_desc = content.split('"""')[1].strip()

setup(
    name="aipaygent-langchain",
    version="1.0.0",
    description="LangChain toolkit for AiPayGent — 123 AI endpoints via x402 micropayments (USDC on Base)",
    long_description=long_desc,
    long_description_content_type="text/x-rst",
    author="AiPayGent",
    author_email="hello@aipaygent.xyz",
    url="https://api.aipaygent.xyz",
    py_modules=["aipaygent_langchain"],
    install_requires=[
        "langchain-core>=0.1.0",
        "requests>=2.28.0",
    ],
    extras_require={"dev": ["langchain>=0.1.0"]},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires=">=3.9",
    keywords="langchain ai agent x402 claude anthropic marketplace usdc base web3 micropayments",
    project_urls={
        "Homepage": "https://api.aipaygent.xyz",
        "OpenAPI": "https://api.aipaygent.xyz/openapi.json",
        "llms.txt": "https://api.aipaygent.xyz/llms.txt",
    },
)
