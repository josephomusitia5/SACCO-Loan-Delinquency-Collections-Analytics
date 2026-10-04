"""
Synthetic data generator - SACCO Loan Delinquency & Collections Performance
Analytics.

This dataset is synthetic and was created for analytical demonstration
purposes. It is not United Winners DT Sacco's internal data, and the
findings do not represent United Winners DT Sacco's actual portfolio
performance.

Population sizes (N_MEMBERS, N_LOANS, ...) are a deliberately selected
demonstration scale sufficient to support realistic SQL, Excel, and Power BI
analysis - NOT an estimate of United Winners DT Sacco's actual membership,
loan book, or staffing. Sector figures researched earlier in this project
are used only as loose realism references, never as a target this
simulation is fitted to.

Design principles enforced by this version of the generator:
- Repayments is an IMMUTABLE record of what happened against the ORIGINAL
  schedule. It is never rewritten after the fact.
- Recovery_Transactions is a SEPARATE reconciling layer. A recovery is
  applied FIFO (oldest-first) against whatever original shortfalls are
  still outstanding at that point - it does not retroactively edit
  Repayments.
- days_past_due, at every monthly snapshot, is computed as
  (snapshot_date - oldest_still-outstanding_due_date), not a multiples-of-30
  approximation.
- outstanding_balance = principal - cumulative scheduled repayments -
  cumulative recoveries applied, floored at 0 - computed identically for
  Loans' convenience fields and every Loan_Performance_Snapshot row.
- H1-H5 are seeded on purpose (see Hypothesis Register). Seeding them does
  not make the eventual analysis a "discovery" - see project documentation.
"""
import sqlite3
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "sacco_analytics.db"
SCHEMA_PATH = PROJECT_DIR / "schema.sql"

# ---------------------------------------------------------------------------
# Demonstration-scale population sizes - see docstring above.
# ---------------------------------------------------------------------------
N_MEMBERS = 350
N_LOANS = 650
N_OFFICERS = 6

OBS_START = date(2022, 1, 1)
OBS_END = date(2026, 8, 31)
MEMBER_JOIN_START = date(2016, 1, 1)
SAV_START = date(2023, 1, 1)

BRANCHES = [
    (1, "Headquarters", "Spine Road, Nairobi"),
    (2, "Umoja", "Umoja, Nairobi"),
    (3, "Ruai", "Ruai Mega Mall, Nairobi"),
]

# (id, name, category, term_months, rate_pm, rate_source_note, min_principal, max_principal)
LOAN_PRODUCTS = [
    (1, "Salary Advance", "FOSA", 2, 1.0, "ASSUMPTION - only the Ksh100,000 cap is verified", 5000, 100000),
    (2, "Jeki Loan", "FOSA", 12, 1.5, "ASSUMPTION - not publicly disclosed", 5000, 50000),
    (3, "Product Loan", "FOSA", 12, 1.3, "ASSUMPTION - not publicly disclosed", 10000, 80000),
    (4, "Mtumishi Loan", "FOSA", 24, 1.2, "ASSUMPTION - not publicly disclosed", 10000, 150000),
    (5, "School Fees Loan", "BOSA", 4, 1.4, "ASSUMPTION - not publicly disclosed", 5000, 60000),
    (6, "Bima Loan", "BOSA", 12, 1.3, "ASSUMPTION - not publicly disclosed", 5000, 40000),
    (7, "Development Loan", "BOSA", 36, 1.2, "ASSUMPTION - not publicly disclosed", 50000, 500000),
    (8, "Emergency Loan", "BOSA", 6, 1.6, "ASSUMPTION - not publicly disclosed", 3000, 30000),
    (9, "Instant Loan", "BOSA", 3, 1.7, "ASSUMPTION - not publicly disclosed", 2000, 20000),
    (10, "ELoan", "BOSA", 6, 1.5, "ASSUMPTION - not publicly disclosed", 5000, 50000),
    (11, "Moto Gari Loan", "BOSA", 48, 1.1, "ASSUMPTION - not publicly disclosed", 200000, 1500000),
    (12, "Mjengo Loan", "BOSA", 48, 1.1, "ASSUMPTION - not publicly disclosed", 100000, 2000000),
    (13, "Supa Loan", "BOSA", 60, 1.1, "VERIFIED - LinkedIn company page", 50000, 500000),
]

