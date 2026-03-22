#pragma once

#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>

// Minimal test macros — no external dependencies required.
static int g_test_count = 0;
static int g_test_pass = 0;
static int g_test_fail = 0;

#define ASSERT_TRUE(expr)                                                     \
    do {                                                                      \
        ++g_test_count;                                                       \
        if (!(expr)) {                                                        \
            std::cerr << "  FAIL: " << #expr << " @ " << __FILE__ << ":"     \
                      << __LINE__ << "\n";                                    \
            ++g_test_fail;                                                    \
        } else {                                                              \
            ++g_test_pass;                                                    \
        }                                                                     \
    } while (0)

#define ASSERT_FALSE(expr) ASSERT_TRUE(!(expr))

#define ASSERT_EQ(a, b) ASSERT_TRUE((a) == (b))

#define ASSERT_NEAR(a, b, tol)                                                \
    do {                                                                      \
        ++g_test_count;                                                       \
        if (std::abs((a) - (b)) > (tol)) {                                   \
            std::cerr << "  FAIL: " << #a << " ≈ " << #b                    \
                      << " (got " << (a) << " vs " << (b) << ", tol "       \
                      << (tol) << ") @ " << __FILE__ << ":" << __LINE__      \
                      << "\n";                                                \
            ++g_test_fail;                                                    \
        } else {                                                              \
            ++g_test_pass;                                                    \
        }                                                                     \
    } while (0)

#define RUN_TEST(fn)                                                          \
    do {                                                                      \
        std::cout << "  " << #fn << "... ";                                  \
        fn();                                                                 \
        std::cout << "ok\n";                                                 \
    } while (0)

#define TEST_SUMMARY()                                                        \
    do {                                                                      \
        std::cout << "\n" << g_test_pass << "/" << g_test_count               \
                  << " assertions passed";                                    \
        if (g_test_fail > 0) {                                               \
            std::cout << " (" << g_test_fail << " FAILED)";                  \
        }                                                                     \
        std::cout << "\n";                                                   \
        return g_test_fail > 0 ? 1 : 0;                                     \
    } while (0)
