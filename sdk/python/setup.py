from setuptools import setup, find_packages

setup(
    name="saferun",
    version="0.1.0",
    description="Python SDK for SafeRun API",
    packages=find_packages(include=["saferun", "saferun.*"]),
    install_requires=[
        "requests>=2.31.0",
    ],
    extras_require={
        "dev": ["pytest", "requests-mock", "mypy"],
    },
    python_requires=">=3.9",
    include_package_data=True,
)
