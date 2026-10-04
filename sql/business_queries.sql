-- ============================================================================
-- Business queries v2 - SACCO Loan Delinquency & Collections Performance
-- Analytics. All results are SIMULATED - not United Winners DT Sacco's
-- actual portfolio.
--
-- Two distinct metric families are used throughout, and never conflated:
--   Loan Delinquency Rate = COUNT(loans with days_past_due>=30) / COUNT(active loans)
--     -> an OPERATIONAL measure: how many accounts/members need attention
--   PARxx = SUM(balance of loans with parXX_flag=1) / SUM(all outstanding balance)
--     -> a FINANCIAL EXPOSURE measure: how much money is actually at risk
-- A CEO needs both: a book can have many small delinquent loans (high rate,
-- low PAR) or a few large ones (low rate, high PAR) - very different
-- provisioning, liquidity and staffing implications.
-- ============================================================================

-- Q1: product-level delinquency, BOTH measures, using the most recent
-- snapshot date so "active loans" means loans on the book that month
WITH latest AS (SELECT MAX(snapshot_date) d FROM Loan_Performance_Snapshot)
SELECT
    lp.product_name, lp.category, lp.rate_source_note,
    COUNT(*)                                                                AS active_loans,
    ROUND(SUM(s.par30_flag) * 100.0 / COUNT(*), 1)                          AS loan_delinquency_rate_pct,
    ROUND(SUM(CASE WHEN s.par30_flag=1 THEN s.outstanding_balance_ksh ELSE 0 END)
          * 100.0 / SUM(s.outstanding_balance_ksh), 1)                      AS par30_pct
FROM Loan_Performance_Snapshot s
JOIN Loans l ON l.loan_id = s.loan_id
JOIN Loan_Products lp ON lp.product_id = l.product_id
WHERE s.snapshot_date = (SELECT d FROM latest)
GROUP BY lp.product_name, lp.category, lp.rate_source_note
ORDER BY par30_pct DESC;