MEMBER_SEGMENTS = ["Individual", "SME", "Corporate", "Learning Institution", "Religious Institution"]
SEGMENT_WEIGHTS = [0.55, 0.20, 0.10, 0.10, 0.05]
EMPLOYMENT_TYPES = ["Salaried-CheckOff", "Salaried-Direct", "Self-Employed", "Business Owner"]
EMPLOYMENT_WEIGHTS = [0.50, 0.15, 0.20, 0.15]
PRODUCT_WEIGHTS = [0.14, 0.09, 0.06, 0.05, 0.11, 0.07, 0.04, 0.14, 0.13, 0.07, 0.03, 0.03, 0.04]


def month_add(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, 28))


def month_end(d: date) -> date:
    nxt = month_add(date(d.year, d.month, 1), 1)
    return nxt - timedelta(days=1)


def random_date(start: date, end: date) -> date:
    return start + timedelta(days=random.randint(0, (end - start).days))


def months_between(d1: date, d2: date) -> int:
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def classify(days_past_due: int) -> str:
    if days_past_due == 0:
        return "Normal"
    if days_past_due < 30:
        return "Watch"
    if days_past_due < 60:
        return "Substandard"
    if days_past_due < 90:
        return "Doubtful"
    return "Loss"


conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()
cur.executescript(SCHEMA_PATH.read_text())
conn.commit()

cur.executemany("INSERT INTO Branches VALUES (?,?,?)", BRANCHES)
cur.executemany(
    "INSERT INTO Loan_Products (product_id,product_name,category,typical_term_months,"
    "typical_interest_rate_pm,rate_source_note) VALUES (?,?,?,?,?,?)",
    [(p[0], p[1], p[2], p[3], p[4], p[5]) for p in LOAN_PRODUCTS],
)
OFFICER_NAMES = ["A. Mwangi", "B. Otieno", "C. Wanjiru", "D. Kiptoo", "E. Achieng", "F. Njoroge"]
officers = [(i + 1, OFFICER_NAMES[i], random.choice([1, 2, 3])) for i in range(N_OFFICERS)]
cur.executemany("INSERT INTO Collections_Officers VALUES (?,?,?)", officers)

# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
members, member_join, member_segment, member_employment = [], {}, {}, {}
for mid in range(1, N_MEMBERS + 1):
    branch_id = random.choices([1, 2, 3], weights=[0.45, 0.33, 0.22])[0]
    join_d = random_date(MEMBER_JOIN_START, OBS_END)
    segment = random.choices(MEMBER_SEGMENTS, weights=SEGMENT_WEIGHTS)[0]
    employment = random.choices(EMPLOYMENT_TYPES, weights=EMPLOYMENT_WEIGHTS)[0]
    employer_name = None
    if employment == "Salaried-CheckOff":
        employer_name = f"Employer_{random.randint(1, 40):03d}"
        if random.random() < 0.04:
            employer_name = None
    share_capital = round(17000 * random.uniform(0.95, 1.15), -2)
    savings_target = round(1500 * random.uniform(0.9, 1.3), -1)
    status = random.choices(["Active", "Dormant", "Exited"], weights=[0.82, 0.12, 0.06])[0]
    members.append((mid, join_d.isoformat(), branch_id, segment, employment,
                     employer_name, share_capital, savings_target, status))
    member_join[mid] = join_d
    member_segment[mid] = segment
    member_employment[mid] = employment

next_id = N_MEMBERS + 1
for _ in range(3):
    src = random.choice(members)
    members.append((next_id,) + src[1:])
    member_join[next_id] = member_join[src[0]]
    member_segment[next_id] = member_segment[src[0]]
    member_employment[next_id] = member_employment[src[0]]
    next_id += 1

cur.executemany("INSERT INTO Members VALUES (?,?,?,?,?,?,?,?,?)", members)
member_ids = [m[0] for m in members]
member_branch = {m[0]: m[2] for m in members}
conn.commit()
print(f"Members inserted: {len(members)}")

# ---------------------------------------------------------------------------
# Loans + everything derived from a loan's monthly simulation.
#
# H1: larger loans (relative to their own product's range) / SME-Corporate
#     segment / Business Owner -> higher risk
# H2: shorter member tenure at disbursement -> higher risk
# H3: loans disbursed Jan-Apr 2025 -> elevated risk (seeded weak vintage)
# H4: handled after this loop, against Savings_Activity
# H5: repayment channel changes risk composition (Check-Off lower baseline
#     but exposed to employer-remittance risk; Direct/Cash-Mobile higher
#     baseline, expressed as the member's own missed payments)
# ---------------------------------------------------------------------------
loans, repayments, remittances = [], [], []
collections_activity, recoveries, snapshots, loan_guarantees = [], [], [], []
delinquency_onsets = []

