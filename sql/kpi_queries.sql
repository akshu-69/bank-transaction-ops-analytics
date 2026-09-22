-- ============================================================================
-- KPI queries for the bank transaction operations dataset.
-- Each query answers a real ops-reporting question and is written to be
-- dropped into a BI semantic layer (Power BI / dbt model) as-is.
-- SLA definition: a transaction breaches SLA when processing_time_mins > 15.
-- ============================================================================

-- Q1. Exception rate by channel over time (weekly trend for the ops dashboard).
WITH weekly AS (
    SELECT
        date_trunc('week', txn_date)::date          AS week_start,
        channel,
        COUNT(*)                                    AS total_txns,
        COUNT(*) FILTER (WHERE status = 'exception') AS exceptions
    FROM transactions
    GROUP BY 1, 2
)
SELECT
    week_start,
    channel,
    total_txns,
    exceptions,
    ROUND(exceptions * 100.0 / NULLIF(total_txns, 0), 2) AS exception_rate_pct
FROM weekly
ORDER BY week_start, channel;

-- Q2. Daily volume vs. 7-day rolling exception rate (spike detection).
WITH daily AS (
    SELECT
        txn_date,
        COUNT(*)                                        AS volume,
        COUNT(*) FILTER (WHERE status = 'exception')    AS exceptions
    FROM transactions
    GROUP BY 1
)
SELECT
    txn_date,
    volume,
    ROUND(exceptions * 100.0 / volume, 2)                                  AS exception_rate_pct,
    ROUND(AVG(exceptions * 100.0 / volume) OVER
          (ORDER BY txn_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2)  AS rolling_7d_rate_pct,
    CASE
        WHEN exceptions * 100.0 / volume >
             2 * AVG(exceptions * 100.0 / volume) OVER
                 (ORDER BY txn_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
        THEN 'SPIKE'
        ELSE 'normal'
    END                                                                     AS spike_flag
FROM daily
ORDER BY txn_date;

-- Q3. SLA breach rate by transaction type and channel (where is ops missing SLA?).
SELECT
    transaction_type,
    channel,
    COUNT(*) AS total_txns,
    ROUND(COUNT(*) FILTER (WHERE processing_time_mins > 15) * 100.0
          / COUNT(*), 2) AS sla_breach_rate_pct,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY processing_time_mins), 1)
        AS median_processing_mins
FROM transactions
GROUP BY 1, 2
ORDER BY sla_breach_rate_pct DESC;

-- Q4. Average processing time by status, benchmarked against "processed".
SELECT
    status,
    COUNT(*) AS txns,
    ROUND(AVG(processing_time_mins), 1) AS avg_processing_mins,
    ROUND(AVG(processing_time_mins) /
          AVG(AVG(processing_time_mins)) OVER (), 2) AS vs_overall_avg
FROM transactions
GROUP BY 1
ORDER BY avg_processing_mins DESC;

-- Q5. Exception reason breakdown: which failure modes dominate?
SELECT
    exception_reason,
    COUNT(*) AS exceptions,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS share_of_exceptions_pct,
    ROUND(AVG(amount), 2)                             AS avg_amount
FROM transactions
WHERE status = 'exception'
GROUP BY 1
ORDER BY exceptions DESC;

-- Q6. Duplicate transaction detection (same transaction_id submitted > once).
SELECT
    transaction_id,
    COUNT(*)                        AS occurrences,
    STRING_AGG(DISTINCT status, ', ') AS statuses_seen,
    ROUND(SUM(amount), 2)           AS total_amount_at_risk
FROM transactions
GROUP BY 1
HAVING COUNT(*) > 1
ORDER BY occurrences DESC, total_amount_at_risk DESC
LIMIT 100;

-- Q7. Region x transaction-type exception matrix (find the worst cell).
SELECT
    region,
    transaction_type,
    COUNT(*) AS total_txns,
    ROUND(COUNT(*) FILTER (WHERE status = 'exception') * 100.0
          / COUNT(*), 2) AS exception_rate_pct,
    RANK() OVER (PARTITION BY region ORDER BY
        COUNT(*) FILTER (WHERE status = 'exception') * 100.0 / COUNT(*) DESC)
        AS worst_type_rank_in_region
FROM transactions
WHERE region IS NOT NULL
GROUP BY 1, 2
ORDER BY exception_rate_pct DESC;

-- Q8. Source-to-report reconciliation: do grouped totals tie to the raw table?
--     (Compare with: SELECT COUNT(*), SUM(amount) FROM transactions;)
WITH report_totals AS (
    SELECT
        txn_date,
        channel,
        COUNT(*)    AS rpt_rows,
        SUM(amount) AS rpt_amount
    FROM transactions
    GROUP BY 1, 2
)
SELECT
    (SELECT COUNT(*)      FROM transactions) AS source_rows,
    (SELECT ROUND(SUM(amount), 2) FROM transactions) AS source_amount,
    SUM(rpt_rows)  AS report_rows,
    ROUND(SUM(rpt_amount), 2) AS report_amount,
    CASE
        WHEN (SELECT COUNT(*) FROM transactions) = SUM(rpt_rows)
         AND (SELECT SUM(amount) FROM transactions) = SUM(rpt_amount)
        THEN 'RECONCILED'
        ELSE 'MISMATCH'
    END AS reconciliation_status
FROM report_totals;

-- Q9. Data-quality audit: nulls, negative amounts, future-dated rows.
SELECT 'region'            AS check_name, COUNT(*) FILTER (WHERE region IS NULL)            AS bad_rows FROM transactions
UNION ALL
SELECT 'exception_reason_for_exception', COUNT(*) FILTER (WHERE status = 'exception' AND exception_reason IS NULL) FROM transactions
UNION ALL
SELECT 'non_positive_amount', COUNT(*) FILTER (WHERE amount <= 0) FROM transactions
UNION ALL
SELECT 'negative_processing_time', COUNT(*) FILTER (WHERE processing_time_mins < 0) FROM transactions
ORDER BY bad_rows DESC;

-- Q10. Week-over-week volume change by channel (capacity-planning signal).
WITH weekly AS (
    SELECT
        date_trunc('week', txn_date)::date AS week_start,
        channel,
        COUNT(*) AS volume
    FROM transactions
    GROUP BY 1, 2
)
SELECT
    week_start,
    channel,
    volume,
    LAG(volume) OVER (PARTITION BY channel ORDER BY week_start) AS prior_week_volume,
    ROUND((volume - LAG(volume) OVER (PARTITION BY channel ORDER BY week_start))
          * 100.0 / NULLIF(LAG(volume) OVER (PARTITION BY channel ORDER BY week_start), 0), 1)
        AS wow_change_pct
FROM weekly
ORDER BY week_start, channel;
