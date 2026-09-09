# Plant Production Loss & Bad Actor Analysis

## Industrial Reliability Case Study

This case study demonstrates a production-loss-driven approach to industrial reliability.

Rather than starting from individual equipment KPIs, the analysis begins with the operational impact: **where production was lost, which areas and systems contributed most to those losses, and which bad actors should receive engineering attention first.**

> **Note:** All data used in this project will be synthetic and created exclusively for demonstration purposes. The case does not reproduce confidential data from any real industrial facility.

---

## Business Problem

Industrial plants often have large volumes of maintenance, process and operational information but limited engineering resources to investigate every recurring issue.

The challenge is therefore not simply to identify failures.

It is to answer:

- Where is production being lost?
- Which areas are responsible for the largest losses?
- Which systems or events repeatedly affect plant performance?
- Which bad actors should be prioritized?
- What information is already available to support a deeper investigation?
- Where should Reliability and Maintenance focus first?

---

## Case Scenario

The study will represent a continuous-process industrial plant across **three operating campaigns**.

The dataset will include production-loss events distributed across different:

- production areas;
- systems;
- equipment groups;
- event categories;
- failure or restriction mechanisms;
- campaigns.

Each event will contain information such as production loss, duration, operational impact and affected system.

The scenario will intentionally contain a small number of recurring high-impact problems hidden among a larger number of lower-impact events.

The objective is to identify these bad actors systematically.

---

## Engineering Approach

The analysis will follow the hierarchy:

**Plant → Campaign → Area → System → Event → Bad Actor → Engineering Priority**

The general methodology will be:

1. Quantify total production losses.
2. Compare losses between operating campaigns.
3. Decompose losses by production area.
4. Identify the systems responsible for the greatest impact.
5. Evaluate recurrence and severity of events.
6. Rank bad actors using operational impact.
7. Select the highest-priority opportunities for deeper investigation.
8. Evaluate what additional maintenance, automation and historian data would be required for each deep dive.

---

## Main Analyses

The case will include:

- Total production-loss analysis
- Production-loss comparison by campaign
- Loss decomposition by area
- Loss decomposition by system
- Pareto analysis
- Bad-actor ranking
- Recurrence versus impact analysis
- Event duration and production-impact analysis
- Priority matrix
- Identification of the Top 5 reliability opportunities
- Initial data-availability assessment for subsequent investigation

---

## Key Principle

Traditional reliability indicators such as MTBF and MTTR may support the analysis, but they are **not the starting point of this case**.

The main driver is:

> **Production impact.**

The objective is to prioritize engineering effort according to the problems that most affect plant performance.

---

## Expected Deliverables

At the end of the case, the analysis should provide:

### 1. Production Loss Overview
A clear view of where production has been lost across the three campaigns.

### 2. Area and System Pareto
Identification of the areas and systems responsible for the largest operational impact.

### 3. Bad Actor Ranking
A prioritized list considering loss magnitude, recurrence and operational relevance.

### 4. Top 5 Reliability Opportunities
The five systems or recurring problems that justify deeper engineering investigation.

### 5. Initial Reliability Roadmap
Recommended sequence for subsequent deep dives.

### 6. Data Availability Assessment
Initial definition of which maintenance, automation, process and historian information would be useful for investigating each prioritized bad actor.

---

## What This Case Does Not Cover

This case does not attempt to perform detailed Root Cause Analysis of the selected bad actors.

It also does not yet develop:

- asset health indicators;
- calculated tags;
- early-warning models;
- FMEA;
- RCM;
- anomaly-detection models;
- new instrumentation specifications.

These activities belong to subsequent case studies.

---

## Connection to the Portfolio

This project is the first part of a three-case reliability portfolio:

### Case 1 — Plant Production Loss & Bad Actor Analysis
**Where are we losing production?**

↓

### Case 2 — Systemic Reliability Investigation
**Why are we losing production?**

↓

### Case 3 — Reliability Monitoring & Management System
**How can we detect, treat and prevent recurrence sustainably?**

---

## Planned Tools

The project may use:

- Python
- Pandas
- Statistical analysis
- Power BI
- Industrial reliability concepts
- Maintenance and operational performance analysis

Technology will be used only where it supports the engineering objective.

---

## Author

**Khayan Sobral Marques**  
Reliability & Asset Performance Engineer  
Production Loss Reduction | Maintenance Strategy | Industrial Analytics

[LinkedIn](https://www.linkedin.com/in/khayansm/)
