from setuptools import setup, find_packages

setup(
    name="aipaygen-agent",
    version="0.1.0",
    description="CLI agent that pays for AiPayGen API calls via x402",
    packages=find_packages(),
    install_requires=["x402>=2.0", "eth-account>=0.10", "requests>=2.28"],
    entry_points={"console_scripts": ["aipaygen-agent=aipaygen_agent.cli:main"]},
    python_requires=">=3.10",
)