-- Q2: segment-level delinquency, BOTH measures (H1's test)
WITH latest AS (SELECT MAX(snapshot_date) d FROM Loan_Performance_Snapshot)
SELECT
    m.member_segment,
    COUNT(*)                                                                AS active_loans,
    ROUND(SUM(s.par30_flag) * 100.0 / COUNT(*), 1)                          AS loan_delinquency_rate_pct,
    ROUND(SUM(CASE WHEN s.par30_flag=1 THEN s.outstanding_balance_ksh ELSE 0 END)
          * 100.0 / SUM(s.outstanding_balance_ksh), 1)                      AS par30_pct
FROM Loan_Performance_Snapshot s
JOIN Loans l ON l.loan_id = s.loan_id
JOIN Members m ON m.member_id = l.member_id
WHERE s.snapshot_date = (SELECT d FROM latest)
GROUP BY m.member_segment
ORDER BY par30_pct DESC;

-- Q4: derived arrears source - BOTH sides of the business question, still
-- fully derived from observable behaviour, never a stored label.
-- Employer/check-off side: Employer_Remittances shortfall.
-- Direct/member side: Repayments shortfall on non-check-off loans.
WITH employer_side AS (
    SELECT r.loan_id, r.due_date,
           ROUND(er.expected_deduction_ksh - er.remitted_amount_ksh, 2) AS shortfall_ksh
    FROM Repayments r
    JOIN Loans l ON l.loan_id = r.loan_id
    JOIN Employer_Remittances er ON er.loan_id = r.loan_id AND er.period = r.due_date
    WHERE l.repayment_channel = 'Check-Off'
      AND er.remitted_amount_ksh < er.expected_deduction_ksh
),
member_side AS (
    SELECT r.loan_id, r.due_date,
           ROUND(r.amount_due_ksh - r.amount_paid_ksh, 2) AS shortfall_ksh
    FROM Repayments r
    JOIN Loans l ON l.loan_id = r.loan_id
    WHERE l.repayment_channel IN ('Direct-Standing-Order', 'Cash-MobileMoney')
      AND r.payment_status IN ('Missed', 'Partial')
),
combined AS (
    SELECT 'Employer/check-off remittance shortfall' AS derived_source, loan_id, shortfall_ksh FROM employer_side
    UNION ALL
    SELECT 'Direct/member-side repayment shortfall', loan_id, shortfall_ksh FROM member_side
)
SELECT
    derived_source,
    COUNT(DISTINCT loan_id)                                              AS affected_loans,
    COUNT(*)                                                              AS affected_periods,
    ROUND(SUM(shortfall_ksh), 0)                                          AS arrears_ksh,
    ROUND(SUM(shortfall_ksh) * 100.0 / SUM(SUM(shortfall_ksh)) OVER (), 1) AS pct_of_total_arrears
FROM combined
GROUP BY derived_source;

-- Q5: vintage curves, balance-based PAR30 (the appropriate measure for
-- vintage analysis - a cohort's financial exposure as it ages, not just
-- how many of its loans happen to be delinquent)
SELECT
    strftime('%Y-%m', l.disbursement_date)                                         AS vintage_cohort,
    CAST((julianday(s.snapshot_date) - julianday(l.disbursement_date)) / 30 AS INT) AS months_on_book,
    ROUND(SUM(CASE WHEN s.par30_flag=1 THEN s.outstanding_balance_ksh ELSE 0 END)
          * 100.0 / SUM(s.outstanding_balance_ksh), 1)                              AS par30_pct,
    COUNT(*)                                                                        AS loans_in_cohort_month
FROM Loans l
JOIN Loan_Performance_Snapshot s ON s.loan_id = l.loan_id
GROUP BY vintage_cohort, months_on_book
HAVING COUNT(*) >= 5
ORDER BY vintage_cohort, months_on_book;

-- Q7a: Recovery Rate - denominator is now a FLOW measure ("amount referred
-- into the case"), not a point-in-time balance: the sum of every shortfall
-- that ever arose on this loan's single delinquency episode, through the
-- 6-month window close. No double counting - each Repayments row
-- contributes its shortfall exactly once, and this simulation gives each
-- loan at most one episode, so every shortfall row belongs unambiguously to
-- this loan's one case. A recovery event's amount, by the FIFO design in
-- the generator, can never exceed the shortfalls accrued so far - so the
-- rate is bounded at <=100% by construction, not by hoping the numbers
-- happen to work out, and the QC report checks this per loan, not just in
-- aggregate.
WITH case_open AS (
    SELECT loan_id, MIN(snapshot_date) AS case_open_date
    FROM Loan_Performance_Snapshot WHERE par30_flag = 1
    GROUP BY loan_id
),
case_window AS (
    SELECT loan_id, case_open_date, date(case_open_date, '+6 months') AS case_close_date
    FROM case_open
),
referred AS (
    SELECT cw.loan_id, cw.case_close_date,
           SUM(r.amount_due_ksh - r.amount_paid_ksh) AS referred_amount_ksh
    FROM case_window cw
    JOIN Repayments r ON r.loan_id = cw.loan_id
    WHERE r.due_date <= cw.case_close_date AND r.amount_paid_ksh < r.amount_due_ksh
    GROUP BY cw.loan_id, cw.case_close_date
),
recovered_in_window AS (
    SELECT rf.loan_id, SUM(rt.amount_recovered_ksh) AS recovered_ksh
    FROM referred rf
    LEFT JOIN Recovery_Transactions rt
      ON rt.loan_id = rf.loan_id AND rt.recovery_date <= rf.case_close_date
    GROUP BY rf.loan_id
)
SELECT
    COUNT(*)                                                                       AS collection_cases,
    ROUND(SUM(rf.referred_amount_ksh), 0)                                          AS total_referred_ksh,
    ROUND(SUM(COALESCE(riw.recovered_ksh, 0)), 0)                                  AS total_recovered_ksh,
    ROUND(SUM(COALESCE(riw.recovered_ksh, 0)) * 100.0 / SUM(rf.referred_amount_ksh), 1) AS recovery_rate_pct
FROM referred rf
LEFT JOIN recovered_in_window riw ON riw.loan_id = rf.loan_id;

-- Q7b: Recovery per Contact and Contact-to-Payment Conversion, by channel -
-- unchanged definitions, re-run against the corrected data
SELECT
    ca.channel,
    COUNT(*)                                                                AS total_contacts,
    ROUND(SUM(CASE WHEN ca.outcome = 'Payment Received' THEN 1 ELSE 0 END) * 100.0
          / COUNT(*), 1)                                                    AS contact_to_payment_conversion_pct,
    ROUND(COALESCE(SUM(rt.amount_recovered_ksh), 0) * 1.0 / COUNT(*), 0)     AS recovery_per_contact_ksh
FROM Collections_Activity ca
LEFT JOIN Recovery_Transactions rt ON rt.related_activity_id = ca.activity_id
GROUP BY ca.channel
ORDER BY recovery_per_contact_ksh DESC;

-- Q8 (secondary): recovery source split
SELECT recovery_source, COUNT(*) AS transactions,
       ROUND(SUM(amount_recovered_ksh), 0) AS total_recovered_ksh,
       ROUND(SUM(amount_recovered_ksh) * 100.0 / (SELECT SUM(amount_recovered_ksh) FROM Recovery_Transactions), 1) AS pct_of_recovery
FROM Recovery_Transactions GROUP BY recovery_source ORDER BY total_recovered_ksh DESC;

-- Q10: descriptive/correlational only. Two comparisons, clearly labelled:
-- (1) a matched comparison - members whose loans never went delinquent,
--     sampled in the SAME calendar months the treatment group's pre-onset
--     window falls in, controlling for any period-specific effect. This is
--     the primary, more defensible comparison.
-- (2) the unmatched, all-member-months baseline, kept for reference only
--     and explicitly labelled as unmatched - never call this a control
--     group.
-- Limitation, stated plainly: even (1) is not a full matched control -
-- never-delinquent members may differ systematically from the treatment
-- group in ways beyond calendar timing (product mix, segment, risk
-- profile). A stronger design would also match on those.
WITH onset AS (
    SELECT l.loan_id, l.member_id, MIN(s.snapshot_date) AS onset_month
    FROM Loans l JOIN Loan_Performance_Snapshot s ON s.loan_id = l.loan_id
    WHERE s.par30_flag = 1 GROUP BY l.loan_id, l.member_id
),
treatment AS (
    SELECT sa.contribution_status FROM onset o
    JOIN Savings_Activity sa ON sa.member_id = o.member_id
    WHERE sa.period BETWEEN date(o.onset_month, '-2 months') AND date(o.onset_month, '-1 months')
),
treatment_months AS (
    SELECT DISTINCT strftime('%Y-%m', date(onset_month, '-2 months')) AS ym FROM onset
    UNION
    SELECT DISTINCT strftime('%Y-%m', date(onset_month, '-1 months')) FROM onset
),
never_delinquent_members AS (
    SELECT DISTINCT member_id FROM Loans
    WHERE member_id NOT IN (
        SELECT DISTINCT l2.member_id FROM Loans l2
        JOIN Loan_Performance_Snapshot s2 ON s2.loan_id = l2.loan_id WHERE s2.par30_flag = 1
    )
),
matched_comparison AS (
    SELECT sa.contribution_status
    FROM Savings_Activity sa
    JOIN never_delinquent_members ndm ON ndm.member_id = sa.member_id
    WHERE strftime('%Y-%m', sa.period) IN (SELECT ym FROM treatment_months)
)
SELECT 'Treatment: pre-delinquency window (2mo before onset)' AS population,
       ROUND(SUM(CASE WHEN contribution_status != 'Met' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS pct_below_target_or_missed,
       COUNT(*) AS n
FROM treatment
UNION ALL
SELECT 'Matched comparison: never-delinquent members, same calendar months',
       ROUND(SUM(CASE WHEN contribution_status != 'Met' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1), COUNT(*)
FROM matched_comparison
UNION ALL
SELECT 'Unmatched baseline (reference only - NOT a control group): all member-months',
       ROUND(SUM(CASE WHEN contribution_status != 'Met' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1), COUNT(*)
FROM Savings_Activity;

-- Q12: rolling monthly trend, BOTH measures
SELECT
    c.year_month,
    ROUND(SUM(s.par30_flag) * 100.0 / COUNT(*), 1)                                            AS loan_delinquency_rate_pct,
    ROUND(SUM(CASE WHEN s.par30_flag=1 THEN s.outstanding_balance_ksh ELSE 0 END) * 100.0
          / SUM(s.outstanding_balance_ksh), 1)                                                 AS par30_pct,
    ROUND(SUM(CASE WHEN s.par60_flag=1 THEN s.outstanding_balance_ksh ELSE 0 END) * 100.0
          / SUM(s.outstanding_balance_ksh), 1)                                                 AS par60_pct,
    ROUND(SUM(CASE WHEN s.par90_flag=1 THEN s.outstanding_balance_ksh ELSE 0 END) * 100.0
          / SUM(s.outstanding_balance_ksh), 1)                                                 AS par90_pct
FROM Loan_Performance_Snapshot s
JOIN Calendar c ON c.date = s.snapshot_date
GROUP BY c.year_month
ORDER BY c.year_month;

-- H1 (balance version): segment risk on BOTH measures, most recent month
WITH latest AS (SELECT MAX(snapshot_date) d FROM Loan_Performance_Snapshot)
SELECT
    CASE WHEN m.member_segment IN ('SME','Corporate') THEN 'SME/Corporate' ELSE 'Other segments' END grp,
    ROUND(SUM(s.par30_flag) * 100.0 / COUNT(*), 1)                          AS loan_delinquency_rate_pct,
    ROUND(SUM(CASE WHEN s.par30_flag=1 THEN s.outstanding_balance_ksh ELSE 0 END)
          * 100.0 / SUM(s.outstanding_balance_ksh), 1)                      AS par30_pct
FROM Loan_Performance_Snapshot s JOIN Loans l ON l.loan_id=s.loan_id JOIN Members m ON m.member_id=l.member_id
WHERE s.snapshot_date = (SELECT d FROM latest) GROUP BY grp;

-- H3 (balance version): seeded weak vintage on BOTH measures.
-- NOTE: unlike Q1/Q2/H1/H5 above, this is deliberately NOT restricted to the
-- portfolio's single latest snapshot date. A vintage cohort's own loans stop
-- generating snapshots once they pass their nominal term, so a "latest
-- global month" filter would silently exclude most of an older/shorter-term
-- cohort and understate its risk. Vintage risk is tested across each
-- cohort's own full observed lifetime instead - the same aggregation the
-- vintage curve (Q5) itself uses.
SELECT
    CASE WHEN l.disbursement_date BETWEEN '2025-01-01' AND '2025-04-30' THEN 'Seeded weak vintage' ELSE 'Other' END grp,
    ROUND(SUM(s.par30_flag) * 100.0 / COUNT(*), 1)                          AS loan_delinquency_rate_pct,
    ROUND(SUM(CASE WHEN s.par30_flag=1 THEN s.outstanding_balance_ksh ELSE 0 END)
          * 100.0 / SUM(s.outstanding_balance_ksh), 1)                      AS par30_pct
FROM Loan_Performance_Snapshot s JOIN Loans l ON l.loan_id=s.loan_id
GROUP BY grp;

-- H5 (balance version): channel risk on BOTH measures
WITH latest AS (SELECT MAX(snapshot_date) d FROM Loan_Performance_Snapshot)
SELECT
    l.repayment_channel,
    ROUND(SUM(s.par30_flag) * 100.0 / COUNT(*), 1)                          AS loan_delinquency_rate_pct,
    ROUND(SUM(CASE WHEN s.par30_flag=1 THEN s.outstanding_balance_ksh ELSE 0 END)
          * 100.0 / SUM(s.outstanding_balance_ksh), 1)                      AS par30_pct
FROM Loan_Performance_Snapshot s JOIN Loans l ON l.loan_id=s.loan_id
WHERE s.snapshot_date = (SELECT d FROM latest) GROUP BY l.repayment_channel;
