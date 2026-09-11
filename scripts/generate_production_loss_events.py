"""Generate operational losses with Python 3, standard library only.

Run: python scripts/generate_production_loss_events.py
Seed 20260911; local mill timestamps have no UTC offset. Rates are effective
whole-mill ADt/day, including the effect of buffers during local interruptions.
Duration is quantized to 15 minutes; losses are rounded to 0.01 ADt.

QA relationships are hypotheses, never causal conclusions or exported columns:
A: no confirmed same-asset/mode report or recent corrective completion in 180
   days, with a full 180 days of extract coverage (avoids early-C1 censoring).
B: confirmed same-asset/mode report in 180 days, without recorded meaningful
   correction after that report and strictly before the event date.
C: confirmed same-asset/mode corrective completion 7-120 days before the event,
   without a newer confirmed report after that completion. C takes precedence.
Same-day notifications/completions do not establish temporal precedence because
maintenance dates lack time of day. Final order status alone is never evidence
that execution had already occurred. Closure and replanning timestamps are absent,
so B does not assert when administrative closure or each schedule change occurred.

All events are non-overlapping at mill level to avoid double-counted lost output.
No campaign-dependent severity factors or improving/deteriorating trends are used.
"""

import csv
import hashlib
import io
import math
import random
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260911
LOOKBACK = 180
POSITIVE = "FAN-RB-AIR-01"
PRIORITY_AREAS = {"Digester", "Drying", "Recovery Boiler", "Causticizing"}
FIELDS = (
    "loss_event_id campaign_id event_start_datetime event_end_datetime duration_hours "
    "island area system_id system_name functional_location asset_id impact_scope "
    "event_type cause_category failure_mode event_description root_cause_status "
    "baseline_rate_adt_day actual_rate_adt_day production_loss_adt operations_comment"
).split()
HIERARCHY = "island area system_id system_name functional_location".split()
TYPES = ["Production Rate Reduction", "Area Shutdown", "Mill Shutdown"]
CAUSES = ["Equipment Failure", "Instrumentation / Control", "Process Upset", "Utility Constraint"]
STATUSES = ["Confirmed", "Probable", "Under Investigation"]
SEEDS = [
    ("P-DIG-CIR-01", "PUMP_BEARING_VIBRATION", ["Area Shutdown", "Mill Shutdown"]),
    ("HPU-DRY-HYD-01", "HYD_PRESS_INSTABILITY", ["Production Rate Reduction", "Area Shutdown"]),
    ("FV-CAU-WLC-01", "VALVE_STICTION", ["Production Rate Reduction", "Area Shutdown"]),
    ("P-RB-BLF-01", "PUMP_BEARING_VIBRATION", ["Production Rate Reduction", "Mill Shutdown"]),
]
PROCESS = {
    "PROCESS_INSTABILITY": "Process oscillations required reduced mill throughput",
    "PROCESS_RESTRICTION": "Process restriction limited transfer capacity",
    "QUALITY_RESTRICTION": "Off-target pulp quality required reduced throughput",
    "FOULING": "Deposits reduced effective process capacity",
    "STEAM_PRESSURE_CONSTRAINT": "Available steam pressure limited mill throughput",
    "CHEMICAL_BALANCE_DEVIATION": "Chemical balance deviation constrained stable operation",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def encode(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def number(value):
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def process_modes(asset):
    """Limit process attribution to systems where the mechanism is plausible."""
    name = asset["system_name"]
    if name in {"Chip Feeding", "Sheet Handling / Cutter", "Hydraulic System",
                "Lubrication System", "Kiln Drive", "Electrical Distribution",
                "Compressed Air", "Combustion Air", "Induced Draft"}:
        return []
    modes = ["PROCESS_INSTABILITY", "PROCESS_RESTRICTION", "FOULING"]
    if name in {"Dryer Section", "Steam / Pressure Control", "Steam Distribution", "Evaporator Circulation"}:
        modes.append("STEAM_PRESSURE_CONSTRAINT")
    if asset["area"] in {"Digester", "Bleaching", "Washing & Screening"} or name in {"Forming Section", "Press Section", "Dryer Section"}:
        modes.append("QUALITY_RESTRICTION")
    if name in {"Impregnation", "Cooking Circulation", "Chemical Mixing", "Chemical Dosing",
                "Bleaching Towers", "Slaking", "Causticizing Reactors", "White Liquor Clarification"}:
        modes.append("CHEMICAL_BALANCE_DEVIATION")
    return modes


class History:
    def __init__(self, maintenance, campaigns):
        self.start = min(date.fromisoformat(c["start_date"]) for c in campaigns)
        self.by_pair = defaultdict(list)
        self.vocabulary = defaultdict(set)
        self.symptoms = {}
        self.training_pairs = set()
        for row in maintenance:
            pair = row["asset_id"], row["failure_mode"]
            self.vocabulary[pair[0]].add(pair[1])
            self.symptoms.setdefault(pair, row["symptom"].rstrip("."))
            if row["detected_by_team"] == "Washing & Screening - Maintenance Route A" and row["defect_confirmed"] == "FALSE":
                self.training_pairs.add(pair)
            if row["defect_confirmed"] == "TRUE":
                completion = None
                if row["work_order_id"] and row["order_status"] == "Completed" and row["closure_code"] == "WORK_COMPLETED" and row["action_type"] not in ("", "Inspection only"):
                    completion = date.fromisoformat(row["actual_end_date"])
                self.by_pair[pair].append((date.fromisoformat(row["notification_date"]), completion))

    def infer(self, asset, mode, day):
        if not asset:
            return "System/process"
        prior = [(n, c) for n, c in self.by_pair[(asset, mode)] if n < day]
        recent = [(n, c) for n, c in prior if (day - n).days <= LOOKBACK]
        completed = [c for _, c in prior if c and c < day]
        latest = max(completed, default=None)
        if latest and 7 <= (day - latest).days <= 120 and not any(n > latest for n, _ in prior):
            return "C"
        if recent:
            last_report = max(n for n, _ in recent)
            if not any(c >= last_report for c in completed):
                return "B"
        same_day_report = any(n == day for n, _ in self.by_pair[(asset, mode)])
        if not recent and not same_day_report and not any((day - c).days <= LOOKBACK for c in completed) and (day - self.start).days >= LOOKBACK:
            return "A"
        return "Other"


def make_event(rng, asset, mode, campaign, start, kind, history, seeded=False, system=False):
    dominant = asset["area"] in PRIORITY_AREAS
    # Seeded systems have longer restoration/stabilization periods. Ordinary
    # events overlap in severity across areas and across criticality classes.
    median = 17 if seeded else (4.0 if dominant else 3.0)
    hours = min(48, max(.5, rng.lognormvariate(math.log(median), .80)))
    hours = round(hours * 4) / 4
    end = start + timedelta(hours=hours)
    baseline = Decimal(number(min(4450, max(3900, rng.gauss(4200, 95)))))
    if kind == "Mill Shutdown":
        fraction = rng.uniform(0, .025)
        scope = "Mill"
    elif kind == "Area Shutdown":
        fraction = rng.uniform(.20, .55)
        scope = "Area"
    else:
        reduction = rng.uniform(.08, .34) * (1.08 if asset["asset_criticality"] == "A" else .95)
        fraction = 1 - reduction
        scope = "Mill" if system and mode == "STEAM_PRESSURE_CONSTRAINT" else "System"
    actual = Decimal(number(baseline * Decimal(str(fraction))))
    loss = number((baseline - actual) * Decimal(str(hours)) / 24)
    if system:
        cause = "Utility Constraint" if mode == "STEAM_PRESSURE_CONSTRAINT" else "Process Upset"
        description = PROCESS[mode]
        status = rng.choices(STATUSES, [15, 55, 30])[0]
    else:
        cause = "Instrumentation / Control" if mode in ("SIGNAL_DRIFT", "INTERMITTENT_SIGNAL", "CALIBRATION_DEVIATION", "IMPULSE_LINE_RESTRICTION", "CONTROL_SEQUENCE_DEVIATION", "POSITIONER_DEVIATION") else "Equipment Failure"
        description = history.symptoms[(asset["asset_id"], mode)]
        status = rng.choices(STATUSES, [55, 45, 0] if seeded else [45, 45, 10])[0]
    effects = {"Mill Shutdown": "mill production stopped for recovery",
               "Area Shutdown": "area operation stopped and mill output reduced",
               "Production Rate Reduction": "mill throughput reduced during stabilization"}
    comments = {"Mill Shutdown": "Shift coordinated isolation and a staged mill restart.",
                "Area Shutdown": "Available buffers were used while the affected area recovered.",
                "Production Rate Reduction": "Throughput was limited until operating conditions stabilized."}
    row = dict.fromkeys(FIELDS, "")
    row.update({field: asset[field] for field in HIERARCHY})
    row.update(campaign_id=campaign["campaign_id"], event_start_datetime=start.isoformat(),
               event_end_datetime=end.isoformat(), duration_hours=number(hours),
               asset_id="" if system else asset["asset_id"], impact_scope=scope,
               event_type=kind, cause_category=cause, failure_mode=mode,
               event_description=description + "; " + effects[kind] + ".",
               root_cause_status=status, baseline_rate_adt_day=str(baseline),
               actual_rate_adt_day=str(actual), production_loss_adt=loss,
               operations_comment=comments[kind])
    return row


def fits(row, campaign, existing):
    start, end = (datetime.fromisoformat(row[k]) for k in ("event_start_datetime", "event_end_datetime"))
    lower = datetime.fromisoformat(campaign["start_date"])
    upper = datetime.fromisoformat(campaign["end_date"]) + timedelta(days=1)
    return lower <= start < end < upper and all(
        end + timedelta(hours=2) <= datetime.fromisoformat(other["event_start_datetime"])
        or start >= datetime.fromisoformat(other["event_end_datetime"]) + timedelta(hours=2)
        for other in existing)


def generate(assets, maintenance, campaigns):
    rng = random.Random(SEED)
    history = History(maintenance, campaigns)
    by_id = {a["asset_id"]: a for a in assets}
    area_counts = Counter(a["area"] for a in assets)
    seeded_ids = {s[0] for s in SEEDS}
    # Training-associated asset/mode pairs are excluded, not turned into bad actors.
    candidates = [(a, mode) for a in assets if a["asset_id"] not in seeded_ids | {POSITIVE}
                  for mode in sorted(history.vocabulary[a["asset_id"]])
                  if (a["asset_id"], mode) not in history.training_pairs]
    weights = [1 / (area_counts[a["area"]] * len(history.vocabulary[a["asset_id"]])) for a, _ in candidates]
    locations = {a["functional_location"]: a for a in assets}
    location_values = [a for a in locations.values() if process_modes(a)]
    location_areas = Counter(a["area"] for a in location_values)
    rows = []
    for campaign in campaigns:
        start_day = date.fromisoformat(campaign["start_date"])
        span = (date.fromisoformat(campaign["end_date"]) - start_day).days
        current = []
        # Two impacts per recurring asset per campaign; not every notification
        # maps to an event. Six of these eight must follow an unresolved report.
        for aid, mode, kinds in SEEDS:
            for index, kind in enumerate(kinds):
                for _ in range(10000):
                    day = start_day + timedelta(days=rng.randint(*[(65, 110), (180, 245)][index]))
                    if aid != "P-RB-BLF-01" and history.infer(aid, mode, day) != "B":
                        continue
                    start = datetime.combine(day, time(rng.randrange(24), rng.choice([0, 15, 30, 45])))
                    row = make_event(rng, by_id[aid], mode, campaign, start, kind, history, seeded=True)
                    if fits(row, campaign, current):
                        current.append(row)
                        break
                else:
                    raise RuntimeError("Cannot place a recurring-system event")
        # Modest category quotas ensure diagnostic coverage; these are not labels
        # or IDs exported with events. Other asset events are unconstrained.
        requests = ["C"] * 7 + ["B"] * 12 + ["A"] * 12 + ["Any"] * 25 + ["System"] * 16
        kinds = [TYPES[0]] * 48 + [TYPES[1]] * 20 + [TYPES[2]] * 4
        rng.shuffle(kinds)
        for requested, kind in zip(requests, kinds):
            for _ in range(30000):
                day = start_day + timedelta(days=rng.randint(0, span))
                if requested == "System":
                    asset = rng.choices(location_values, [1 / location_areas[a["area"]] for a in location_values])[0]
                    mode = rng.choice(process_modes(asset))
                else:
                    asset, mode = rng.choices(candidates, weights)[0]
                    if requested != "Any" and history.infer(asset["asset_id"], mode, day) != requested:
                        continue
                if kind == "Mill Shutdown" and asset["asset_criticality"] == "C":
                    continue
                start = datetime.combine(day, time(rng.randrange(24), rng.choice([0, 15, 30, 45])))
                row = make_event(rng, asset, mode, campaign, start, kind, history, system=requested == "System")
                if fits(row, campaign, current):
                    current.append(row)
                    break
            else:
                raise RuntimeError(f"Cannot place {requested} event in {campaign['campaign_id']}")
        rows.extend(current)
    rows.sort(key=lambda r: r["event_start_datetime"])
    for index, row in enumerate(rows, 1):
        row["loss_event_id"] = f"LE{index:06d}"
    return rows


def summarize(rows, history):
    by_area, by_campaign, by_asset, by_location = (defaultdict(Decimal) for _ in range(4))
    for r in rows:
        loss = Decimal(r["production_loss_adt"])
        by_area[r["area"]] += loss
        by_campaign[r["campaign_id"]] += loss
        if r["asset_id"]:
            by_asset[r["asset_id"]] += loss
        by_location[r["functional_location"]] += loss
    total = sum(by_area.values())
    ranked = sorted((Decimal(r["production_loss_adt"]) for r in rows), reverse=True)
    patterns = Counter(history.infer(r["asset_id"], r["failure_mode"], datetime.fromisoformat(r["event_start_datetime"]).date()) for r in rows)
    return dict(total=total, areas=by_area, campaigns=by_campaign, assets=by_asset,
                locations=by_location, patterns=patterns,
                concentration=sum(by_area[a] for a in PRIORITY_AREAS) / total,
                top10=sum(ranked[:24]) / total, top20=sum(ranked[:48]) / total,
                bottom50=sum(ranked[120:]) / total)


def validate(rows, assets, maintenance, campaigns):
    require(len(rows) == 240, "Expected exactly 240 events")
    require(len({r["loss_event_id"] for r in rows}) == 240, "Duplicate loss event ID")
    require(Counter(r["campaign_id"] for r in rows) == {"C1": 80, "C2": 80, "C3": 80}, "Campaign event counts differ")
    by_id = {a["asset_id"]: a for a in assets}
    locations = {a["functional_location"]: a for a in assets}
    campaign_map = {c["campaign_id"]: c for c in campaigns}
    history = History(maintenance, campaigns)
    for row in rows:
        tag = row["loss_event_id"]
        require(list(row) == FIELDS, f"{tag}: schema mismatch")
        require(row["campaign_id"] in campaign_map, f"{tag}: unknown campaign")
        campaign = campaign_map[row["campaign_id"]]
        require(fits(row, campaign, []), f"{tag}: outside campaign or reversed dates")
        start, end = (datetime.fromisoformat(row[k]) for k in ("event_start_datetime", "event_end_datetime"))
        require(start.tzinfo is None and end.tzinfo is None, f"{tag}: expected local timestamps")
        require(end < datetime(2025, 11, 16), f"{tag}: exceeds extract cutoff")
        for c in campaigns:
            shutdown_start = datetime.fromisoformat(c["planned_shutdown_start"])
            shutdown_end = datetime.fromisoformat(c["planned_shutdown_end"]) + timedelta(days=1)
            require(end <= shutdown_start or start >= shutdown_end, f"{tag}: overlaps planned shutdown")
        duration = Decimal(row["duration_hours"])
        require(abs(duration - Decimal(str((end - start).total_seconds() / 3600))) <= Decimal("0.005"), f"{tag}: duration mismatch")
        baseline, actual, loss = (Decimal(row[k]) for k in ("baseline_rate_adt_day", "actual_rate_adt_day", "production_loss_adt"))
        require(all(n.is_finite() for n in (duration, baseline, actual, loss)), f"{tag}: nonfinite number")
        require(baseline > actual >= 0 and loss > 0, f"{tag}: invalid rates/loss")
        require(abs(loss - (baseline - actual) * duration / 24) <= Decimal("0.005"), f"{tag}: loss calculation mismatch")
        require(row["functional_location"] in locations, f"{tag}: unknown location")
        reference = locations[row["functional_location"]]
        if row["asset_id"]:
            require(row["asset_id"] in by_id, f"{tag}: unknown asset")
            reference = by_id[row["asset_id"]]
            require(row["failure_mode"] in history.vocabulary[row["asset_id"]], f"{tag}: incompatible technical attribution")
            require((row["asset_id"], row["failure_mode"]) not in history.training_pairs, f"{tag}: training report converted to loss")
        else:
            require(row["failure_mode"] in process_modes(reference), f"{tag}: process mechanism incompatible with system")
        require(all(row[k] == reference[k] for k in HIERARCHY), f"{tag}: inconsistent hierarchy")
        require(row["asset_id"] != POSITIVE, f"{tag}: positive control violated")
        require(row["event_type"] in TYPES and row["cause_category"] in CAUSES and row["root_cause_status"] in STATUSES, f"{tag}: uncontrolled vocabulary")
        require(row["impact_scope"] in ("Mill", "Area", "System"), f"{tag}: invalid scope")
        if row["event_type"] == "Mill Shutdown":
            require(actual <= baseline * Decimal("0.03") and row["impact_scope"] == "Mill", f"{tag}: shutdown rate/scope mismatch")
        elif row["event_type"] == "Area Shutdown":
            require(actual < baseline * Decimal("0.60") and row["impact_scope"] == "Area", f"{tag}: area impact mismatch")
        else:
            require(actual > 0, f"{tag}: rate reduction has zero output")
        require(not any(word in " ".join(row.values()).lower() for word in (
            "painting", "coating", "preservation", "undetected", "untreated", "ineffective maintenance", "bad actor")), f"{tag}: excluded conclusion/subject")
    ordered = sorted(rows, key=lambda r: r["event_start_datetime"])
    require(all(a["event_end_datetime"] < b["event_start_datetime"] for a, b in zip(ordered, ordered[1:])), "Overlapping mill losses")
    stats = summarize(rows, history)
    require(Decimal(".65") <= stats["concentration"] <= Decimal(".80"), "Priority-area loss concentration outside 65-80%")
    dominant_count = sum(r["area"] in PRIORITY_AREAS for r in rows)
    dominant_mean = stats["total"] * stats["concentration"] / dominant_count
    other_mean = stats["total"] * (1 - stats["concentration"]) / (240 - dominant_count)
    require(dominant_mean > other_mean * Decimal("1.5"), "Concentration depends too heavily on event counts")
    for pattern, minimum in [("A", 25), ("B", 30), ("C", 15)]:
        require(stats["patterns"][pattern] >= minimum, f"Too few inferable {pattern} cases")
        pairs = {(r["asset_id"], r["failure_mode"]) for r in rows if history.infer(r["asset_id"], r["failure_mode"], datetime.fromisoformat(r["event_start_datetime"]).date()) == pattern}
        require(len(pairs) >= 10, f"{pattern} cases lack asset/mode diversity")
    require(36 <= sum(not r["asset_id"] for r in rows) <= 60, "System-level attribution outside target")
    require(stats["areas"]["Washing & Screening"] / stats["total"] < Decimal(".08"), "Training area became a major loss driver")
    require(stats["top10"] > stats["bottom50"] * 2 and stats["top20"] > Decimal(".45"), "Insufficient long tail")
    counts = Counter(r["event_type"] for r in rows)
    for kind, low, high in zip(TYPES, [.60, .25, .05], [.70, .35, .10]):
        require(low <= counts[kind] / 240 <= high, "Event-type distribution outside target")
    require(set(stats["areas"]) == {a["area"] for a in assets}, "Missing plant area")
    for aid, mode, kinds in SEEDS:
        group = [r for r in rows if r["asset_id"] == aid and r["failure_mode"] == mode]
        require(Counter(r["campaign_id"] for r in group) == {"C1": 2, "C2": 2, "C3": 2}, "Recurring-system coverage changed")
        require(set(kinds) <= {r["event_type"] for r in group}, "Missing seeded impact types")
        if aid != "P-RB-BLF-01":
            require(all(history.infer(aid, mode, datetime.fromisoformat(r["event_start_datetime"]).date()) == "B" for r in group), "Recurring timeline no longer follows unresolved reports")
    # Verify magnitude is not a deterministic criticality ranking.
    a_losses = [Decimal(r["production_loss_adt"]) for r in rows if r["asset_id"] and by_id[r["asset_id"]]["asset_criticality"] == "A"]
    b_losses = [Decimal(r["production_loss_adt"]) for r in rows if r["asset_id"] and by_id[r["asset_id"]]["asset_criticality"] == "B"]
    require(max(b_losses) > sorted(a_losses)[len(a_losses) // 2], "Criticality determines magnitude too rigidly")
    return stats


def report(rows, stats):
    print(f"QA PASS | seed {SEED} | events {len(rows)} | total loss {stats['total']:,.2f} ADt")
    print("Campaigns: " + "; ".join(f"{c}: 80 events, {loss:,.2f} ADt" for c, loss in sorted(stats["campaigns"].items())))
    for field in ("event_type", "cause_category", "root_cause_status"):
        print(field + ": " + "; ".join(f"{key}: {n} ({n/240:.2%})" for key, n in sorted(Counter(r[field] for r in rows).items())))
    print("Area | events | ADt")
    for area, loss in sorted(stats["areas"].items(), key=lambda x: (-x[1], x[0])):
        print(f"  {area} | {sum(r['area'] == area for r in rows)} | {loss:,.2f}")
    for key in ("assets", "locations"):
        print("Top 10 " + key + " by ADt:")
        for name, loss in sorted(stats[key].items(), key=lambda x: (-x[1], x[0]))[:10]:
            print(f"  {name}: {loss:,.2f}")
    print(f"Four priority areas: {stats['concentration']:.2%}")
    attributed = sum(bool(r["asset_id"]) for r in rows)
    print(f"Asset attributed: {attributed}; system/process: {240-attributed}")
    print("Inferred relationships (QA only): " + str(dict(sorted(stats["patterns"].items()))))
    print(f"Pareto: top 10%={stats['top10']:.2%}; top 20%={stats['top20']:.2%}; bottom half={stats['bottom50']:.2%}")
    print("FAN-RB-AIR-01 positive control preserved; no training-pair loss attribution.")


def main():
    paths = [ROOT / p for p in ("data/reference/system_asset_master.csv", "data/reference/risk_matrix.csv",
                               "data/raw/maintenance_history.csv", "data/raw/campaign_summary.csv",
                               "scripts/generate_maintenance_history.py")]
    protected = {p: p.read_bytes() for p in paths}
    assets, maintenance, campaigns = (read_csv(paths[i]) for i in (0, 2, 3))
    require(all(not r["linked_loss_event_id"] for r in maintenance), "Maintenance links must remain blank")
    rows = generate(assets, maintenance, campaigns)
    stats = validate(rows, assets, maintenance, campaigns)
    output = encode(rows)
    require(output == encode(generate(assets, maintenance, campaigns)), "Deterministic regeneration failed")
    target = ROOT / "data/raw/production_loss_events.csv"
    target.write_bytes(output)
    validate(read_csv(target), assets, maintenance, campaigns)
    require(all(p.read_bytes() == original for p, original in protected.items()), "Protected input changed")
    report(rows, stats)
    print("Saved CSV and deterministic regeneration PASS; SHA256 " + hashlib.sha256(output).hexdigest())
    print("Maintenance, campaign, reference CSVs and maintenance generator are byte-for-byte unchanged.")


if __name__ == "__main__":
    main()
