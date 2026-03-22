cmake_minimum_required(VERSION 3.18)
project(quant_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# Optimization flags
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG -march=native")

# ── pybind11 ──────────────────────────────────────────────────────────────
find_package(pybind11 CONFIG QUIET)
if(NOT pybind11_FOUND)
    # Fallback: fetch pybind11 from GitHub
    include(FetchContent)
    FetchContent_Declare(
        pybind11
        GIT_REPOSITORY https://github.com/pybind/pybind11.git
        GIT_TAG        v2.13.6
    )
    FetchContent_MakeAvailable(pybind11)
endif()

# ── Source files ──────────────────────────────────────────────────────────
set(SOURCES
    src/order_book.cpp
    src/feature_engine.cpp
    src/matching_engine.cpp
)

set(HEADERS
    include/quant_cpp/order_book.h
    include/quant_cpp/feature_engine.h
    include/quant_cpp/matching_engine.h
)

# ── Static library (for C++ tests) ───────────────────────────────────────
add_library(quant_cpp_lib STATIC ${SOURCES})
target_include_directories(quant_cpp_lib PUBLIC include)

# ── Python module (pybind11) ──────────────────────────────────────────────
pybind11_add_module(quant_cpp bindings/bindings.cpp ${SOURCES})
target_include_directories(quant_cpp PRIVATE include)

# ── C++ tests (Catch2-style, but we use a minimal approach) ───────────────
enable_testing()

add_executable(test_order_book tests/test_order_book.cpp)
target_link_libraries(test_order_book PRIVATE quant_cpp_lib)
add_test(NAME test_order_book COMMAND test_order_book)

add_executable(test_feature_engine tests/test_feature_engine.cpp)
target_link_libraries(test_feature_engine PRIVATE quant_cpp_lib)
add_test(NAME test_feature_engine COMMAND test_feature_engine)

add_executable(test_matching_engine tests/test_matching_engine.cpp)
target_link_libraries(test_matching_engine PRIVATE quant_cpp_lib)
add_test(NAME test_matching_engine COMMAND test_matching_engine)
