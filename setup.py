"""
Setup script for Dogeey
"""
from setuptools import setup, find_packages

setup(
    name="dogeey",
    version="1.0.0",
    description="轻量级AI智能体 - 越用越聪明",
    packages=find_packages(),
    install_requires=[
        "click>=8.0.0",
        "openai>=1.0.0",
        "pydantic>=2.0.0",
        "python-dotenv>=1.0.0",
    ],
    extras_require={
        "web": [
            "fastapi>=0.100.0",
            "uvicorn>=0.20.0",
            "websockets>=12.0",
        ],
        "full": [
            "fastapi>=0.100.0",
            "uvicorn>=0.20.0",
            "websockets>=12.0",
            "aiosqlite>=0.19.0",
            "rich>=13.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "dogeey=dogeey.cli:cli",
        ]
    },
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