loan_id_ctr = repay_id_ctr = remit_id_ctr = activity_id_ctr = recovery_id_ctr = 1
product_by_id = {p[0]: p for p in LOAN_PRODUCTS}

for _ in range(N_LOANS):
    member_id = random.choice(member_ids)
    product_id = random.choices([p[0] for p in LOAN_PRODUCTS], weights=PRODUCT_WEIGHTS)[0]
    _, pname, category, term_typ, rate, rate_note, pmin, pmax = product_by_id[product_id]

    join_d = member_join[member_id]
    earliest = max(OBS_START, join_d)
    if earliest >= OBS_END:
        earliest = OBS_END - timedelta(days=30)
    disb = random_date(earliest, OBS_END)

    term_months = max(1, term_typ + random.randint(-1, 1))
    principal = round(random.uniform(pmin, pmax), -2)
    branch_id = member_branch[member_id]
    segment = member_segment[member_id]
    employment = member_employment[member_id]

    if employment == "Salaried-CheckOff":
        channel = random.choices(["Check-Off", "Direct-Standing-Order", "Cash-MobileMoney"],
                                  weights=[0.85, 0.10, 0.05])[0]
    else:
        channel = random.choices(["Check-Off", "Direct-Standing-Order", "Cash-MobileMoney"],
                                  weights=[0.05, 0.55, 0.40])[0]

    guarantor_required = 1 if (category == "BOSA" and principal > 40000) else 0

    size_risk = (principal - pmin) / max(1, (pmax - pmin))
    segment_risk = 1 if segment in ("SME", "Corporate") or employment == "Business Owner" else 0
    tenure_months = months_between(join_d, disb)
    tenure_risk = 1 if tenure_months < 12 else (0.4 if tenure_months < 24 else 0)
    vintage_risk = 1 if date(2025, 1, 1) <= disb <= date(2025, 4, 30) else 0
    channel_adj = -0.06 if channel == "Check-Off" else (0.06 if channel == "Cash-MobileMoney" else 0.0)

    risk_score = 0.08 + 0.16 * size_risk + 0.13 * segment_risk + 0.20 * tenure_risk \
        + 0.16 * vintage_risk + channel_adj
    risk_score = max(0.03, min(0.6, risk_score))

    observable_months = min(term_months, months_between(disb, OBS_END))
    ever_delinquent = observable_months >= 3 and random.random() < risk_score

    onset = episode_len = recovers = recovery_offset = None
    if ever_delinquent:
        onset = random.randint(2, max(2, observable_months - 1))
        episode_len = random.randint(2, 7)
        recovers = random.random() < (0.65 - 0.35 * risk_score)
        if recovers:
            recovery_offset = random.randint(1, episode_len)

    installment_amt = round(principal / term_months, 2)

    # ---- month-0 "cold start" snapshot: the loan is on the outstanding
    # portfolio from its disbursement month, even before its first
    # instalment has come due. Every loan gets exactly one of these,
    # unconditionally - this is what fixes the 650-vs-616 gap: a loan
    # disbursed in the final observed month previously got observable_months
    # = 0 and therefore NO snapshot row at all, silently dropping it from
    # every latest-month portfolio total. ----
    disb_snap_date = month_end(disb)
    snapshots.append((loan_id_ctr, disb_snap_date.isoformat(), principal, 0.0, 0,
                       "Normal", 0, 0, 0))

    # ---- monthly simulation: Repayments is immutable; shortfall_queue is
    #      the running FIFO ledger of still-outstanding original shortfalls,
    #      and Recovery_Transactions reconciles against it, oldest-first ----
    shortfall_queue = []          # [[due_date, remaining_shortfall_ksh], ...]
    cum_paid_original = 0.0
    cum_recovered = 0.0
    recovered_already = False
    last_activity_id_for_loan = None
    onset_calendar_date = None

    for month_i in range(1, observable_months + 1):
        due_d = month_add(disb, month_i)
        in_episode = ever_delinquent and onset is not None and onset <= month_i < onset + episode_len

        if not ever_delinquent or month_i < onset or recovered_already:
            status = "Paid-OnTime" if random.random() > 0.05 else "Paid-Late"
            paid = installment_amt
            pay_date = due_d.isoformat() if status == "Paid-OnTime" else (due_d + timedelta(days=random.randint(3, 10))).isoformat()
        else:
            status = random.choices(["Missed", "Partial"], weights=[0.6, 0.4])[0]
            paid = 0.0 if status == "Missed" else round(installment_amt * random.uniform(0.2, 0.7), 2)
            pay_date = None if status == "Missed" else (due_d + timedelta(days=random.randint(5, 25))).isoformat()
            if in_episode and onset_calendar_date is None:
                onset_calendar_date = due_d
                delinquency_onsets.append((member_id, onset_calendar_date))

        cum_paid_original += paid
        repayments.append((repay_id_ctr, loan_id_ctr, month_i, due_d.isoformat(),
                            installment_amt, paid, pay_date, status))
        repay_id_ctr += 1

        if channel == "Check-Off":
            remittances.append((remit_id_ctr, loan_id_ctr, due_d.isoformat(), installment_amt, paid, pay_date))
            remit_id_ctr += 1

        shortfall = round(installment_amt - paid, 2)
        if shortfall > 0.01:
            shortfall_queue.append([due_d, shortfall])

        # collections contact during an active, unresolved episode
        if in_episode and not recovered_already and random.random() < 0.55:
            branch_officers = [o[0] for o in officers if o[2] == branch_id] or [o[0] for o in officers]
            officer_id = random.choice(branch_officers)
            ch = random.choices(["Phone Call", "SMS", "In-Person Visit", "Restructuring Offer", "Guarantor Contact"],
                                 weights=[0.4, 0.3, 0.15, 0.1, 0.05])[0]
            outc = random.choices(["Promise-to-Pay", "No Contact", "Disputed", "Refused"],
                                   weights=[0.5, 0.3, 0.1, 0.1])[0]
            collections_activity.append((activity_id_ctr, loan_id_ctr, officer_id, due_d.isoformat(), ch, outc))
            last_activity_id_for_loan = activity_id_ctr
            activity_id_ctr += 1

        # recovery event: pays down shortfall_queue FIFO (oldest-first) -
        # the arrears amount is the TRUE queue total at this point, not an
        # installment_amt * count approximation
        if ever_delinquent and recovers and not recovered_already and month_i == onset + recovery_offset:
            arrears = round(sum(s for _, s in shortfall_queue), 2)
            severity = len(shortfall_queue)
            if severity <= 2:
                source = "Borrower Payment"
            elif severity <= 4:
                source = random.choices(["Borrower Payment", "Borrower Deposit"], weights=[0.6, 0.4])[0]
            else:
                source = random.choices(["Borrower Deposit", "Guarantor Deposit", "Other Recovery"],
                                         weights=[0.5, 0.35, 0.15])[0]
            link = last_activity_id_for_loan if random.random() < 0.8 else None
            recoveries.append((recovery_id_ctr, loan_id_ctr, due_d.isoformat(), source, arrears, link))
            if link is not None:
                for idx, row in enumerate(collections_activity):
                    if row[0] == link:
                        collections_activity[idx] = row[:5] + ("Payment Received",)
            recovery_id_ctr += 1

            remaining = arrears
            new_queue = []
            for d_, s_ in shortfall_queue:
                applied = min(remaining, s_)
                net = round(s_ - applied, 2)
                remaining = round(remaining - applied, 2)
                if net > 0.01:
                    new_queue.append([d_, net])
            shortfall_queue = new_queue
            cum_recovered += arrears
            recovered_already = True

        # ---- derive this month's snapshot from the current queue state ----
        snap_date = month_end(due_d)
        if shortfall_queue:
            oldest_due = shortfall_queue[0][0]
            days_past_due = (snap_date - oldest_due).days
            amount_overdue = round(sum(s for _, s in shortfall_queue), 2)
        else:
            days_past_due = 0
            amount_overdue = 0.0
        outstanding = max(0.0, round(principal - cum_paid_original - cum_recovered, 2))
        cls = classify(days_past_due)
        snapshots.append((loan_id_ctr, snap_date.isoformat(), outstanding, amount_overdue, days_past_due,
                           cls, int(days_past_due >= 30), int(days_past_due >= 60), int(days_past_due >= 90)))

    if snapshots and snapshots[-1][0] == loan_id_ctr:
        _, _, last_bal, _, last_dpd, last_cls, _, _, _ = snapshots[-1]
    else:
        last_bal, last_dpd, last_cls = principal, 0, "Normal"

    loans.append((loan_id_ctr, member_id, product_id, branch_id, disb.isoformat(), principal,
                  term_months, rate, channel, last_cls, last_bal, last_dpd, guarantor_required))

    if guarantor_required:
        candidates = [m for m in member_ids if m != member_id]
        for g in random.sample(candidates, k=min(2, len(candidates))):
            loan_guarantees.append((len(loan_guarantees) + 1, loan_id_ctr, g,
                                     round(principal * 0.5, 2), round(random.uniform(5000, 40000), 2)))
    loan_id_ctr += 1

