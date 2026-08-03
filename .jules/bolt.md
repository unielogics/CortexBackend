# Bolt Performance Journal

## 2026-03-03 - Initial Journal Setup
**Learning:** Initiated journal to track critical learnings, patterns, and performance optimizations made in the repository.
**Action:** Always maintain and consult this journal for codebase performance patterns.

## 2026-03-03 - Spherical Law of Cosines & LRU Caching for Static Geographical Queries
**Learning:** Distance calculations against a static set of targets (e.g. state hub coordinates) can be optimized by pre-computing target coordinates/trig results in radians, and replacing expensive Haversine distance computations (which require `asin` and `sqrt`) with a simple Spherical Law of Cosines dot-product metric when finding the minimum/closest target. Adding `@functools.lru_cache` provides massive O(1) performance gains for static inputs (e.g. 1000 potential ZIP3 inputs). This yielded a ~11.5x speedup for unique cold calls (8.22ms vs 94.69ms) and a ~615x speedup for warm/cached calls.
**Action:** Use pre-computation of fixed coordinate properties and Spherical Law of Cosines to maximize cosine distance metrics instead of computing exact great-circle distance inside hot search loops. Always add `lru_cache` on pure, static lookup routines with small argument spaces.
