"""Build the V1 reliability analytical layer; Python 3 standard library only.

Run: python scripts/build_reliability_analysis.py
See data/processed/README.md for definitions and analytical limitations.
Only the six named processed CSVs are written; source files are read-only.
"""

import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AS_OF_DATE = date(2025, 11, 15)
LOOKBACK = 180
ACTIVE_ORDERS = {"Created", "Released", "Scheduled"}
CONTEXTS = (
    "NO_PRIOR_DETECTION", "KNOWN_UNTREATED_DEFECT", "POST_MAINTENANCE_RECURRENCE",
    "SYSTEM_PROCESS_EVENT", "INSUFFICIENT_HISTORY", "OTHER_AMBIGUOUS",
)
STATES = {
    "OPEN_NOTIFICATION", "ACTIVE_WORK_ORDER", "COMPLETED_CORRECTIVE_ACTION",
    "CLOSED_CONFIRMED_WITHOUT_ORDER", "CLOSED_UNCONFIRMED_WITHOUT_ORDER",
    "MONITOR_CONDITION", "CANCELLED", "OTHER_CLOSED",
}
MASTER_FIELDS = "island area system_id system_name asset_type asset_criticality".split()
MAINTENANCE_ADDED = MASTER_FIELDS + (
    "converted_to_order closed_without_order confirmed_closed_without_order "
    "unconfirmed_closed_without_order recurrent_notification days_since_previous_same_defect "
    "notification_age_days days_to_order execution_lead_days active_backlog risk_class "
    "risk_sort_order defect_status maintenance_response_state"
).split()
LOSS_ADDED = (
    "history_coverage_eligible maintenance_context prior_confirmed_notification_count_180d "
    "latest_prior_notification_id latest_prior_notification_date latest_prior_responsible_discipline "
    "latest_prior_work_order_id latest_prior_closure_code latest_prior_action_type latest_prior_risk_class "
    "latest_prior_risk_sort_order days_from_latest_notification_to_loss "
    "latest_completed_corrective_notification_id latest_completed_corrective_date "
    "days_from_corrective_completion_to_loss"
).split()
ASSOCIATION_FIELDS = (
    "known_untreated_loss_event_count known_untreated_loss_adt "
    "post_maintenance_recurrence_event_count post_maintenance_recurrence_loss_adt"
).split()
DISCIPLINE_FIELDS = (
    "responsible_discipline notification_count confirmed_defect_count confirmed_defect_rate "
    "converted_to_order_count conversion_rate confirmed_to_order_count confirmed_to_order_rate "
    "closed_without_order_count closed_without_order_rate confirmed_closed_without_order_count "
    "confirmed_closed_without_order_rate unconfirmed_closed_without_order_count "
    "unconfirmed_closed_without_order_rate recurrent_notification_count recurrence_rate "
    "reassigned_count reassignment_rate active_backlog_count r1_r3_backlog_count"
).split() + ASSOCIATION_FIELDS
ASSET_FIELDS = (
    "bad_actor_rank asset_id functional_location island area system_id system_name asset_type "
    "asset_criticality production_loss_event_count total_production_loss_adt average_loss_adt "
    "maximum_loss_adt maintenance_notification_count confirmed_defect_count recurrent_notification_count "
    "active_backlog_count highest_active_risk_class highest_active_risk_sort_order"
).split() + ASSOCIATION_FIELDS
LOCATION_FIELDS = (
    "location_rank functional_location island area system_id system_name production_loss_event_count "
    "total_production_loss_adt share_of_total_loss cumulative_share_of_total_loss "
    "maintenance_notification_count confirmed_defect_count active_backlog_count"
).split() + ASSOCIATION_FIELDS
BACKLOG_FIELDS = (
    "notification_id work_order_id functional_location asset_id island area system_id system_name "
    "asset_type asset_criticality notification_date notification_priority defect_status risk_class "
    "risk_sort_order responsible_discipline failure_mode notification_status order_status replanning_count "
    "notification_age_days maintenance_response_state"
).split()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames), list(reader)


