from setuptools import setup, find_packages

setup(
    name="quant_core",
    version="0.1.0",
    packages=find_packages(),
    python_requires=">=3.14",
    install_requires=[
        "confluent-kafka>=2.3.0",
        "redis>=5.0.0",
        "orjson>=3.9.0",
    ],
)
