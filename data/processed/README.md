# Reliability analytical layer

Run `python scripts/build_reliability_analysis.py` from the repository root to rebuild the six UTF-8 CSVs deterministically using the Python standard library. The snapshot is **2025-11-15**. Raw and reference CSVs are immutable; their bytes are checked before and after every build. Both enriched extracts preserve every source column and row.

| Output | Grain and purpose |
|---|---|
| `maintenance_enriched.csv` | Notification; hierarchy, response, recurrence and risk indicators |
| `loss_event_analysis.csv` | Loss event; exact asset/failure-mode maintenance context and supporting notification IDs |
| `discipline_performance.csv` | Receiving discipline; notification indicators and loss associations |
| `bad_actor_ranking.csv` | Asset with notifications or losses; ranked by attributed production loss |
| `functional_location_ranking.csv` | Functional location; includes asset-attributed and process losses for the system Pareto |
| `risk_backlog.csv` | Active notification/work order; ordered by formal risk, priority and notification date |

## Time and maintenance context

V1 matches **exact asset_id + exact failure_mode**, with an inclusive **180-day** prior-confirmed-notification lookback. Coverage starts at the first campaign operating date (2023-01-01), representing the extract boundary rather than each asset's first notification. `history_coverage_eligible` indicates 180 elapsed days of extract coverage, including for system events. Maintenance dates must be strictly earlier than the loss date; same-day reports are not proven prior detection.

Context precedence is the order below. These are analytical associations, **not proven root causes**.

1. `SYSTEM_PROCESS_EVENT`: no asset attribution.
2. `POST_MAINTENANCE_RECURRENCE`: latest meaningful confirmed-defect correction completed 7–120 days earlier, with no newer confirmed matching report strictly before the loss date.
3. `KNOWN_UNTREATED_DEFECT`: confirmed matching report within 180 days and no meaningful correction on/after the latest report date and strictly before the loss date.
4. `INSUFFICIENT_HISTORY`: no matching confirmed report in the window and fewer than 180 days of extract coverage, unless a prior rule applies.
5. `NO_PRIOR_DETECTION`: sufficient coverage, no confirmed report in the window or on the loss date, and no matching meaningful correction in the previous 180 days.
6. `OTHER_AMBIGUOUS`: remaining asset events, including recent corrections outside the 7–120-day window.

Meaningful correction requires a populated work order, `Completed` order status, `WORK_COMPLETED` closure, an action other than blank/`Inspection only`, and a completed execution date. Loss-context matching additionally requires a confirmed defect. A future completion never establishes treatment before an event.

`latest_prior_*` identifies the latest **confirmed report within the 180-day window**. `latest_completed_corrective_*` identifies the latest matching meaningful confirmed-defect correction strictly before the event, even outside that window. Ties use notification ID. Closure codes, action types and work-order IDs are the linked notification's **snapshot attributes**, not evidence those attributes existed at the event time: closure and replanning timestamps are unavailable. These fields must not independently establish event-time treatment.

## Indicator definitions

Notification recurrence includes confirmed and unconfirmed reports: a preceding same-asset/mode notification within 180 days. Dates then notification IDs determine order; same-date earlier IDs have a zero-day gap. Age is snapshot minus notification date for all records, not time in backlog. Order lead time is creation minus notification date; execution lead time is completion minus notification date for completed orders, including inspection-only work.

Active backlog is notification `Open`/`In Progress` **or** order `Created`/`Released`/`Scheduled`. Response-state precedence: active order → open/in-progress notification → cancelled → completed corrective action → confirmed/unconfirmed closure without order → monitor condition → other closed. Thus no-order monitor closures retain the confirmed/unconfirmed no-order state; the original closure code remains available.

All discipline rates are fractions of that discipline's total notifications, **except `confirmed_to_order_rate`**, whose denominator is confirmed defects. Zero denominators produce blanks. Rates and Pareto shares have six decimal places; monetary/loss amounts have two. `r1_r3_backlog_count` includes R1, R2 and R3. Risk is joined directly from the existing nine-cell matrix using asset criticality and notification priority; defect status is the matrix label, not the confirmation flag. Age and replanning do not override formal risk.

Each known-untreated event is associated once with the latest prior report's receiving discipline. Each post-maintenance event is associated once with the discipline responsible for its latest meaningful corrective notification. These refer to `responsible_discipline`, not reassigned ownership; they do not prove that a discipline caused the loss. No detection-quality or team-performance interpretation is stored as a categorical label.

Assets rank by total loss descending, then event count descending, then asset ID. Locations use the same ordering with location as the final tie-breaker. Assets with maintenance but no losses remain visible with zero loss; highest active risk is blank where no backlog exists. Location totals include events without asset attribution. The positive-control fan remains visible as a zero-loss asset.

Units: production losses are air-dried tonnes (**ADt**), production rates **ADt/day**, maintenance costs synthetic **BRL**, labor hours, and elapsed calendar days. The build prints reconciliations, context regression comparisons, the complete discipline matrix, rankings and formal-risk backlog. A discrepancy from generator QA counts is reported rather than corrected by changing source data.
