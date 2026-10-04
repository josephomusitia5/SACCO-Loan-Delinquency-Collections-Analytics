"""
Quality-control report for sacco_analytics.db.
Run after any regeneration, before proceeding to Power BI.
Every check should read 0 / PASS. A non-zero count is a real defect, not
a rounding artifact - rounding tolerance is applied explicitly where noted.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "sacco_analytics.db"
TOL = 1.0  # Ksh rounding tolerance for balance reconciliation

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()


def check(label, query, expect_zero=True):
    cur.execute(query)
    val = cur.fetchone()[0]
    val = 0 if val is None else val
    status = "PASS" if (val == 0 if expect_zero else val) else "FAIL"
    print(f"[{status}] {label}: {val}")
    return status == "PASS"


print("=" * 78)
print("ROW COUNTS")
print("=" * 78)
for t in ["Members", "Branches", "Loan_Products", "Loans", "Repayments",
          "Employer_Remittances", "Savings_Activity", "Collections_Officers",
          "Collections_Activity", "Loan_Guarantees", "Loan_Performance_Snapshot",
          "Recovery_Transactions", "Calendar"]:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"  {t}: {cur.fetchone()[0]}")

print()
print("=" * 78)
print("FOREIGN-KEY / ORPHAN CHECKS")
print("=" * 78)
all_pass = True
all_pass &= check("orphaned Loans.member_id", "SELECT COUNT(*) FROM Loans WHERE member_id NOT IN (SELECT member_id FROM Members)")
all_pass &= check("orphaned Loans.product_id", "SELECT COUNT(*) FROM Loans WHERE product_id NOT IN (SELECT product_id FROM Loan_Products)")
all_pass &= check("orphaned Repayments.loan_id", "SELECT COUNT(*) FROM Repayments WHERE loan_id NOT IN (SELECT loan_id FROM Loans)")
all_pass &= check("orphaned Employer_Remittances.loan_id", "SELECT COUNT(*) FROM Employer_Remittances WHERE loan_id NOT IN (SELECT loan_id FROM Loans)")
all_pass &= check("orphaned Collections_Activity.loan_id", "SELECT COUNT(*) FROM Collections_Activity WHERE loan_id NOT IN (SELECT loan_id FROM Loans)")
all_pass &= check("orphaned Loan_Guarantees.loan_id", "SELECT COUNT(*) FROM Loan_Guarantees WHERE loan_id NOT IN (SELECT loan_id FROM Loans)")
all_pass &= check("orphaned Loan_Performance_Snapshot.loan_id", "SELECT COUNT(*) FROM Loan_Performance_Snapshot WHERE loan_id NOT IN (SELECT loan_id FROM Loans)")
all_pass &= check("orphaned Recovery_Transactions.loan_id", "SELECT COUNT(*) FROM Recovery_Transactions WHERE loan_id NOT IN (SELECT loan_id FROM Loans)")
all_pass &= check("orphaned Recovery_Transactions.related_activity_id",
                   "SELECT COUNT(*) FROM Recovery_Transactions WHERE related_activity_id IS NOT NULL "
                   "AND related_activity_id NOT IN (SELECT activity_id FROM Collections_Activity)")

print()
print("=" * 78)
print("DUPLICATE / PRIMARY-KEY CHECKS")
print("=" * 78)
all_pass &= check("duplicate Loan_Performance_Snapshot (loan_id,snapshot_date)",
                   "SELECT COUNT(*) - COUNT(DISTINCT loan_id||'|'||snapshot_date) FROM Loan_Performance_Snapshot")
all_pass &= check("duplicate Savings_Activity (member_id,period)",
                   "SELECT COUNT(*) - COUNT(DISTINCT member_id||'|'||period) FROM Savings_Activity")
all_pass &= check("Recovery_Transactions.related_activity_id reused across >1 recovery (point 6)",
                   "SELECT COUNT(*) FROM (SELECT related_activity_id FROM Recovery_Transactions "
                   "WHERE related_activity_id IS NOT NULL GROUP BY related_activity_id HAVING COUNT(*) > 1)")

print()
print("=" * 78)
print("BALANCE / RECOVERY CONSISTENCY (point 3)")
print("=" * 78)
cur.execute(f"""
    SELECT COUNT(*) FROM (
      SELECT l.loan_id,
             l.principal_amount_ksh
               - COALESCE((SELECT SUM(amount_paid_ksh) FROM Repayments r WHERE r.loan_id = l.loan_id), 0)
               - COALESCE((SELECT SUM(amount_recovered_ksh) FROM Recovery_Transactions rt WHERE rt.loan_id = l.loan_id), 0)
             AS expected_balance,
             l.outstanding_balance_ksh AS recorded_balance
      FROM Loans l
    ) WHERE ABS(expected_balance - recorded_balance) > {TOL} AND expected_balance > {TOL}
      -- expected_balance can go slightly negative pre-floor; recorded is floored at 0, so only
      -- flag real mismatches where expected balance is still meaningfully positive