cur.executemany("INSERT INTO Loans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", loans)
cur.executemany("INSERT INTO Repayments VALUES (?,?,?,?,?,?,?,?)", repayments)
cur.executemany("INSERT INTO Employer_Remittances VALUES (?,?,?,?,?,?)", remittances)
cur.executemany("INSERT INTO Collections_Activity VALUES (?,?,?,?,?,?)", collections_activity)
cur.executemany("INSERT INTO Recovery_Transactions VALUES (?,?,?,?,?,?)", recoveries)
cur.executemany("INSERT INTO Loan_Performance_Snapshot VALUES (?,?,?,?,?,?,?,?,?)", snapshots)
cur.executemany("INSERT INTO Loan_Guarantees VALUES (?,?,?,?,?)", loan_guarantees)
conn.commit()
print(f"Loans: {len(loans)}, Repayments: {len(repayments)}, Remittances: {len(remittances)}, "
      f"Collections_Activity: {len(collections_activity)}, Recoveries: {len(recoveries)}, "
      f"Snapshots: {len(snapshots)}, Guarantees: {len(loan_guarantees)}, "
      f"Delinquency onsets (for H4): {len(delinquency_onsets)}")

# ---------------------------------------------------------------------------
# Savings_Activity - baseline, then H4 override in the 1-2 months before onset
# ---------------------------------------------------------------------------
savings = {}
for mid in member_ids:
    start = max(SAV_START, member_join[mid])
    n_months = max(0, months_between(start, OBS_END))
    target = next(m[7] for m in members if m[0] == mid)
    balance = round(random.uniform(2000, 15000), 2)
    for i in range(n_months + 1):
        period = month_end(month_add(start, i))
        status = random.choices(["Met", "Below-Target", "Missed"], weights=[0.82, 0.13, 0.05])[0]
        contrib = target if status == "Met" else (target * random.uniform(0.2, 0.7) if status == "Below-Target" else 0.0)
        balance = max(0.0, round(balance + contrib - random.uniform(0, target * 0.3), 2))
        savings[(mid, period.isoformat())] = [mid, period.isoformat(), balance, round(contrib, 2), status]

