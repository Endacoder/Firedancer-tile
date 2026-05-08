from setuptools import setup, find_packages

setup(
    name="fdmon",
    version="1.0.0",
    description="Firedancer Tile Monitor — real-time tile health dashboard for Solana validators",
    author="Sunghyun",
    python_requires=">=3.8",
    packages=find_packages(),
    install_requires=[
        "rich>=13.7.0",
        "click>=8.1.0",
        "requests>=2.31.0",
        "pyyaml>=6.0.1",
    ],
    entry_points={
        "console_scripts": [
            "fdmon=fdmon.cli:cli",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Monitoring",
    ],
)
