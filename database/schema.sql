-- ============================================================================
-- SACCO Loan Delinquency & Collections Performance Analytics
-- Schema: 13 tables. All data loaded via this schema is SYNTHETIC.
-- This dataset is synthetic and was created for analytical demonstration
-- purposes. It is not United Winners DT Sacco's internal data, and the
-- findings do not represent United Winners DT Sacco's actual portfolio
-- performance.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ---------- Dimension tables ----------

CREATE TABLE Branches (
    branch_id       INTEGER PRIMARY KEY,
    branch_name     TEXT NOT NULL,          -- verified: UWS's 3 real branches
    location_area   TEXT
);

CREATE TABLE Loan_Products (
    product_id                 INTEGER PRIMARY KEY,
    product_name                TEXT NOT NULL,      -- verified: UWS's real 13-product catalogue
    category                    TEXT NOT NULL CHECK (category IN ('FOSA','BOSA')),
    typical_term_months         INTEGER,
    typical_interest_rate_pm    REAL,
    rate_source_note            TEXT NOT NULL        -- 'VERIFIED' or 'ASSUMPTION - not publicly disclosed'
);

CREATE TABLE Members (
    member_id                   INTEGER PRIMARY KEY,
    join_date                   TEXT NOT NULL,
    branch_id                   INTEGER NOT NULL REFERENCES Branches(branch_id),
    member_segment               TEXT NOT NULL CHECK (member_segment IN
                                  ('Individual','SME','Corporate','Learning Institution','Religious Institution')),
    employment_type             TEXT NOT NULL CHECK (employment_type IN
                                  ('Salaried-CheckOff','Salaried-Direct','Self-Employed','Business Owner')),
    employer_name                TEXT,               -- nullable; some rows deliberately blank (data-quality issue)
    share_capital_ksh            REAL NOT NULL,
    monthly_savings_target_ksh   REAL NOT NULL,
    member_status                TEXT NOT NULL CHECK (member_status IN ('Active','Dormant','Exited'))
);

CREATE TABLE Collections_Officers (
    officer_id      INTEGER PRIMARY KEY,
    officer_name    TEXT NOT NULL,
    branch_id       INTEGER NOT NULL REFERENCES Branches(branch_id)
);

-- ---------- Central fact ----------

CREATE TABLE Loans (
    loan_id                  INTEGER PRIMARY KEY,
    member_id                INTEGER NOT NULL REFERENCES Members(member_id),
    product_id                INTEGER NOT NULL REFERENCES Loan_Products(product_id),
    branch_id                 INTEGER NOT NULL REFERENCES Branches(branch_id),
    disbursement_date         TEXT NOT NULL,
    principal_amount_ksh       REAL NOT NULL,
    term_months                INTEGER NOT NULL,
    interest_rate_pm           REAL,
    repayment_channel          TEXT NOT NULL CHECK (repayment_channel IN
                                ('Check-Off','Direct-Standing-Order','Cash-MobileMoney')),
    current_classification     TEXT NOT NULL CHECK (current_classification IN
                                ('Normal','Watch','Substandard','Doubtful','Loss')),
    outstanding_balance_ksh    REAL NOT NULL,         -- convenience field; must equal latest snapshot row
    days_past_due              INTEGER NOT NULL,
    guarantor_required         INTEGER NOT NULL CHECK (guarantor_required IN (0,1))
);

-- ---------- Transactional facts ----------

CREATE TABLE Repayments (
    repayment_id        INTEGER PRIMARY KEY,
    loan_id              INTEGER NOT NULL REFERENCES Loans(loan_id),
    installment_number    INTEGER NOT NULL,
    due_date              TEXT NOT NULL,
    amount_due_ksh        REAL NOT NULL,
    amount_paid_ksh       REAL NOT NULL,
    payment_date          TEXT,                       -- nullable; some rows deliberately null (data-quality issue)
    payment_status        TEXT NOT NULL CHECK (payment_status IN
                           ('Paid-OnTime','Paid-Late','Partial','Missed'))
);

CREATE TABLE Employer_Remittances (
    remittance_id          INTEGER PRIMARY KEY,
    loan_id                 INTEGER NOT NULL REFERENCES Loans(loan_id),   -- check-off loans only
    period                  TEXT NOT NULL,
    expected_deduction_ksh   REAL NOT NULL,
    remitted_amount_ksh      REAL NOT NULL,
    remittance_date          TEXT
);

