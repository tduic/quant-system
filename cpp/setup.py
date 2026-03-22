"""Build script for the quant_cpp pybind11 module.

Usage:
    pip install ./cpp/           # install into current env
    pip install -e ./cpp/        # editable/dev install
    cd cpp && python setup.py build_ext --inplace  # build .so in place
"""

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

ext_modules = [
    Pybind11Extension(
        "quant_cpp",
        sources=[
            "bindings/bindings.cpp",
            "src/order_book.cpp",
            "src/feature_engine.cpp",
            "src/matching_engine.cpp",
        ],
        include_dirs=["include"],
        cxx_std=20,
        extra_compile_args=["-O3", "-march=native"],
    ),
]

setup(
    name="quant_cpp",
    version="0.1.0",
    description="C++ performance-critical components for the quant trading system",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    python_requires=">=3.12",
    install_requires=["pybind11>=2.13"],
)