""")
mismatch = cur.fetchone()[0]
print(f"[{'PASS' if mismatch == 0 else 'FAIL'}] loans where principal - repayments - recoveries != recorded outstanding_balance_ksh: {mismatch}")
all_pass &= (mismatch == 0)

all_pass &= check("negative outstanding_balance_ksh on Loans", "SELECT COUNT(*) FROM Loans WHERE outstanding_balance_ksh < 0")
all_pass &= check("negative outstanding_balance_ksh on snapshots", "SELECT COUNT(*) FROM Loan_Performance_Snapshot WHERE outstanding_balance_ksh < 0")

print()
print("=" * 78)
print("REPAYMENT TOTAL CONSISTENCY")
print("=" * 78)
all_pass &= check("Repayments rows with amount_paid_ksh > amount_due_ksh (overpaid instalment)",
                   "SELECT COUNT(*) FROM Repayments WHERE amount_paid_ksh > amount_due_ksh + 0.01")
all_pass &= check("Repayments 'Paid-OnTime'/'Paid-Late' rows with payment_date NULL (should be 0 - only 'Missed' rows are null by design)",
                   "SELECT COUNT(*) FROM Repayments WHERE payment_status IN ('Paid-OnTime','Paid-Late') AND payment_date IS NULL")
all_pass &= check("Repayments 'Missed' rows with a non-null payment_date (should be 0)",
                   "SELECT COUNT(*) FROM Repayments WHERE payment_status = 'Missed' AND payment_date IS NOT NULL")

print()
print("=" * 78)
print("SNAPSHOT / SCHEDULE CONSISTENCY (point 2)")
print("=" * 78)
# for every loan with days_past_due > 0 at its LATEST snapshot, the DPD must equal
# (latest snapshot_date - oldest Repayments.due_date with a still-net-outstanding shortfall
#  after FIFO recovery application). We recompute this independently here, in SQL/Python,
# as a genuine cross-check rather than re-trusting the generator's own arithmetic.
cur.execute("""
    SELECT loan_id, MAX(snapshot_date) FROM Loan_Performance_Snapshot GROUP BY loan_id
