# Plant Production Loss & Bad Actor Analysis

## Industrial Reliability Case Study

This case demonstrates a production-loss-driven approach to industrial reliability: identify where production was lost, which systems contributed most, and where reliability engineering should focus first.

> All data is synthetic and created exclusively for demonstration. It does not reproduce confidential data from an actual industrial facility.

## Case Results

- Total production loss: **106,546.52 ADt**
- Loss events: **240** across **3 campaigns**
- Four priority areas: **73.95% of loss**
- Top four functional locations: **49.14% of loss**
- Known untreated defect association: **52,643.04 ADt**
- No-prior-detection association: **27,452.31 ADt**
- Active maintenance backlog: **38**
- R1 backlog: **7**

These maintenance-history associations do not prove causality. Read the [full Case 1 executive summary](reports/case1_executive_summary.md) for definitions, limitations, discipline indicators and the proposed investigation roadmap.

![Loss By Area Pareto](reports/figures/02_loss_by_area_pareto.png)

![Loss By Maintenance Context](reports/figures/05_loss_by_maintenance_context.png)

![Top5 Opportunities](reports/figures/08_top5_opportunities.png)

## Business Problem and Engineering Approach

Industrial plants often have abundant maintenance and process information but limited engineering capacity. The question is where production loss is concentrated, which recurring issues matter most, and what evidence would support a deeper investigation.

**Plant → Campaign → Area → System → Event → Bad Actor → Engineering Priority**

Case 1 quantified losses, compared campaigns, built area/system Pareto views, ranked assets by operational impact, connected losses to prior maintenance history, and prioritized five system-level opportunities. The case covers a continuous-process pulp mill across three operating campaigns. Notification activity increased with detection coverage; no production improvement trend was imposed.

The completed deliverables include a production-loss overview, area/system Pareto, bad-actor ranking, analytical maintenance context, discipline indicators, formal-risk backlog, Top 5 opportunities and an initial reliability roadmap. Detailed condition-monitoring and historian evidence remains a Case 2 data-availability requirement.

## Key Principle and Scope

**Production impact** is the starting point. MTBF and MTTR may support later investigation, but they do not replace identifying where production is being lost.

This case does not perform detailed Root Cause Analysis, FMEA, RCM, predictive modeling, early-warning design or new instrumentation specification. These belong to subsequent case studies.

## Reproducibility

The repository contains [raw synthetic datasets](data/raw/README.md), [reference definitions](data/reference/README.md) and a [processed analytical layer](data/processed/README.md). Reporting reads the processed layer without changing source data.

```bash
python scripts/build_case1_report.py
```

The report build requires Python 3 and Matplotlib. Data generation and the analytical build use the Python standard library. No seaborn or composite prioritization score is used.

## Connection to the Portfolio

### Case 1 — Plant Production Loss & Bad Actor Analysis
**Where are we losing production?** Completed: production-impact prioritization and management signals.

### Case 2 — Systemic Reliability Investigation
**Why are we losing production?** Next: investigate one selected system, beginning with White Liquor Clarification.

### Case 3 — Reliability Monitoring & Management System
**How can we detect, treat and prevent recurrence sustainably?** Future: develop monitoring and management practices from validated mechanisms.

## Author

**Khayan Sobral Marques**  
Reliability & Asset Performance Engineer  
Production Loss Reduction | Maintenance Strategy | Industrial Analytics

[LinkedIn](https://www.linkedin.com/in/khayansm/)
