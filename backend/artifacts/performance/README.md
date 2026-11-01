# API latency measurements

Produced by `backend/scripts/measure_latency.py` against the Online Retail II
dataset (1,021,349 sales lines), on Docker Desktop for Windows with
PostgreSQL 16 in a container.

Target: Assessment 1 Table 10, "interactive response under 3 seconds",
restated as a p95 in the architecture document (TO3). Measured as the warm
round trip from request to the last byte of the response body, discarding one
warm-up call per endpoint.

| run | Postgres settings | repeats | endpoints over target |
|---|---|---|---|
| 20261031T044503Z | stock: work_mem 4MB, shared_buffers 128MB | 10 | kpis, trends, products, customers |
| 20261101T021238Z | stock | 10 | filter-options, kpis, trends, products, customers |
| 20261101T021922Z | stock | 30 | filter-options, trends, products, customers |
| 20261101T023616Z | work_mem 64MB | 30 | kpis, trends, products, customers |

## What holds across every run

`trends`, `products` and `customers` exceed the target in all four runs.
`kpis` exceeds it in three, `filter-options` in two — both sit close enough to
the boundary to flip. The ten endpoints served from the `analysis_results`
cache stay under 0.2s at p95 in all four runs, two orders of magnitude clear.

The endpoints that fail are exactly the ones that bypass the cache and
aggregate the sales table on every request. The determinant is architectural,
not configuration.

## The tuning experiment, and its null result

`EXPLAIN (ANALYZE, BUFFERS)` on the KPI aggregation showed a disk spill:
`temp read=1168 written=1172`, roughly 9.4 MB, from `count(DISTINCT ...)`
exceeding the default 4MB `work_mem`. Raising it to 64MB removed the spill and
produced no improvement in response time.

Forcing a sequential scan was also tested and was substantially worse
(13.3s against 5.1s): the planner's index scan avoids a sort that a sequential
scan must perform and spill, so the plan it chose was correct.

The median for `products` ranges from 3.0s to 7.7s across runs of identical
work on identical data. Between-run variance on this platform exceeds the
effect under test, so a change of this magnitude is not measurable here. The
setting was reset to stock after measurement.

## Limitation

Measured on a laptop under Docker Desktop for Windows, where disk I/O passes
through a virtual machine. Absolute figures are not representative of a
deployed Linux host. The relative difference between cached and uncached
endpoints is large enough to survive that caveat; the marginal cases are not.