def encode(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def flag(value):
    return "TRUE" if value else "FALSE"


def fixed(value, places=2):
    return str(Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def rate(numerator, denominator):
    return fixed(Decimal(numerator) / denominator, 6) if denominator else ""


def day(value):
    return date.fromisoformat(value)


def meaningful(row):
    return bool(row["work_order_id"] and row["order_status"] == "Completed"
                and row["closure_code"] == "WORK_COMPLETED"
                and row["action_type"] not in ("", "Inspection only") and row["actual_end_date"])


def response_state(row):
    if row["order_status"] in ACTIVE_ORDERS:
        return "ACTIVE_WORK_ORDER"
    if row["notification_status"] in {"Open", "In Progress"}:
        return "OPEN_NOTIFICATION"
    if row["order_status"] == "Cancelled" or row["closure_code"] == "CANCELLED":
        return "CANCELLED"
    if meaningful(row):
        return "COMPLETED_CORRECTIVE_ACTION"
    if row["closed_without_order"] == "TRUE":
        return "CLOSED_CONFIRMED_WITHOUT_ORDER" if row["defect_confirmed"] == "TRUE" else "CLOSED_UNCONFIRMED_WITHOUT_ORDER"
    if row["closure_code"] == "MONITOR_CONDITION":
        return "MONITOR_CONDITION"
    return "OTHER_CLOSED"


def enrich_maintenance(raw, assets, matrix):
    by_id = {a["asset_id"]: a for a in assets}
    risks = {(r["asset_criticality"], r["notification_priority"]): r for r in matrix}
    require(len(by_id) == len(assets), "Duplicate master asset ID")
    require(len(risks) == len(matrix) == 9, "Risk matrix is not a unique nine-cell mapping")
    previous = {}
    enriched = {}
    for source in sorted(raw, key=lambda r: (r["notification_date"], r["notification_id"])):
        row = dict(source)
        asset = by_id[row["asset_id"]]
        require(asset["functional_location"] == row["functional_location"], "Invalid maintenance asset/location pair")
        row.update({k: asset[k] for k in MASTER_FIELDS})
        converted = bool(row["work_order_id"])
        closed = row["notification_status"] == "Closed" and not converted
        confirmed = row["defect_confirmed"] == "TRUE"
        notification_date = day(row["notification_date"])
        pair = row["asset_id"], row["failure_mode"]
        gap = (notification_date - previous[pair]).days if pair in previous else None
        active = row["notification_status"] in {"Open", "In Progress"} or row["order_status"] in ACTIVE_ORDERS
        row.update(converted_to_order=flag(converted), closed_without_order=flag(closed),
                   confirmed_closed_without_order=flag(closed and confirmed),
                   unconfirmed_closed_without_order=flag(closed and not confirmed),
                   recurrent_notification=flag(gap is not None and gap <= LOOKBACK),
                   days_since_previous_same_defect="" if gap is None else str(gap),
                   notification_age_days=str((AS_OF_DATE - notification_date).days),
                   days_to_order=str((day(row["order_created_date"]) - notification_date).days) if converted else "",
                   execution_lead_days=str((day(row["actual_end_date"]) - notification_date).days) if row["order_status"] == "Completed" else "",
                   active_backlog=flag(active))
        risk = risks[(row["asset_criticality"], row["notification_priority"])]
        row.update({k: risk[k] for k in ("risk_class", "risk_sort_order", "defect_status")})
        row["maintenance_response_state"] = response_state(row)
        previous[pair] = notification_date
        enriched[row["notification_id"]] = row
    # Preserve source order and every source column, even if source order changes.
    return [enriched[r["notification_id"]] for r in raw]


def loss_context(asset_id, event_day, matching, coverage_start):
    eligible = (event_day - coverage_start).days >= LOOKBACK
    if not asset_id:
        return "SYSTEM_PROCESS_EVENT", [], None, None, eligible
    confirmed = [r for r in matching if r["defect_confirmed"] == "TRUE"]
    prior = [r for r in confirmed if day(r["notification_date"]) < event_day]
    recent = [r for r in prior if (event_day - day(r["notification_date"])).days <= LOOKBACK]
    latest = max(recent, key=lambda r: (r["notification_date"], r["notification_id"]), default=None)
    completed = [r for r in prior if meaningful(r) and day(r["actual_end_date"]) < event_day]
    correction = max(completed, key=lambda r: (r["actual_end_date"], r["notification_id"]), default=None)
    context = "OTHER_AMBIGUOUS"
    if correction and 7 <= (event_day - day(correction["actual_end_date"])).days <= 120 and not any(r["notification_date"] > correction["actual_end_date"] for r in prior):
        context = "POST_MAINTENANCE_RECURRENCE"
    elif latest and not any(r["actual_end_date"] >= latest["notification_date"] for r in completed):
        context = "KNOWN_UNTREATED_DEFECT"
    elif not recent and not eligible:
        context = "INSUFFICIENT_HISTORY"
    elif not recent and eligible and not any(day(r["notification_date"]) == event_day for r in confirmed) and not any((event_day - day(r["actual_end_date"])).days <= LOOKBACK for r in completed):
        context = "NO_PRIOR_DETECTION"
    return context, recent, latest, correction, eligible


def analyze_losses(raw, enriched, campaigns):
    coverage_start = min(day(c["start_date"]) for c in campaigns)
    by_pair = defaultdict(list)
    for row in enriched:
        by_pair[row["asset_id"], row["failure_mode"]].append(row)
    result = []
    for source in raw:
        row = dict(source)
        row.update(dict.fromkeys(LOSS_ADDED, ""))
        event_day = datetime.fromisoformat(row["event_start_datetime"]).date()
        context, recent, latest, correction, eligible = loss_context(row["asset_id"], event_day, by_pair[row["asset_id"], row["failure_mode"]], coverage_start)
        row.update(history_coverage_eligible=flag(eligible), maintenance_context=context,
                   prior_confirmed_notification_count_180d=str(len(recent)))
        if latest:
            for field in ("notification_id", "notification_date", "responsible_discipline", "work_order_id", "closure_code", "action_type", "risk_class", "risk_sort_order"):
                row["latest_prior_" + field] = latest[field]
            row["days_from_latest_notification_to_loss"] = str((event_day - day(latest["notification_date"])).days)
        if correction:
            row.update(latest_completed_corrective_notification_id=correction["notification_id"],
                       latest_completed_corrective_date=correction["actual_end_date"],
                       days_from_corrective_completion_to_loss=str((event_day - day(correction["actual_end_date"])).days))
        result.append(row)
    return result


def loss_sum(rows):
    return sum((Decimal(r["production_loss_adt"]) for r in rows), Decimal(0))


def associations(rows):
    result = {}
    for context, prefix in [("KNOWN_UNTREATED_DEFECT", "known_untreated_loss"),
                            ("POST_MAINTENANCE_RECURRENCE", "post_maintenance_recurrence")]:
        selected = [r for r in rows if r["maintenance_context"] == context]
        count_key = "known_untreated_loss_event_count" if prefix == "known_untreated_loss" else prefix + "_event_count"
        loss_key = "known_untreated_loss_adt" if prefix == "known_untreated_loss" else prefix + "_loss_adt"
        result[count_key] = str(len(selected))
        result[loss_key] = fixed(loss_sum(selected))
    return result


def discipline_matrix(maintenance, losses):
    by_id = {r["notification_id"]: r for r in maintenance}
    allocated = defaultdict(list)
    for loss in losses:
        if loss["maintenance_context"] == "KNOWN_UNTREATED_DEFECT":
            owner = loss["latest_prior_responsible_discipline"]
        elif loss["maintenance_context"] == "POST_MAINTENANCE_RECURRENCE":
            owner = by_id[loss["latest_completed_corrective_notification_id"]]["responsible_discipline"]
        else:
            continue
        require(bool(owner), "Missing discipline on loss association")
        allocated[owner].append(loss)
    result = []
    for discipline in sorted({r["responsible_discipline"] for r in maintenance}):
        group = [r for r in maintenance if r["responsible_discipline"] == discipline]
        n = len(group)
        confirmed = sum(r["defect_confirmed"] == "TRUE" for r in group)
        row = dict.fromkeys(DISCIPLINE_FIELDS, "")
        row.update(responsible_discipline=discipline, notification_count=str(n),
                   confirmed_defect_count=str(confirmed), confirmed_defect_rate=rate(confirmed, n))
        metrics = [
            ("converted_to_order_count", "conversion_rate", lambda r: r["converted_to_order"] == "TRUE", n),
            ("confirmed_to_order_count", "confirmed_to_order_rate", lambda r: r["converted_to_order"] == "TRUE" and r["defect_confirmed"] == "TRUE", confirmed),
            ("closed_without_order_count", "closed_without_order_rate", lambda r: r["closed_without_order"] == "TRUE", n),
            ("confirmed_closed_without_order_count", "confirmed_closed_without_order_rate", lambda r: r["confirmed_closed_without_order"] == "TRUE", n),
            ("unconfirmed_closed_without_order_count", "unconfirmed_closed_without_order_rate", lambda r: r["unconfirmed_closed_without_order"] == "TRUE", n),
            ("recurrent_notification_count", "recurrence_rate", lambda r: r["recurrent_notification"] == "TRUE", n),
            ("reassigned_count", "reassignment_rate", lambda r: bool(r["reassigned_discipline"]), n),
        ]
        for count_field, rate_field, predicate, denominator in metrics:
            count = sum(predicate(r) for r in group)
            row[count_field], row[rate_field] = str(count), rate(count, denominator)
        row["active_backlog_count"] = str(sum(r["active_backlog"] == "TRUE" for r in group))
        row["r1_r3_backlog_count"] = str(sum(r["active_backlog"] == "TRUE" and r["risk_class"] in {"R1", "R2", "R3"} for r in group))
        row.update(associations(allocated[discipline]))
        result.append(row)
    return result


def rankings(maintenance, losses, assets):
    by_id = {r["asset_id"]: r for r in assets}
    locations = {r["functional_location"]: r for r in assets}
    tables = []
    for key, fields in [("asset_id", ASSET_FIELDS), ("functional_location", LOCATION_FIELDS)]:
        maintenance_groups, loss_groups = defaultdict(list), defaultdict(list)
        for row in maintenance:
            maintenance_groups[row[key]].append(row)
        for row in losses:
            if row[key]:
                loss_groups[row[key]].append(row)
        records = []
        for value in sorted(maintenance_groups.keys() | loss_groups.keys()):
            group, events = maintenance_groups[value], loss_groups[value]
            reference = by_id[value] if key == "asset_id" else locations[value]
            row = dict.fromkeys(fields, "")
            for field in ("asset_id", "functional_location", *MASTER_FIELDS):
                if field in row:
                    row[field] = reference[field]
            active = [r for r in group if r["active_backlog"] == "TRUE"]
            row.update(production_loss_event_count=str(len(events)), total_production_loss_adt=fixed(loss_sum(events)),
                       maintenance_notification_count=str(len(group)),
                       confirmed_defect_count=str(sum(r["defect_confirmed"] == "TRUE" for r in group)), active_backlog_count=str(len(active)))
            if key == "asset_id":
                row.update(average_loss_adt=fixed(loss_sum(events) / len(events)) if events else "0.00",
                           maximum_loss_adt=fixed(max((Decimal(e["production_loss_adt"]) for e in events), default=Decimal(0))),
                           recurrent_notification_count=str(sum(r["recurrent_notification"] == "TRUE" for r in group)))
                if active:
                    highest = min(active, key=lambda r: int(r["risk_sort_order"]))
                    row.update(highest_active_risk_class=highest["risk_class"], highest_active_risk_sort_order=highest["risk_sort_order"])
            row.update(associations(events))
            records.append(row)
        records.sort(key=lambda r: (-Decimal(r["total_production_loss_adt"]), -int(r["production_loss_event_count"]), r[key]))
        cumulative, total = Decimal(0), loss_sum(losses)
        for rank, row in enumerate(records, 1):
            row["bad_actor_rank" if key == "asset_id" else "location_rank"] = str(rank)
            if key == "functional_location":
                amount = Decimal(row["total_production_loss_adt"])
                cumulative += amount
                row.update(share_of_total_loss=rate(amount, total), cumulative_share_of_total_loss=rate(cumulative, total))
        tables.append(records)
    return tables


def backlog_key(row):
    return int(row["risk_sort_order"]), int(row["notification_priority"]), row["notification_date"], row["notification_id"]


def build(inputs):
    assets, matrix, maintenance, losses, campaigns = [inputs[name][1] for name in ("assets", "matrix", "maintenance", "losses", "campaigns")]
    enriched = enrich_maintenance(maintenance, assets, matrix)
    analyzed = analyze_losses(losses, enriched, campaigns)
    asset_ranking, location_ranking = rankings(enriched, analyzed, assets)
    backlog = [{k: r[k] for k in BACKLOG_FIELDS} for r in sorted(enriched, key=backlog_key) if r["active_backlog"] == "TRUE"]
    return {
        "maintenance_enriched.csv": (inputs["maintenance"][0] + MAINTENANCE_ADDED, enriched),
        "loss_event_analysis.csv": (inputs["losses"][0] + LOSS_ADDED, analyzed),
        "discipline_performance.csv": (DISCIPLINE_FIELDS, discipline_matrix(enriched, analyzed)),
        "bad_actor_ranking.csv": (ASSET_FIELDS, asset_ranking),
        "functional_location_ranking.csv": (LOCATION_FIELDS, location_ranking),
        "risk_backlog.csv": (BACKLOG_FIELDS, backlog),
    }


def validate(outputs, inputs):
    maintenance = outputs["maintenance_enriched.csv"][1]
    losses = outputs["loss_event_analysis.csv"][1]
    disciplines = outputs["discipline_performance.csv"][1]
    assets = outputs["bad_actor_ranking.csv"][1]
    locations = outputs["functional_location_ranking.csv"][1]
    backlog = outputs["risk_backlog.csv"][1]
    require(len(maintenance) == 1200 and len(losses) == 240, "Unexpected source cardinality")
    for source_name, enriched in [("maintenance", maintenance), ("losses", losses)]:
        fields, source = inputs[source_name]
        require([{k: r[k] for k in fields} for r in enriched] == source, "Raw field or source order changed")
    for fields, rows in outputs.values():
        require(len(set(fields)) == len(fields), "Duplicate output field")
        require(all(list(r) == fields for r in rows), "Output schema/order mismatch")
    master = {r["asset_id"]: r for r in inputs["assets"][1]}
    risk = {(r["asset_criticality"], r["notification_priority"]): r for r in inputs["matrix"][1]}
    by_id = {r["notification_id"]: r for r in maintenance}
    require(len(by_id) == 1200, "Duplicate notification")
    require(len({r["loss_event_id"] for r in losses}) == 240, "Duplicate loss")
    for row in maintenance:
        require(all(row[k] == master[row["asset_id"]][k] for k in ["functional_location", *MASTER_FIELDS]), "Invalid master enrichment")
        cell = risk[row["asset_criticality"], row["notification_priority"]]
        require(all(row[k] == cell[k] for k in ("risk_class", "risk_sort_order", "defect_status")), "Risk mapping differs from reference")
        require(row["maintenance_response_state"] in STATES, "Invalid response state")
        require(int(row["notification_age_days"]) >= 0, "Post-snapshot notification")
        for k in ("days_to_order", "execution_lead_days", "days_since_previous_same_defect"):
            require(not row[k] or int(row[k]) >= 0, "Negative elapsed time")
    for loss in losses:
        require(loss["maintenance_context"] in CONTEXTS, "Missing/invalid maintenance context")
        event_day = datetime.fromisoformat(loss["event_start_datetime"]).date()
        for key in ("latest_prior_notification_id", "latest_completed_corrective_notification_id"):
            if loss[key]:
                prior = by_id[loss[key]]
                require(prior["asset_id"] == loss["asset_id"] and prior["failure_mode"] == loss["failure_mode"] and prior["defect_confirmed"] == "TRUE", "Invalid exact-match link")
                require(day(prior["notification_date"]) < event_day, "Same-day/future notification treated as prior")
                if key == "latest_completed_corrective_notification_id":
                    require(meaningful(prior) and day(prior["actual_end_date"]) < event_day, "Future/noncorrective completion linked")
        if loss["maintenance_context"] == "KNOWN_UNTREATED_DEFECT":
            require(loss["latest_prior_notification_id"] and 1 <= int(loss["days_from_latest_notification_to_loss"]) <= LOOKBACK, "Invalid unresolved-defect window")
        if loss["maintenance_context"] == "POST_MAINTENANCE_RECURRENCE":
            require(7 <= int(loss["days_from_corrective_completion_to_loss"]) <= 120, "Invalid post-action window")
    expected_backlog = sorted([r for r in maintenance if r["active_backlog"] == "TRUE"], key=backlog_key)
    require(backlog == [{k: r[k] for k in BACKLOG_FIELDS} for r in expected_backlog], "Backlog membership/risk ordering mismatch")
    require(sum(int(r["notification_count"]) for r in disciplines) == 1200, "Discipline counts do not reconcile")
    denominators = {
        "confirmed_defect_rate": ("confirmed_defect_count", "notification_count"),
        "conversion_rate": ("converted_to_order_count", "notification_count"),
        "confirmed_to_order_rate": ("confirmed_to_order_count", "confirmed_defect_count"),
        "closed_without_order_rate": ("closed_without_order_count", "notification_count"),
        "confirmed_closed_without_order_rate": ("confirmed_closed_without_order_count", "notification_count"),
        "unconfirmed_closed_without_order_rate": ("unconfirmed_closed_without_order_count", "notification_count"),
        "recurrence_rate": ("recurrent_notification_count", "notification_count"),
        "reassignment_rate": ("reassigned_count", "notification_count"),
    }
    for row in disciplines:
        for field, (numerator, denominator) in denominators.items():
            require(row[field] == rate(int(row[numerator]), int(row[denominator])), "Incorrect rate denominator")
    for context, count_field, loss_field in [
        ("KNOWN_UNTREATED_DEFECT", "known_untreated_loss_event_count", "known_untreated_loss_adt"),
        ("POST_MAINTENANCE_RECURRENCE", "post_maintenance_recurrence_event_count", "post_maintenance_recurrence_loss_adt"),
    ]:
        selected = [r for r in losses if r["maintenance_context"] == context]
        for table in (disciplines, assets, locations):
            require(sum(int(r[count_field]) for r in table) == len(selected), "Associated event duplicated or omitted")
            require(sum(Decimal(r[loss_field]) for r in table) == loss_sum(selected), "Associated loss duplicated or omitted")
    require(sum(Decimal(r["total_production_loss_adt"]) for r in assets) == loss_sum([r for r in losses if r["asset_id"]]), "Asset loss total mismatch")
    require(sum(Decimal(r["total_production_loss_adt"]) for r in locations) == loss_sum(losses), "Location loss total mismatch")
    require(locations[-1]["cumulative_share_of_total_loss"] == "1.000000", "Pareto does not reach total")
    for table, key, rank_key in [(assets, "asset_id", "bad_actor_rank"), (locations, "functional_location", "location_rank")]:
        require(table == sorted(table, key=lambda r: (-Decimal(r["total_production_loss_adt"]), -int(r["production_loss_event_count"]), r[key])), "Ranking order invalid")
        require([r[rank_key] for r in table] == list(map(str, range(1, len(table) + 1))), "Nonsequential ranks")
    for aid, mode in [("P-DIG-CIR-01", "PUMP_BEARING_VIBRATION"), ("HPU-DRY-HYD-01", "HYD_PRESS_INSTABILITY"),
                      ("FV-CAU-WLC-01", "VALVE_STICTION"), ("P-RB-BLF-01", "PUMP_BEARING_VIBRATION")]:
        require(any(r["asset_id"] == aid and r["failure_mode"] == mode for r in maintenance), "Seeded maintenance missing")
        require(any(r["asset_id"] == aid and r["failure_mode"] == mode for r in losses), "Seeded loss history missing")
    positive = next(r for r in assets if r["asset_id"] == "FAN-RB-AIR-01")
    require(positive["production_loss_event_count"] == "0" and any(r["asset_id"] == "FAN-RB-AIR-01" and meaningful(r) for r in maintenance), "Positive control changed")


def report(outputs):
    maintenance, losses, disciplines, assets, locations, backlog = [outputs[name + ".csv"][1] for name in (
        "maintenance_enriched", "loss_event_analysis", "discipline_performance", "bad_actor_ranking", "functional_location_ranking", "risk_backlog")]
    count = lambda field: sum(r[field] == "TRUE" for r in maintenance)
    print(f"QA PASS | AS_OF_DATE {AS_OF_DATE} | notifications {len(maintenance)} | conversion {count('converted_to_order')/len(maintenance):.2%}")
    print(f"Closed without order: confirmed {count('confirmed_closed_without_order')}; unconfirmed {count('unconfirmed_closed_without_order')}")
    print(f"Recurrence {count('recurrent_notification')} ({count('recurrent_notification')/len(maintenance):.2%}); active backlog {len(backlog)}")
    print("Backlog by formal risk: " + "; ".join(f"R{i}={sum(r['risk_class'] == 'R'+str(i) for r in backlog)}" for i in range(1, 10)))
    attributed = loss_sum([r for r in losses if r["asset_id"]])
    expected = {"NO_PRIOR_DETECTION": 87, "KNOWN_UNTREATED_DEFECT": 63, "POST_MAINTENANCE_RECURRENCE": 24, "SYSTEM_PROCESS_EVENT": 48}
    print(f"Loss contexts | total {loss_sum(losses):,.2f} ADt | asset-attributed denominator {attributed:,.2f} ADt")
    for context in CONTEXTS:
        group = [r for r in losses if r["maintenance_context"] == context]
        amount = loss_sum(group)
        print(f"  {context}: {len(group)}; {amount:,.2f} ADt" + (f"; {amount/attributed:.2%} of asset loss" if context in list(CONTEXTS)[:3] else ""))
        if context in expected and len(group) != expected[context]:
            print(f"  REGRESSION DIFFERENCE: expected {expected[context]}, observed {len(group)}. Review coverage/temporal rules; counts were not forced.")
    if all(sum(r["maintenance_context"] == k for r in losses) == v for k, v in expected.items()):
        print("Generator QA regression: exact agreement (87 / 63 / 24 / 48).")
    print("Full discipline matrix (rates are fractions):")
    print(encode(DISCIPLINE_FIELDS, disciplines).decode().strip())
    for metric in ("confirmed_closed_without_order_rate", "unconfirmed_closed_without_order_rate", "recurrence_rate", "known_untreated_loss_adt"):
        largest = max(Decimal(r[metric]) for r in disciplines)
        leaders = [r["responsible_discipline"] for r in disciplines if Decimal(r[metric]) == largest]
        print(f"Highest {metric}: {', '.join(leaders)} = {largest}")
    for title, table, key in [("Top 10 assets", assets, "asset_id"), ("Top 10 locations", locations, "functional_location")]:
        print(title + " | events | ADt")
        for row in table[:10]:
            print(f"  {row[key]} | {row['production_loss_event_count']} | {row['total_production_loss_adt']}")
    print("Seeded technical histories | notifications | loss events | ADt | contexts")
    for aid, mode in [("P-DIG-CIR-01", "PUMP_BEARING_VIBRATION"), ("HPU-DRY-HYD-01", "HYD_PRESS_INSTABILITY"),
                      ("FV-CAU-WLC-01", "VALVE_STICTION"), ("P-RB-BLF-01", "PUMP_BEARING_VIBRATION")]:
        group = [r for r in losses if r["asset_id"] == aid and r["failure_mode"] == mode]
        n = sum(r["asset_id"] == aid and r["failure_mode"] == mode for r in maintenance)
        print(f"  {aid} / {mode} | {n} | {len(group)} | {loss_sum(group)} | {dict(Counter(r['maintenance_context'] for r in group))}")
    print("Top 15 backlog | notification | asset | risk | priority | age days | replans")
    for r in backlog[:15]:
        print(f"  {r['notification_id']} | {r['asset_id']} | {r['risk_class']} | {r['notification_priority']} | {r['notification_age_days']} | {r['replanning_count'] or 'blank'}")
    print("FAN-RB-AIR-01: completed corrective intervention retained, zero production-loss events.")


def main():
    sources = {"assets": "data/reference/system_asset_master.csv", "matrix": "data/reference/risk_matrix.csv",
               "maintenance": "data/raw/maintenance_history.csv", "losses": "data/raw/production_loss_events.csv",
               "campaigns": "data/raw/campaign_summary.csv"}
    protected = {p: p.read_bytes() for folder in (ROOT / "data/raw", ROOT / "data/reference") for p in folder.glob("*.csv")}
    inputs = {name: read_csv(ROOT / path) for name, path in sources.items()}
    outputs = build(inputs)
    validate(outputs, inputs)
    rebuilt = build(inputs)
    require(all(encode(*table) == encode(*rebuilt[name]) for name, table in outputs.items()), "Nondeterministic analytical build")
    directory = ROOT / "data/processed"
    directory.mkdir(parents=True, exist_ok=True)
    for name, table in outputs.items():
        (directory / name).write_bytes(encode(*table))
    saved = {name: read_csv(directory / name) for name in outputs}
    validate(saved, inputs)
    require(all(p.read_bytes() == original for p, original in protected.items()), "Raw/reference CSV bytes changed")
    report(saved)
    print("Saved-output validation and deterministic regeneration PASS; all raw/reference CSV bytes unchanged.")


if __name__ == "__main__":
    main()
