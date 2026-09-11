# Raw Data

This folder contains the synthetic transactional datasets used in the case study.

Datasets:

- `maintenance_history.csv` — synthetic maintenance notifications and work-order history inspired by typical SAP maintenance workflows.
- `production_loss_events.csv` — synthetic operational loss events; `production_loss_adt` is air-dried tonnes (ADt), and production rates are ADt/day.
- `campaign_summary.csv` — summary information for the three operating campaigns used in the case.

These datasets are synthetic and created exclusively for demonstration purposes. They do not reproduce confidential data from any real industrial facility.

`maintenance_cost` represents synthetic maintenance costs in Brazilian reais (BRL).

Relationships between maintenance history and production losses are derived later in the analytical layer; raw data does not store these conclusions or populate maintenance loss-event links.
