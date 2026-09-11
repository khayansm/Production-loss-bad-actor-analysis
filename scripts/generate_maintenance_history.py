"""Rebuild the synthetic maintenance extract with Python 3 (standard library only).

Run: python scripts/generate_maintenance_history.py
Snapshot: 2025-11-15. Dates are calendar dates; planned dates are the latest plan,
not a schedule audit trail. Labor/cost are incurred amounts, including triage.
repeat_failure_code is the reported technical code family on every notification,
including first reports; recurrence flags are deliberately left to later analysis.
Notification closure covers administrative disposition, not proof of correction.
Growth in campaign counts models route coverage, not a changing failure rate.
"""

import csv
import hashlib
import io
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260911
AS_OF = date(2025, 11, 15)
FIELDS = (
    "notification_id work_order_id functional_location asset_id notification_date "
    "notification_priority notification_source detected_by_team inspection_route_type "
    "symptom failure_mode repeat_failure_code responsible_discipline reassigned_discipline "
    "planner_group notification_status order_created_date order_type order_status "
    "planned_start_date planned_finish_date actual_start_date actual_end_date "
    "replanning_count closure_code closure_text action_type action_text defect_confirmed "
    "labor_hours maintenance_cost linked_loss_event_id"
).split()
ORDER_FIELDS = (
    "order_created_date order_type order_status planned_start_date planned_finish_date "
    "actual_start_date actual_end_date replanning_count"
).split()
CAMPAIGN_FIELDS = (
    "campaign_id start_date end_date planned_shutdown_start planned_shutdown_end notes"
).split()
CAMPAIGNS = [
    dict(zip(CAMPAIGN_FIELDS, values)) for values in [
        ("C1", "2023-01-01", "2023-11-15", "2023-11-16", "2023-11-30", "Initial notification coverage."),
        ("C2", "2023-12-01", "2024-11-15", "2024-11-16", "2024-11-30", "Expanded route coverage and notification activity."),
        ("C3", "2024-12-01", "2025-11-15", "2025-11-16", "2025-11-30", "Broader early detection coverage; extract as of 2025-11-15."),
    ]
]
CONVERSION = {"Mechanical": .78, "Electrical": .90, "Instrumentation": .66,
              "Valves": .43, "Condition Monitoring": .83, "Lubrication": .88,
              "Hydraulics": .77, "Automation": .68}
# Minimum gap after a completed corrective action, in days. Weak treatments get
# shorter gaps. No-defect closures have a separate 120-day guard below.
COOLDOWN = {"Mechanical": 100, "Electrical": 240, "Instrumentation": 100,
            "Valves": 40, "Condition Monitoring": 180, "Lubrication": 240,
            "Hydraulics": 45, "Automation": 110}
SOURCES = ["Operator Route", "Maintenance Sensory Route", "Condition Monitoring",
           "Process Alarm", "Planned Inspection", "Operator Report", "Breakdown / Corrective"]
ROUTES = {"Operator Route": "Sensory Route", "Maintenance Sensory Route": "Sensory Route",
          "Condition Monitoring": "Predictive Route", "Process Alarm": "Process / Control Monitoring",
          "Planned Inspection": "Planned Inspection"}