""")
latest_snap = dict(cur.fetchall())
mismatches = 0
for loan_id, snap_date in latest_snap.items():
    cur.execute("SELECT days_past_due, amount_overdue_ksh FROM Loan_Performance_Snapshot WHERE loan_id=? AND snapshot_date=?",
                (loan_id, snap_date))
    recorded_dpd, recorded_overdue = cur.fetchone()
    cur.execute("SELECT due_date, amount_due_ksh, amount_paid_ksh FROM Repayments WHERE loan_id=? ORDER BY due_date", (loan_id,))
    installments = cur.fetchall()
    cur.execute("SELECT recovery_date, amount_recovered_ksh FROM Recovery_Transactions WHERE loan_id=? ORDER BY recovery_date", (loan_id,))
    recs = cur.fetchall()
    total_recovered = sum(r[1] for r in recs)
    queue = []
    for due_d, due_amt, paid_amt in installments:
        sf = round(due_amt - paid_amt, 2)
        if sf > 0.01:
            queue.append([due_d, sf])
    remaining = total_recovered
    net_queue = []
    for d_, s_ in queue:
        applied = min(remaining, s_)
        net = round(s_ - applied, 2)
        remaining = round(remaining - applied, 2)
        if net > 0.01:
            net_queue.append((d_, net))
    if net_queue:
        from datetime import date as _date
        y, m, d_ = map(int, snap_date.split("-"))
        y2, m2, d2 = map(int, net_queue[0][0].split("-"))
        recomputed_dpd = (_date(y, m, d_) - _date(y2, m2, d2)).days
        recomputed_overdue = round(sum(s for _, s in net_queue), 2)
    else:
        recomputed_dpd, recomputed_overdue = 0, 0.0
    if recomputed_dpd != recorded_dpd or abs(recomputed_overdue - recorded_overdue) > TOL:
        mismatches += 1
print(f"[{'PASS' if mismatches == 0 else 'FAIL'}] loans where independently-recomputed DPD/overdue "
      f"(from Repayments+Recovery_Transactions) disagrees with the stored latest snapshot: {mismatches} / {len(latest_snap)}")
all_pass &= (mismatches == 0)

print()
print("=" * 78)
print("SNAPSHOT COMPLETENESS (point 1 - the 650-vs-616 gap)")
print("=" * 78)
cur.execute("SELECT COUNT(*) FROM Loans")
total_loans = cur.fetchone()[0]
cur.execute("SELECT COUNT(DISTINCT loan_id) FROM Loan_Performance_Snapshot")
loans_with_snapshot = cur.fetchone()[0]
print(f"[{'PASS' if loans_with_snapshot == total_loans else 'FAIL'}] "
      f"loans with at least one snapshot: {loans_with_snapshot} / {total_loans}")
all_pass &= (loans_with_snapshot == total_loans)

# every loan's snapshot COUNT should equal its own on-book month count
# (disbursement month + every month_i through min(term_months, months to OBS_END))
cur.execute("""
    SELECT l.loan_id, l.disbursement_date, l.term_months, COUNT(s.snapshot_date) AS n_snaps
    FROM Loans l LEFT JOIN Loan_Performance_Snapshot s ON s.loan_id = l.loan_id
    GROUP BY l.loan_id
""")
from datetime import date as _date
OBS_END_CHK = _date(2026, 8, 31)


def _months_between(d1, d2):
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


bad = 0
for loan_id, disb_s, term_months, n_snaps in cur.fetchall():
    y, m, d = map(int, disb_s.split("-"))
    disb = _date(y, m, d)
    expected = min(term_months, _months_between(disb, OBS_END_CHK)) + 1  # +1 for the cold-start row
    if n_snaps != expected:
        bad += 1
print(f"[{'PASS' if bad == 0 else 'FAIL'}] loans whose snapshot-row count doesn't match "
      f"(on-book months + 1 cold-start row): {bad} / {total_loans}")
all_pass &= (bad == 0)

print()
print("=" * 78)
print("LATEST-MONTH PORTFOLIO COMPLETENESS (point 1)")
print("=" * 78)
cur.execute("SELECT MAX(snapshot_date) FROM Loan_Performance_Snapshot")
latest = cur.fetchone()[0]
cur.execute("SELECT COUNT(*), ROUND(SUM(outstanding_balance_ksh),0) FROM Loan_Performance_Snapshot WHERE snapshot_date=?", (latest,))
n_active, total_bal = cur.fetchone()
cur.execute("SELECT COUNT(*) FROM Loans WHERE disbursement_date BETWEEN '2026-08-01' AND '2026-08-31'")
aug_loans = cur.fetchone()[0]
cur.execute("""SELECT COUNT(*) FROM Loan_Performance_Snapshot s JOIN Loans l ON l.loan_id=s.loan_id
                WHERE l.disbursement_date BETWEEN '2026-08-01' AND '2026-08-31' AND s.snapshot_date=?""", (latest,))
aug_present = cur.fetchone()[0]
print(f"Latest snapshot month-end: {latest}")
print(f"Active loans in latest month: {n_active}, total outstanding balance: Ksh {total_bal:,.0f}")
print(f"[{'PASS' if aug_present == aug_loans else 'FAIL'}] loans disbursed in the latest month present "
      f"in that month's snapshot: {aug_present} / {aug_loans}")
all_pass &= (aug_present == aug_loans)

print()
print("=" * 78)
print("RECOVERY RATE BOUND (point 2) - per-case, not just in aggregate")
print("=" * 78)
cur.execute("""
    WITH case_open AS (SELECT loan_id, MIN(snapshot_date) d FROM Loan_Performance_Snapshot WHERE par30_flag=1 GROUP BY loan_id),
    cw AS (SELECT loan_id, date(d,'+6 months') AS close_d FROM case_open),
    referred AS (SELECT cw.loan_id, cw.close_d, SUM(r.amount_due_ksh-r.amount_paid_ksh) ref
                 FROM cw JOIN Repayments r ON r.loan_id=cw.loan_id
                 WHERE r.due_date<=cw.close_d AND r.amount_paid_ksh<r.amount_due_ksh GROUP BY cw.loan_id, cw.close_d),
    recov AS (SELECT rf.loan_id, COALESCE(SUM(rt.amount_recovered_ksh),0) rec
              FROM referred rf LEFT JOIN Recovery_Transactions rt
                ON rt.loan_id=rf.loan_id AND rt.recovery_date<=rf.close_d
              GROUP BY rf.loan_id)
    SELECT COUNT(*) FROM referred rf JOIN recov r ON r.loan_id=rf.loan_id WHERE r.rec > rf.ref + 1.0