CREATE TABLE Savings_Activity (
    member_id                INTEGER NOT NULL REFERENCES Members(member_id),
    period                    TEXT NOT NULL,
    savings_balance_ksh        REAL NOT NULL,
    monthly_contribution_ksh   REAL NOT NULL,
    contribution_status        TEXT NOT NULL CHECK (contribution_status IN ('Met','Below-Target','Missed')),
    PRIMARY KEY (member_id, period)
);

CREATE TABLE Collections_Activity (
    activity_id     INTEGER PRIMARY KEY,
    loan_id          INTEGER NOT NULL REFERENCES Loans(loan_id),
    officer_id        INTEGER NOT NULL REFERENCES Collections_Officers(officer_id),
    activity_date     TEXT NOT NULL,
    channel           TEXT NOT NULL CHECK (channel IN
                       ('Phone Call','SMS','In-Person Visit','Restructuring Offer','Guarantor Contact')),
    outcome           TEXT NOT NULL CHECK (outcome IN
                       ('Promise-to-Pay','Payment Received','No Contact','Disputed','Refused'))
    -- NOTE: amount_recovered_ksh intentionally removed (Phase 6 correction) -
    -- Recovery_Transactions is the single source of truth for recovered amounts.
);

CREATE TABLE Loan_Guarantees (
    guarantee_id                     INTEGER PRIMARY KEY,
    loan_id                           INTEGER NOT NULL REFERENCES Loans(loan_id),
    guarantor_member_id                INTEGER NOT NULL REFERENCES Members(member_id),
    guaranteed_amount_ksh              REAL NOT NULL,
    guarantor_deposits_committed_ksh   REAL NOT NULL
);

CREATE TABLE Loan_Performance_Snapshot (
    loan_id                 INTEGER NOT NULL REFERENCES Loans(loan_id),
    snapshot_date            TEXT NOT NULL,             -- month-end
    outstanding_balance_ksh   REAL NOT NULL,
    amount_overdue_ksh        REAL NOT NULL,
    days_past_due             INTEGER NOT NULL,
    classification             TEXT NOT NULL CHECK (classification IN
                                ('Normal','Watch','Substandard','Doubtful','Loss')),
    par30_flag                 INTEGER NOT NULL CHECK (par30_flag IN (0,1)),
    par60_flag                 INTEGER NOT NULL CHECK (par60_flag IN (0,1)),
    par90_flag                 INTEGER NOT NULL CHECK (par90_flag IN (0,1)),
    PRIMARY KEY (loan_id, snapshot_date)
);

CREATE TABLE Recovery_Transactions (
    recovery_id           INTEGER PRIMARY KEY,
    loan_id                INTEGER NOT NULL REFERENCES Loans(loan_id),
    recovery_date           TEXT NOT NULL,
    recovery_source         TEXT NOT NULL CHECK (recovery_source IN
                             ('Borrower Payment','Borrower Deposit','Guarantor Deposit','Other Recovery')),
    amount_recovered_ksh     REAL NOT NULL,
    related_activity_id      INTEGER REFERENCES Collections_Activity(activity_id)  -- nullable
);

-- ---------- Shared date dimension ----------

CREATE TABLE Calendar (
    date            TEXT PRIMARY KEY,
    year            INTEGER NOT NULL,
    quarter         TEXT NOT NULL,
    month           INTEGER NOT NULL,
    month_number    INTEGER NOT NULL,
    month_name      TEXT NOT NULL,
    year_month      TEXT NOT NULL,
    month_end_date  TEXT NOT NULL
);

CREATE INDEX idx_loans_member ON Loans(member_id);
CREATE INDEX idx_loans_product ON Loans(product_id);
CREATE INDEX idx_repayments_loan ON Repayments(loan_id);
CREATE INDEX idx_snapshot_loan ON Loan_Performance_Snapshot(loan_id);
CREATE INDEX idx_snapshot_date ON Loan_Performance_Snapshot(snapshot_date);
CREATE INDEX idx_collections_loan ON Collections_Activity(loan_id);
CREATE INDEX idx_recovery_loan ON Recovery_Transactions(loan_id);
