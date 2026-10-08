"""The analytics core: pure computation over DataFrames.

Same rule as `app/preprocessing/`: **no web framework and no ORM in here.**
Every function takes DataFrames or plain values and returns plain data, so it
can be tested in milliseconds and reused unchanged by the Phase 5 research
scripts. That is what makes the numbers in the report and the numbers in the
dashboard the same numbers.

Aggregation that PostgreSQL can do (SUM, COUNT, GROUP BY, date_trunc) happens in
`app/db/repositories/analytics.py`. What arrives here is already small.
"""
