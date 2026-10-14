# Implementation Decisions

1. **Indexes.** I use a unique index on `emp_code` to prevent duplicate employees, and a unique compound index on `(emp_code, date)` to prevent duplicate daily attendance records. I also index `joined_on`, `(department, joined_on)`, attendance date, and `(emp_code, date)` to support employee filtering, monthly queries, department headcounts, and employee attendance lookups. I considered adding more indexes for every analytics pipeline, but extra indexes increase write and storage costs, so I kept indexes tied to common filters and guarantees.

2. **Punch-in race.** Both requests may initially find no attendance record. The unique `(emp_code, date)` index allows only one insert to succeed. The other request receives a duplicate-key error, which the API handles as a conflict rather than creating a second record.

3. **Ties.** The leaderboard uses `$rank`, then sorts by rank and employee code. It applies `$limit` after ranking, so employees tied at the cutoff may not all be returned. Employee-code ordering makes the selected results deterministic.

4. **Headcount.** The department summary starts from employees who joined on or before the end of the month. It preserves employees without matching attendance logs during the lookup, so they remain part of headcount.

5. **Scaling.** For 100 times more data, I would benchmark the aggregation pipelines with a representative large dataset, inspect execution plans, and measure latency and memory use. I would then tune indexes and consider pre-aggregating frequently requested analytics if measurements showed that live aggregation was too expensive.