# Technical vocabulary: observed symptom, compatible treatment, typical crew hours,
# and synthetic parts/service BRL before the labor component.
MODES = {
    "PUMP_BEARING_VIBRATION": ("Elevated vibration at pump bearing housing", "Bearing replacement", 16, 9000),
    "SEAL_LEAKAGE": ("Leakage at shaft seal", "Seal replacement", 10, 6000),
    "CAVITATION": ("Crackling noise and unstable suction pressure", "Cleaning", 5, 600),
    "LOW_FLOW": ("Delivered flow below expected operating range", "Cleaning", 8, 1200),
    "BEARING_TEMPERATURE": ("Bearing temperature trending above baseline", "Bearing replacement", 14, 8000),
    "MOTOR_BEARING_VIBRATION": ("Motor bearing vibration above baseline", "Bearing replacement", 14, 7000),
    "MOTOR_OVERHEATING": ("Motor temperature rising at normal load", "Cleaning", 6, 900),
    "INSULATION_DEGRADATION": ("Insulation test trending below reference", "Component replacement", 22, 18000),
    "TERMINAL_HEATING": ("Localized heating at electrical connection", "Tightening", 4, 400),
    "VALVE_STICTION": ("Valve travel sticks during small command changes", "Valve overhaul", 18, 12000),
    "ACTUATOR_LEAKAGE": ("Actuator supply pressure decays while held", "Seal replacement", 8, 3500),
    "POSITIONER_DEVIATION": ("Valve feedback differs from demanded position", "Calibration", 4, 700),
    "EXTERNAL_LEAKAGE": ("Visible leakage at valve packing", "Seal replacement", 6, 2300),
    "SIGNAL_DRIFT": ("Indicated value drifts from independent reference", "Calibration", 4, 600),
    "INTERMITTENT_SIGNAL": ("Intermittent signal dropout at stable process conditions", "Instrument replacement", 6, 4000),
    "CALIBRATION_DEVIATION": ("Measured output outside calibration tolerance", "Calibration", 4, 600),
    "IMPULSE_LINE_RESTRICTION": ("Pressure response delayed during process change", "Cleaning", 5, 600),
    "FAN_BEARING_VIBRATION": ("Fan bearing vibration trending above baseline", "Bearing replacement", 20, 13000),
    "IMBALANCE": ("Rotating assembly shows dominant once-per-revolution vibration", "Adjustment", 10, 3500),
    "HYD_PRESS_INSTABILITY": ("Hydraulic header pressure oscillates under steady demand", "Component replacement", 14, 9500),
    "HYD_INTERNAL_LEAKAGE": ("Hydraulic pressure decays with no external leak", "Seal replacement", 12, 5000),
    "OIL_CONTAMINATION": ("Oil sample shows elevated contamination", "Lubrication", 6, 2200),
    "LOW_LUBE_PRESSURE": ("Lubrication supply pressure below normal range", "Cleaning", 6, 1100),
    "LOW_LUBE_LEVEL": ("Lubricant level below normal mark", "Lubrication", 2, 700),
    "GEARBOX_VIBRATION": ("Gear mesh vibration increased from baseline", "Component replacement", 24, 20000),
    "GEARBOX_OVERHEATING": ("Gearbox oil temperature above normal trend", "Lubrication", 6, 2000),
    "OIL_DEGRADATION": ("Oil condition test indicates degraded lubricant", "Lubrication", 6, 2500),
    "CONTROL_SEQUENCE_DEVIATION": ("Control sequence response differs from approved logic", "Control logic correction", 8, 1200),
    "MECHANICAL_BINDING": ("Mechanism travel is uneven with elevated resistance", "Adjustment", 8, 1700),
    "PROCESS_RESTRICTION": ("Process differential pressure above normal operating range", "Cleaning", 10, 1700),
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def csv_bytes(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def modes_for(asset, discipline):
    kind = asset["asset_type"]
    if discipline == "Lubrication":
        return ["OIL_CONTAMINATION", "LOW_LUBE_LEVEL", "OIL_DEGRADATION"]
    if discipline == "Automation":
        return ["CONTROL_SEQUENCE_DEVIATION", "INTERMITTENT_SIGNAL"]
    if kind.startswith("Hydraulic"):
        return ["HYD_PRESS_INSTABILITY", "HYD_INTERNAL_LEAKAGE", "OIL_CONTAMINATION"]
    if kind.startswith("Lubrication"):
        return ["LOW_LUBE_PRESSURE", "LOW_LUBE_LEVEL", "OIL_CONTAMINATION"]
    if kind in ("Pump", "Dosing Pump"):
        return ["PUMP_BEARING_VIBRATION", "SEAL_LEAKAGE", "CAVITATION", "LOW_FLOW", "BEARING_TEMPERATURE"]
    if kind == "Motor":
        return ["MOTOR_BEARING_VIBRATION", "MOTOR_OVERHEATING", "INSULATION_DEGRADATION", "TERMINAL_HEATING"]
    if kind in ("Control Valve", "On/Off Valve"):
        return (["VALVE_STICTION", "ACTUATOR_LEAKAGE", "EXTERNAL_LEAKAGE"]
                + (["POSITIONER_DEVIATION"] if kind == "Control Valve" else []))
    if "Transmitter" in kind or "Switch" in kind or kind == "Encoder":
        return ["SIGNAL_DRIFT", "INTERMITTENT_SIGNAL", "CALIBRATION_DEVIATION"] + (
            ["IMPULSE_LINE_RESTRICTION"] if "Pressure Transmitter" in kind else [])
    if kind == "Fan":
        return ["FAN_BEARING_VIBRATION", "IMBALANCE", "BEARING_TEMPERATURE"]
    if kind == "Gearbox":
        return ["GEARBOX_VIBRATION", "GEARBOX_OVERHEATING", "OIL_DEGRADATION"]
    if asset["primary_discipline"] == "Electrical":
        return ["TERMINAL_HEATING", "INSULATION_DEGRADATION", "CONTROL_SEQUENCE_DEVIATION"]
    if kind in ("Drive", "Clarifier Drive", "Press Roll", "Agitator", "Compressor"):
        return ["BEARING_TEMPERATURE", "IMBALANCE", "MECHANICAL_BINDING"]
    return ["MECHANICAL_BINDING", "PROCESS_RESTRICTION"]


def make_row(rng, asset, day, discipline, mode, **overrides):
    row = dict.fromkeys(FIELDS, "")
    possible = asset["possible_disciplines"].split(";")
    weights = [21, 22, 18 if "Condition Monitoring" in possible else 0, 10, 13, 13, 3]
    source = overrides.get("source", rng.choices(SOURCES, weights)[0])
    # Higher early-route coverage in later campaigns changes detection mix only.
    priority = rng.choices([1, 2, 3], [12, 38, 50] if asset["asset_criticality"] == "A" else [7, 31, 62])[0]
    if source == "Condition Monitoring":
        priority = rng.choices([1, 2, 3], [3, 27, 70])[0]
    if source == "Breakdown / Corrective":
        priority = 1
    priority = overrides.get("priority", priority)
    confirmed = rng.random() < (.96 if source == "Condition Monitoring" or discipline == "Condition Monitoring" else .84)
    if source == "Maintenance Sensory Route":
        confirmed = rng.random() < .73
    if source == "Breakdown / Corrective":
        confirmed = True
    confirmed = overrides.get("confirmed", confirmed)
    reassigned = ""
    alternatives = [d for d in possible if d != discipline and d != "Condition Monitoring"]
    if alternatives and rng.random() < .115:
        reassigned = rng.choice(alternatives)
    reassigned = overrides.get("reassigned", reassigned)
    probability = CONVERSION[discipline] + {1: .17, 2: .04, 3: -.07}[priority]
    probability += .03 if asset["asset_criticality"] == "A" else -.02
    if not confirmed:
        probability = .12
    converted = overrides.get("converted", rng.random() < min(.98, probability))
    suffix = {"Operator Route": "Operations", "Operator Report": "Operations",
              "Process Alarm": "Control Room", "Breakdown / Corrective": "Operations",
              "Maintenance Sensory Route": "Maintenance Route A",
              "Condition Monitoring": "Condition Monitoring", "Planned Inspection": "Inspection"}[source]
    row.update(functional_location=asset["functional_location"], asset_id=asset["asset_id"],
               notification_date=day.isoformat(), notification_priority=str(priority),
               notification_source=source, detected_by_team=asset["area"] + " - " + suffix,
               inspection_route_type=ROUTES.get(source, ""), symptom=MODES[mode][0] + ".",
               failure_mode=mode, repeat_failure_code=mode, responsible_discipline=discipline,
               reassigned_discipline=reassigned, planner_group=asset["functional_location"].split("-")[2] + "-" + (reassigned or discipline).upper().replace(" ", "_"),
               defect_confirmed=str(confirmed).upper())
    hours, cost = rng.uniform(.3, 2), rng.uniform(30, 100)
    closure = ""
    if converted:
        created = day + timedelta(days=rng.randint(0, min(5, (AS_OF - day).days)))
        replan = rng.choices(range(7), [66, 22, 7, 3, 1, .7, .3] if priority == 1 else
                             ([48, 27, 14, 7, 2, 1, 1] if priority == 2 else [32, 29, 20, 11, 4, 3, 1]))[0]
        replan = overrides.get("replan", replan)
        delay = {1: rng.randint(0, 3), 2: rng.randint(3, 18), 3: rng.randint(10, 45)}[priority]
        planned = created + timedelta(days=delay + replan * rng.randint(7, 18))
        finish = planned + timedelta(days=rng.randint(0, 2))
        status = "Completed" if finish <= AS_OF else rng.choice(["Created", "Released", "Scheduled"])
        if rng.random() < .035:
            status = "Cancelled"
        status = overrides.get("status", status)
        if status == "Completed":
            finish = min(finish, AS_OF)
            planned = min(planned, finish)
        row.update(work_order_id="pending", order_created_date=created.isoformat(),
                   order_type="CM01" if priority == 1 else "PM02",
                   order_status=status, replanning_count=str(replan),
                   planned_start_date=planned.isoformat(), planned_finish_date=finish.isoformat())
        if status == "Completed":
            row.update(actual_start_date=planned.isoformat(), actual_end_date=finish.isoformat(), notification_status="Closed")
            weak = rng.random() < {"Valves": .30, "Hydraulics": .20}.get(discipline, .04)
            weak = overrides.get("weak", weak)
            if confirmed and not weak:
                action, typical_hours, parts = MODES[mode][1:]
                factor = rng.uniform(.65, 1.5)
                hours, cost = typical_hours * factor, parts * factor
                row.update(action_type=action, action_text=f"{action} performed; post-work functional check within tolerance.")
                closure = "WORK_COMPLETED"
            else:
                row.update(action_type="Inspection only", action_text="Inspected and recorded readings; no component correction performed.")
                closure = "MONITOR_CONDITION" if confirmed else "NO_DEFECT_FOUND"
        elif status == "Cancelled":
            row["notification_status"] = "Closed"
            closure = "CANCELLED"
        else:
            row["notification_status"] = "In Progress"
    else:
        is_open = (AS_OF - day).days < 75 and rng.random() < .4
        is_open = overrides.get("open", is_open)
        row["notification_status"] = "Open" if is_open else "Closed"
        if not is_open:
            closure = rng.choice(["MONITOR_CONDITION", "NO_ACTION_REQUIRED"]) if confirmed else rng.choice(["NO_DEFECT_FOUND", "OPERATING_CONDITION", "NO_ACTION_REQUIRED"])
            row.update(action_type="Inspection only", action_text="Field inspection completed; no corrective maintenance performed.")
    closure = overrides.get("closure", closure)
    texts = {"WORK_COMPLETED": "Corrective scope executed and checked.",
             "MONITOR_CONDITION": "Condition recorded; continue observation without corrective work.",
             "NO_DEFECT_FOUND": "Inspection could not confirm the reported abnormality.",
             "OPERATING_CONDITION": "Observed response is within the current operating envelope.",
             "NO_ACTION_REQUIRED": "Notification dispositioned without corrective scope.",
             "CANCELLED": "Order cancelled after scope review; no execution recorded."}
    row.update(closure_code=closure, closure_text=texts.get(closure, ""),
               labor_hours=f"{hours:.2f}", maintenance_cost=f"{cost + hours * 145:.2f}")
    return row


def generate(assets):
    rng = random.Random(SEED)
    by_id = {a["asset_id"]: a for a in assets}
    rows = []
    # Explicit multi-campaign histories are reserved from background sampling.
    chains = [("P-DIG-CIR-01", "Mechanical", "PUMP_BEARING_VIBRATION"),
              ("HPU-DRY-HYD-01", "Hydraulics", "HYD_PRESS_INSTABILITY"),
              ("FV-CAU-WLC-01", "Valves", "VALVE_STICTION")]
    reserved = {item[0] for item in chains} | {"FAN-RB-AIR-01"}
    for aid, discipline, mode in chains:
        asset = by_id[aid]
        for campaign in CAMPAIGNS:
            start = date.fromisoformat(campaign["start_date"])
            for index, offset in enumerate([30, 120, 260]):
                received = "Instrumentation" if discipline == "Hydraulics" and index == 1 else discipline
                row = make_row(rng, asset, start + timedelta(days=offset), received, mode,
                               source=["Operator Report", "Planned Inspection", "Process Alarm"][index],
                               priority=[3, 2, 1][index], confirmed=True,
                               converted=(discipline != "Valves" or index == 2),
                               reassigned="Hydraulics" if received == "Instrumentation" else "",
                               replan=4 if index == 2 else 2, weak=True, open=False)
                rows.append(row)
    rows.append(make_row(rng, by_id["FAN-RB-AIR-01"], date(2024, 3, 10), "Condition Monitoring",
                         "FAN_BEARING_VIBRATION", source="Condition Monitoring", priority=3,
                         confirmed=True, converted=True, status="Completed", replan=0, weak=False))
    training = [a for a in assets if a["area"] == "Washing & Screening" and a["asset_criticality"] in ("B", "C")]
    # Distributed across assets and campaigns; no diagnostic answer in CSV text.
    for campaign in CAMPAIGNS:
        start = date.fromisoformat(campaign["start_date"])
        for asset in training:
            day = start + timedelta(days=rng.randint(45, 85))
            rows.append(make_row(rng, asset, day, asset["primary_discipline"],
                                 rng.choice(modes_for(asset, asset["primary_discipline"])),
                                 source="Maintenance Sensory Route", priority=3, confirmed=False,
                                 converted=False, open=False, closure=rng.choice(["NO_DEFECT_FOUND", "OPERATING_CONDITION"])))
    # Explicit concerning backlog includes both converted and unconverted A/1 cases.
    for aid, discipline, mode in chains:
        rows.append(make_row(rng, by_id[aid], date(2025, 10, 1), discipline, mode,
                             priority=1, confirmed=True, converted=True, status="Scheduled", replan=5))
        rows.append(make_row(rng, by_id[aid], date(2025, 11, 10), discipline, mode,
                             priority=1, confirmed=True, converted=False, open=True))
    candidates = [a for a in assets if a["asset_id"] not in reserved]
    # Accept background histories in date order so prior dispositions affect recurrence.
    for ci, (campaign, count) in enumerate(zip(CAMPAIGNS, [360, 400, 440])):
        start, end = [date.fromisoformat(campaign[k]) for k in ("start_date", "end_date")]
        needed = count - sum(start.isoformat() <= r["notification_date"] <= end.isoformat() for r in rows)
        days = sorted(start + timedelta(days=rng.randint(0, (end - start).days)) for _ in range(needed))
        for day in days:
            for attempt in range(10000):
                asset = rng.choice(candidates)
                possible = asset["possible_disciplines"].split(";")
                discipline = rng.choices(possible, [5 if d == asset["primary_discipline"] else 1.5 for d in possible])[0]
                mode = rng.choice(modes_for(asset, discipline))
                nearby = [r for r in rows if r["asset_id"] == asset["asset_id"] and r["failure_mode"] == mode]
                blocked = False
                for prior in nearby:
                    prior_day = date.fromisoformat(prior["notification_date"])
                    if prior["defect_confirmed"] == "FALSE" and abs((day - prior_day).days) < 120:
                        blocked = True
                    if prior_day <= day:
                        gap = 30
                        if prior["closure_code"] == "WORK_COMPLETED":
                            gap = COOLDOWN[prior["responsible_discipline"]]
                        elif prior["responsible_discipline"] in ("Valves", "Hydraulics"):
                            gap = 18
                        anchor = date.fromisoformat(prior["actual_end_date"] or prior["notification_date"])
                        if (day - anchor).days < gap:
                            blocked = True
                if blocked:
                    continue
                opts = {}
                if ci and rng.random() < .10 * ci:
                    opts["source"] = "Condition Monitoring" if "Condition Monitoring" in possible else "Planned Inspection"
                row = make_row(rng, asset, day, discipline, mode, **opts)
                # Also guard newly generated false reports against either side of seeded rows.
                if row["defect_confirmed"] == "FALSE" and any(abs((day - date.fromisoformat(p["notification_date"])).days) < 120 for p in nearby):
                    continue
                rows.append(row)
                break
            else:
                raise RuntimeError("Unable to sample a compatible background history")
    rows.sort(key=lambda r: (r["notification_date"], r["asset_id"], r["failure_mode"]))
    order_number = 0
    for number, row in enumerate(rows, 1):
        row["notification_id"] = f"N{number:07d}"
        if row["work_order_id"]:
            order_number += 1
            row["work_order_id"] = f"WO{order_number:07d}"
    return rows


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(rows, assets, campaigns):
    require(len(rows) == 1200, "Expected 1,200 records")
    require(campaigns == CAMPAIGNS, "Campaign dates/schema changed")
    by_id = {a["asset_id"]: a for a in assets}
    require(len(by_id) == len(assets), "Asset master contains duplicate IDs")
    require(len({r["notification_id"] for r in rows}) == len(rows), "Duplicate notification ID")
    orders = [r for r in rows if r["work_order_id"]]
    require(len({r["work_order_id"] for r in orders}) == len(orders), "Duplicate work order ID")
    for row in rows:
        tag = row["notification_id"]
        require(list(row) == FIELDS, f"{tag}: schema mismatch")
        require(row["asset_id"] in by_id, f"{tag}: unknown asset")
        asset = by_id[row["asset_id"]]
        require(row["functional_location"] == asset["functional_location"], f"{tag}: asset/location mismatch")
        require(row["notification_priority"] in ("1", "2", "3"), f"{tag}: invalid priority")
        require(row["defect_confirmed"] in ("TRUE", "FALSE"), f"{tag}: invalid confirmation")
        require(row["responsible_discipline"] in asset["possible_disciplines"].split(";"), f"{tag}: invalid discipline")
        require(not row["reassigned_discipline"] or (row["reassigned_discipline"] in asset["possible_disciplines"].split(";") and row["reassigned_discipline"] != row["responsible_discipline"]), f"{tag}: invalid reassignment")
        require(not row["linked_loss_event_id"], f"{tag}: loss link populated")
        require(row["failure_mode"] in modes_for(asset, row["responsible_discipline"]), f"{tag}: incompatible failure mode")
        require(row["repeat_failure_code"] == row["failure_mode"], f"{tag}: invalid reported code family")
        require(row["action_type"] in ("", "Inspection only", MODES[row["failure_mode"]][1]), f"{tag}: incompatible action")
        require(float(row["labor_hours"]) >= 0 and float(row["maintenance_cost"]) >= 0, f"{tag}: invalid effort/cost")
        dates = {key: date.fromisoformat(value) for key, value in row.items() if key.endswith("_date") and value}
        day = dates["notification_date"]
        require(day <= AS_OF, f"{tag}: future notification")
        require(any(c["start_date"] <= day.isoformat() <= c["end_date"] for c in campaigns), f"{tag}: outside campaign")
        require(row["inspection_route_type"] == ROUTES.get(row["notification_source"], ""), f"{tag}: source/route mismatch")
        require(row["detected_by_team"].startswith(asset["area"] + " - "), f"{tag}: team area mismatch")
        if row["notification_source"] == "Breakdown / Corrective":
            require(row["notification_priority"] == "1" and row["defect_confirmed"] == "TRUE", f"{tag}: breakdown mismatch")
        if not row["work_order_id"]:
            require(all(not row[k] for k in ORDER_FIELDS), f"{tag}: orphan order fields")
        else:
            require(all(row[k] for k in ORDER_FIELDS if k not in ("actual_start_date", "actual_end_date")), f"{tag}: missing order details")
            require(day <= dates["order_created_date"] <= AS_OF, f"{tag}: invalid creation date")
            require(dates["order_created_date"] <= dates["planned_start_date"] <= dates["planned_finish_date"], f"{tag}: invalid plan dates")
            require(row["replanning_count"] in list(map(str, range(7))), f"{tag}: invalid replanning")
            require(row["order_status"] in ("Created", "Released", "Scheduled", "Completed", "Cancelled"), f"{tag}: invalid order status")
            if row["order_status"] == "Completed":
                require(row["actual_start_date"] and row["actual_end_date"], f"{tag}: missing execution")
                require(dates["order_created_date"] <= dates["actual_start_date"] <= dates["actual_end_date"] <= AS_OF, f"{tag}: invalid actual dates")
                require(row["notification_status"] == "Closed" and row["action_type"], f"{tag}: missing completion disposition")
            else:
                require(not row["actual_start_date"] and not row["actual_end_date"] and not row["action_type"], f"{tag}: misleading execution")
        closed = row["notification_status"] == "Closed"
        require(closed == bool(row["closure_code"]) == bool(row["closure_text"]), f"{tag}: closure/status mismatch")
        require(not any(word in " ".join(row.values()).lower() for word in ("painting", "coating", "cosmetic", "preservation", "r10")), f"{tag}: excluded subject")
    require(.55 <= len(orders) / len(rows) <= .65, "Conversion outside target")
    counts = Counter(r["notification_priority"] for r in rows)
    for priority, low, high in [("1", .10, .15), ("2", .25, .35), ("3", .50, .60)]:
        require(low <= counts[priority] / len(rows) <= high, "Priority distribution outside target")
    require(.08 <= sum(bool(r["reassigned_discipline"]) for r in rows) / len(rows) <= .15, "Reassignment outside target")
    for campaign, count in zip(campaigns, [360, 400, 440]):
        require(sum(campaign["start_date"] <= r["notification_date"] <= campaign["end_date"] for r in rows) == count, "Campaign count mismatch")
    require(sum(r["order_status"] == "Completed" for r in orders) > .7 * len(orders), "Too few historical completions")
    rate = lambda group: sum(bool(r["work_order_id"]) for r in group) / len(group)
    groups = {d: [r for r in rows if r["responsible_discipline"] == d] for d in CONVERSION}
    require(rate(groups["Valves"]) + .15 < min(rate(groups["Electrical"]), rate(groups["Lubrication"])), "Missing discipline conversion signal")
    require(rate([r for r in rows if r["notification_priority"] == "1"]) > rate([r for r in rows if r["notification_priority"] == "3"]), "Missing priority conversion signal")
    require(rate([r for r in rows if r["defect_confirmed"] == "TRUE"]) > rate([r for r in rows if r["defect_confirmed"] == "FALSE"]), "Missing confirmation conversion signal")
    # Guard the controlled positive example and the training pattern from rapid repeats.
    positive = [r for r in rows if r["asset_id"] == "FAN-RB-AIR-01"]
    require(len(positive) == 1 and positive[0]["closure_code"] == "WORK_COMPLETED" and positive[0]["notification_priority"] == "3", "Positive example lost")
    for aid, mode in [("P-DIG-CIR-01", "PUMP_BEARING_VIBRATION"),
                      ("HPU-DRY-HYD-01", "HYD_PRESS_INSTABILITY"),
                      ("FV-CAU-WLC-01", "VALVE_STICTION")]:
        chain = [r for r in rows if r["asset_id"] == aid and r["failure_mode"] == mode]
        require(len(chain) >= 9, "Missing recurring history")
        require(any(r["notification_priority"] == "1" and int(r["replanning_count"] or 0) >= 4 for r in chain), "Missing concerning rescheduling")
        require(any(r["notification_status"] == "Open" and not r["work_order_id"] for r in chain), "Missing open high-priority notification")
        require(any(r["order_status"] == "Scheduled" for r in chain), "Missing high-priority order backlog")
    valve_chain = [r for r in rows if r["asset_id"] == "FV-CAU-WLC-01"]
    require(sum(r["notification_status"] == "Closed" and not r["work_order_id"] and r["defect_confirmed"] == "TRUE" for r in valve_chain) >= 3, "Missing untreated confirmed valve defects")
    require(any(r["asset_id"] == "HPU-DRY-HYD-01" and r["responsible_discipline"] == "Instrumentation" and r["reassigned_discipline"] == "Hydraulics" for r in rows), "Missing hydraulic reassignment")
    training = [r for r in rows if r["detected_by_team"] == "Washing & Screening - Maintenance Route A"]
    comparison = [r for r in rows if r["notification_source"] == "Maintenance Sensory Route" and r not in training]
    false_rate = lambda group: sum(r["defect_confirmed"] == "FALSE" for r in group) / len(group)
    require(false_rate(training) > false_rate(comparison) + .20, "Missing sensory detection-quality signal")
    require(sum(r["notification_priority"] == "3" and r["defect_confirmed"] == "FALSE" and not r["work_order_id"] and r["closure_code"] in ("NO_DEFECT_FOUND", "OPERATING_CONDITION") and by_id[r["asset_id"]]["asset_criticality"] in ("B", "C") for r in training) >= 25, "Missing inspected low-priority training subset")
    monitoring = [r for r in rows if r["notification_source"] == "Condition Monitoring"]
    require(false_rate(monitoring) < .10, "Condition monitoring confirmation too low")
    require(sum(r["notification_priority"] == "3" for r in monitoring) > .5 * len(monitoring), "Condition monitoring is not predominantly early detection")
    for row in rows:
        if row["defect_confirmed"] == "FALSE" and not row["work_order_id"]:
            require(not any(other["notification_id"] != row["notification_id"] and other["asset_id"] == row["asset_id"] and other["failure_mode"] == row["failure_mode"] and 0 < (date.fromisoformat(other["notification_date"]) - date.fromisoformat(row["notification_date"])).days < 120 for other in rows), "Rapid recurrence after no-defect closure")


def report(rows):
    total = len(rows)
    orders = [r for r in rows if r["work_order_id"]]
    closed = [r for r in rows if not r["work_order_id"] and r["notification_status"] == "Closed"]
    print(f"Seed {SEED} | snapshot {AS_OF} | records {total}")
    print(f"Converted: {len(orders)} ({len(orders) / total:.2%})")
    for field in ("notification_priority", "responsible_discipline"):
        print(field + ": " + "; ".join(f"{key}={n} ({n/total:.2%})" for key, n in sorted(Counter(r[field] for r in rows).items())))
    print(f"Closed without order: {len(closed)}; confirmation: {dict(Counter(r['defect_confirmed'] for r in closed))}")
    print(f"Reassigned: {sum(bool(r['reassigned_discipline']) for r in rows)}")
    print("Replanning (orders only): " + str(dict(sorted(Counter(r["replanning_count"] for r in orders).items()))))
    print("Order status: " + str(dict(sorted(Counter(r["order_status"] for r in orders).items()))))
    print(f"Open notifications: {sum(r['notification_status'] != 'Closed' for r in rows)}; active orders: {sum(r['order_status'] in ('Created', 'Released', 'Scheduled') for r in rows)}")
    for discipline in CONVERSION:
        group = [r for r in rows if r["responsible_discipline"] == discipline]
        print(f"  {discipline}: conversion {sum(bool(r['work_order_id']) for r in group)/len(group):.1%}")
    print("180-day same-asset/mode recurrence after corrective completion (full follow-up only):")
    for discipline in CONVERSION:
        treated = [r for r in rows if r["responsible_discipline"] == discipline
                   and r["closure_code"] == "WORK_COMPLETED"
                   and (AS_OF - date.fromisoformat(r["actual_end_date"])).days >= 180]
        repeats = sum(any(s["asset_id"] == r["asset_id"] and s["failure_mode"] == r["failure_mode"]
                          and 0 < (date.fromisoformat(s["notification_date"]) - date.fromisoformat(r["actual_end_date"])).days <= 180
                          for s in rows) for r in treated)
        print(f"  {discipline}: {repeats}/{len(treated)}")
    for team in ("Washing & Screening - Maintenance Route A",):
        group = [r for r in rows if r["detected_by_team"] == team]
        print(f"  {team}: unconfirmed {sum(r['defect_confirmed'] == 'FALSE' for r in group)}/{len(group)}")


def main():
    reference = ROOT / "data/reference"
    raw = ROOT / "data/raw"
    protected = {p: p.read_bytes() for p in (reference / "system_asset_master.csv", reference / "risk_matrix.csv")}
    assets = read_csv(reference / "system_asset_master.csv")
    matrix = read_csv(reference / "risk_matrix.csv")
    require({(r["asset_criticality"], r["notification_priority"]) for r in matrix} == {(a, p) for a in "ABC" for p in "123"}, "Risk matrix coverage mismatch")
    with (raw / "maintenance_history.csv").open(encoding="utf-8-sig", newline="") as stream:
        require(next(csv.reader(stream)) == FIELDS, "Existing raw header differs from contract")
    rows = generate(assets)
    validate(rows, assets, CAMPAIGNS)
    maintenance = csv_bytes(FIELDS, rows)
    require(maintenance == csv_bytes(FIELDS, generate(assets)), "Deterministic regeneration failed")
    (raw / "maintenance_history.csv").write_bytes(maintenance)
    (raw / "campaign_summary.csv").write_bytes(csv_bytes(CAMPAIGN_FIELDS, CAMPAIGNS))
    validate(read_csv(raw / "maintenance_history.csv"), assets, read_csv(raw / "campaign_summary.csv"))
    require(all(p.read_bytes() == original for p, original in protected.items()), "Protected reference changed")
    report(rows)
    print("QA, determinism and saved CSV validation: PASS; SHA256 " + hashlib.sha256(maintenance).hexdigest())


if __name__ == "__main__":
    main()
