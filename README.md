# SACCO Loan Delinquency & Collections Analytics

**A synthetic-data analytics demonstration** — SQL → Excel → Power BI — for loan-portfolio
risk and collections performance, modeled on the Kenyan SACCO sector.

**Case-study reference organization:** United Winners DT SACCO, Nairobi

> ⚠️ **This project uses 100% synthetic, seeded data.** It does not use, reference, or claim
> access to United Winners DT Sacco's (or any SACCO's) actual internal data. Every figure
> below is generated for demonstration purposes only. See [Synthetic Data & Credibility](#synthetic-data--credibility).

---

## Dashboard Preview

Four pages, built in Power BI Desktop from the same validated data model as the Excel workbook.

### Executive Overview
![Executive Overview](Project%20Images/01_executive_overview.png)
Headline portfolio KPIs, the portfolio-at-risk trend over time, and product/segment/branch filters.

### Problem Drivers
![Problem Drivers](Project%20Images/02_problem_drivers.png)
Delinquency and PAR30 by product and member segment, arrears source, vintage risk, and savings behaviour ahead of delinquency.

### Collections Effectiveness
![Collections Effectiveness](Project%20Images/03_collections_effectiveness.png)
Recovery rate, recovery per contact and conversion by channel, recovery source split, and officer-level activity.

### Management Monitoring
![Management Monitoring](Project%20Images/04_management_monitoring.png)
Loan-level drill-down: repayment history, collections history, recovery transactions, and a 60–89 day monitoring list.

---

## Overview

Most SACCOs monitor loan delinquency after the fact — a monthly report reviewed once a
credit committee meets. This project demonstrates what continuous, multi-angle portfolio
monitoring could look like instead: financial exposure and operational delinquency tracked
separately, arrears traced to their actual source, collections effectiveness measured per
channel, and early-warning behavioral signals tested against default.

The same validated metric definitions are implemented three ways — raw SQL, a live-formula
Excel workbook, and a four-page Power BI dashboard — and reconciled to the decimal place, so
the same question gets the same answer no matter which tool someone reaches for.

## Business Problem

**Loan Portfolio Risk & Collections Performance Analytics.** The project shows how a SACCO
could use data to monitor:

- Loan delinquency (operational, count-based)
- PAR30 / PAR60 / PAR90 (financial exposure, balance-weighted)
- Loan-count risk vs. balance-at-risk
- Arrears source (employer/check-off failure vs. member-side shortfall)
- Collections effectiveness (channel conversion, recovery per contact)
- Recovery rate (within a defined case window)
- Early-warning behavioral patterns (savings behavior ahead of delinquency)
- Vintage/cohort performance

## Repository Structure

```
sacco-loan-delinquency-collections-analytics/
├── README.md
├── Project Images/              # dashboard page screenshots, embedded above
│   ├── 01_executive_overview.png
│   ├── 02_problem_drivers.png
│   ├── 03_collections_effectiveness.png
│   └── 04_management_monitoring.png
├── database/
│   ├── schema.sql              # 13-table relational schema, CHECK-constrained
│   ├── generate_data.py        # synthetic data generator (seeded, reproducible)
│   ├── qc_report.py            # automated data-quality / integrity checks
│   └── sacco_analytics.db      # SQLite database (generated)
├── sql/
│   └── business_queries.sql    # every core metric, defined once, validated
├── powerbi/
│   ├── powerbi_csv_export/     # flattened CSV exports (16 tables) for Power BI / Excel
│   └── SACCO_Analytics.pbix    # Power BI model (add once built in Power BI Desktop)
├── excel/
│   └── SACCO_Loan_Collections_Analytics_Workbook.xlsx
└── presentation/
    └── SACCO_Executive_Presentation.pptx
```

## Tech Stack

`SQLite` · `SQL` · `Python` (data generation & QC) · `Excel` (Power Query, Data Model,
PivotTable-style analysis) · `Power BI` (Power Query, DAX, 4-page dashboard)

## Data Model

13 core tables in a star-schema-style layout:

- **Dimensions:** `Branches`, `Loan_Products`, `Members`, `Collections_Officers`, `Calendar`
- **Facts:** `Loans`, `Loan_Performance_Snapshot` (monthly, the core fact table),
  `Repayments`, `Employer_Remittances`, `Savings_Activity`, `Collections_Activity`,
  `Loan_Guarantees`, `Recovery_Transactions`

Three additional derived, already-validated views are exported for Power BI/Excel
consumption: `Arrears_Detail`, `Collection_Cases`, `Savings_Comparison_Detail`.

All referential-integrity, balance-reconciliation, and business-rule checks run
automatically (`qc_report.py` at the SQL layer; a mirrored live-formula version in the
Excel workbook's `Data_Quality` sheet) — both currently **all PASS**.

## Locked Metric Definitions

| Metric | Definition |
|---|---|
| Loan Delinquency Rate | Delinquent active loans / active loans (**operational**, count-based) |
| PAR30 / PAR60 / PAR90 | Balance of loans ≥30/60/90 days past due / gross outstanding portfolio (**financial exposure**, balance-weighted) |
| Recovery Rate | Recoveries within a defined 6-month case window / amount referred into that case during the same window |

These two metric families (operational vs. financial-exposure) are tracked separately
throughout and never blended into a single number.

## Key Findings *(synthetic demonstration data)*

- Delinquency risk concentrates heavily by member segment and product type — Corporate and
  Religious Institution segments carry PAR30 several times the Individual-member average.
- 76.6% of arrears value originates with the member's own repayment shortfall, vs. 23.4%
  from employer/check-off remittance failure.
- Recovery Rate: 22.4% (within the defined 6-month case window); Recovery per Contact
  varies meaningfully by collections channel.
- A savings-contribution dip in the two months before a loan first goes 30+ days past due
  is present in this seeded data (48.9% vs. 18.2% for a matched comparison group) — worth
  testing as a leading indicator on real data.

Framed as hypotheses for a real SACCO's management to test, not conclusions about any real
organization's portfolio.

## How to Reproduce

```bash
python database/generate_data.py     # builds sacco_analytics.db from schema.sql
python database/qc_report.py         # runs the automated data-quality checks
sqlite3 database/sacco_analytics.db < sql/business_queries.sql
```

Open `excel/SACCO_Loan_Collections_Analytics_Workbook.xlsx` directly — every KPI and
analysis table recalculates live from the embedded data. See its `README` sheet for the
Power Query / Data Model / native-PivotTable build spec. For Power BI, import
`powerbi/powerbi_csv_export/*.csv` and rebuild the model per the DAX measures documented in
the Excel workbook's `README` sheet.

## Synthetic Data & Credibility

This project does **not** claim access to any SACCO's internal systems or member data.
Every number is generated by `generate_data.py` (seeded, reproducible) to a demonstration
scale. The correct framing, always: *"I researched a relevant SACCO-sector problem and
built a working analytics demonstration using synthetic data to show how this approach
could be applied to a SACCO such as United Winners."*

## Limitations

- Demonstration-scale data — some cuts (e.g., individual vintage-cohort months) carry small
  sample sizes; read pooled comparisons as the primary signal.
- Two products' interest-rate figures are explicit assumptions where the real rate is not
  publicly disclosed (flagged in `Dim_Products.rate_source_note`); all other product/branch
  facts are drawn from United Winners' public catalogue.
- The savings-behavior "matched comparison" controls for calendar month only, not for
  product mix, segment, or risk profile — stated explicitly as a limitation, not hidden.

## Author

**Joseph Omusitia** — josephomusitia5@gmail.com · [LinkedIn](https://linkedin.com/in/joseph-omusitia-18138a379) · [GitHub](https://github.com/josephomusitia5)
