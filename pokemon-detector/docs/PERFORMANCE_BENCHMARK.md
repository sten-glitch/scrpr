# Measured performance — 2026-10-15

Reproduce: `.venv\Scripts\python.exe benchmark_graded_logic.py`.
Synthetic Python microbenchmarks with tracemalloc enabled, warmed functions:

| Workload | Median | p95 | Peak Python allocations |
|---|---:|---:|---:|
| Parse one explicit certificate text, 1,000 iterations | 0.0492 ms | 0.0887 ms | 53,274 bytes |
| Group 300 observations / 100 certificates, 100 iterations | 26.9306 ms | 34.6631 ms | 715,784 bytes |

No baseline certificate parser/deduplicator existed, so these are initial
measurements, not a measured speedup. tracemalloc is not native process/GPU memory.
300 synthetic listings yielded expected 100 groups / 200 duplicates. This does
not establish real duplicate precision or false-merge rates.

Baseline suite: 265 tests / 12.871 s. New complete suite: 342 tests / 10.090 s,
339 passed / 3 Windows symlink skips. Suite timings are not an optimization claim.
Windows connection-aborts on invalid-origin tests revealed unread request bodies
being closed before the client received 403. Rejected requests now discard at most
64 KiB with a 0.5-second timeout, without parsing. Full suite passed after this fix;
security assertions were not relaxed.

Additional system-Python 3.14 run: 335 tests / 4.295 s, 290 passed / 45 skipped
because optional image dependencies are missing. Its first run exposed a package
name collision and an incomplete optional-dependency test guard; both corrected.
The supported full local test environment remains `.venv` Python 3.13.

Real OCR accuracy, image latency, local-resolution rate, escalation rate and cost
per 1,000 listings: unmeasured, blocked by missing OCR executable, labeled dataset
and marketplace credentials. No estimate is substituted for evidence.
