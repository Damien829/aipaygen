from setuptools import setup

with open("aipaygen_llamaindex.py") as f:
    content = f.read()
long_desc = content.split('"""')[1].strip()

setup(
    name="aipaygen-llamaindex",
    version="1.0.1",
    description="LlamaIndex ToolSpec for AiPayGen — 123 AI endpoints via x402 micropayments (USDC on Base)",
    long_description=long_desc,
    long_description_content_type="text/x-rst",
    author="AiPayGen",
    author_email="hello@aipaygen.com",
    url="https://api.aipaygen.com",
    py_modules=["aipaygen_llamaindex"],
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
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    python_requires=">=3.9",
    keywords="llamaindex llama-index ai agent x402 claude anthropic marketplace micropayments",
    project_urls={
        "Homepage": "https://api.aipaygen.com",
        "OpenAPI": "https://api.aipaygen.com/openapi.json",
    },
)