for mid, onset_d in delinquency_onsets:
    for back in (1, 2):
        p = month_end(month_add(onset_d, -back)).isoformat()
        if (mid, p) in savings and random.random() < 0.70:
            new_status = random.choices(["Below-Target", "Missed"], weights=[0.65, 0.35])[0]
            row = savings[(mid, p)]
            target = next(m[7] for m in members if m[0] == mid)
            row[3] = round(target * random.uniform(0.0, 0.5), 2)
            row[4] = new_status

cur.executemany("INSERT INTO Savings_Activity VALUES (?,?,?,?,?)", [tuple(v) for v in savings.values()])
conn.commit()
print(f"Savings_Activity rows: {len(savings)}")

# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
cal_rows = []
d = MEMBER_JOIN_START
while d <= OBS_END:
    q = (d.month - 1) // 3 + 1
    cal_rows.append((d.isoformat(), d.year, f"Q{q}", d.month, d.month, d.strftime("%B"),
                      f"{d.year}-{d.month:02d}", month_end(d).isoformat()))
    d += timedelta(days=1)
cur.executemany("INSERT INTO Calendar VALUES (?,?,?,?,?,?,?,?)", cal_rows)
conn.commit()
print(f"Calendar rows: {len(cal_rows)}")

conn.close()
print("Done.")