""")
over100 = cur.fetchone()[0]
print(f"[{'PASS' if over100 == 0 else 'FAIL'}] collection cases where recovered-in-window > referred amount: {over100}")
all_pass &= (over100 == 0)

cur.execute("""
    SELECT COUNT(*) FROM Loans l
    JOIN (SELECT loan_id, snapshot_date, outstanding_balance_ksh, days_past_due, classification,
                 ROW_NUMBER() OVER (PARTITION BY loan_id ORDER BY snapshot_date DESC) rn
          FROM Loan_Performance_Snapshot) s ON s.loan_id = l.loan_id AND s.rn = 1
    WHERE ABS(l.outstanding_balance_ksh - s.outstanding_balance_ksh) > 1.0
       OR l.days_past_due != s.days_past_due
       OR l.current_classification != s.classification
""")
mismatch2 = cur.fetchone()[0]
print(f"[{'PASS' if mismatch2 == 0 else 'FAIL'}] Loans convenience fields != latest snapshot row: {mismatch2}")
all_pass &= (mismatch2 == 0)

print()
print("=" * 78)
print("RECOVERY_TRANSACTIONS <-> COLLECTIONS_ACTIVITY LINKAGE (point 6)")
print("=" * 78)
cur.execute("""SELECT
 (SELECT COUNT(*) FROM Collections_Activity WHERE outcome='Payment Received'),
 (SELECT COUNT(DISTINCT related_activity_id) FROM Recovery_Transactions WHERE related_activity_id IS NOT NULL)""")
pr, linked = cur.fetchone()
print(f"[{'PASS' if pr == linked else 'FAIL'}] 'Payment Received' count ({pr}) == distinct linked-recovery count ({linked})")
all_pass &= (pr == linked)

print()
print("=" * 78)
print("PAR CALCULATION SANITY (point 1 / point 7)")
print("=" * 78)
cur.execute("""
    SELECT snapshot_date,
           ROUND(SUM(CASE WHEN par30_flag=1 THEN outstanding_balance_ksh ELSE 0 END)*100.0/SUM(outstanding_balance_ksh),2) par30_pct,
           ROUND(SUM(CASE WHEN par60_flag=1 THEN outstanding_balance_ksh ELSE 0 END)*100.0/SUM(outstanding_balance_ksh),2) par60_pct,
           ROUND(SUM(CASE WHEN par90_flag=1 THEN outstanding_balance_ksh ELSE 0 END)*100.0/SUM(outstanding_balance_ksh),2) par90_pct
    FROM Loan_Performance_Snapshot GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 1
""")
row = cur.fetchone()
par30, par60, par90 = row[1], row[2], row[3]
sane = par30 is not None and par60 is not None and par90 is not None and par30 >= par60 >= par90 >= 0
print(f"[{'PASS' if sane else 'FAIL'}] Most recent month: PAR30={par30}% >= PAR60={par60}% >= PAR90={par90}% >= 0 (must be monotonic by definition)")
all_pass &= sane

print()
print("=" * 78)
print(f"OVERALL: {'ALL CHECKS PASS' if all_pass else 'AT LEAST ONE CHECK FAILED - DO NOT PROCEED'}")
print("=" * 78)
conn.close()
