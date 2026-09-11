"""Build Case 1 reporting only. Requires Python 3 and matplotlib (no seaborn).

Run: python scripts/build_case1_report.py
All reported measurements come from the six processed CSVs. Fixed numbers are
layout settings, analytical definitions or explicit regression expectations.
No raw, reference or processed file is written. Rebuilds replace the report,
eight figures and root README; data/content must remain deterministic.
"""

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, PercentFormatter, MaxNLocator

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
BLUE, TEAL, GRAY, INK = "#315B79", "#287F83", "#A8B4BE", "#243644"
GOLD = "#B47B30"
NAMES = ["01_loss_by_campaign", "02_loss_by_area_pareto", "03_top_functional_locations",
         "04_top_bad_actors", "05_loss_by_maintenance_context", "06_discipline_performance",
         "07_risk_backlog", "08_top5_opportunities"]
CONTEXTS = ["NO_PRIOR_DETECTION", "KNOWN_UNTREATED_DEFECT", "POST_MAINTENANCE_RECURRENCE",
            "INSUFFICIENT_HISTORY", "OTHER_AMBIGUOUS", "SYSTEM_PROCESS_EVENT"]
SELECTED = ["PLT-RU-CAU-WLC", "PLT-FL-DIG-CIR", "PLT-RU-RB-BLF", "PLT-FL-DRY-HYD", "PLT-RU-EVA-CIR"]
QUESTIONS = [
    "Why are confirmed valve defects recurring or closed without effective intervention before production impact?",
    "Why does circulation-pump vibration remain recurrent despite repeated detection and maintenance planning?",
    "Why are significant pump-related losses occurring with limited prior detection?",
    "Why does pressure instability recur across Hydraulics/Instrumentation interactions despite repeated notifications?",
    "Are losses driven by detection gaps, intervention effectiveness or multiple unrelated mechanisms?",
]
NEXT_STEPS = [
    "Review SAP notification/order chronology and valve travel/process trends; validate the failure mechanism in Case 2.",
    "Review pump failure history, vibration trends and work-order chronology; investigate the persistent mechanism in Case 2.",
    "Review pump operating conditions, route coverage and historian trends; validate detection windows and failure mechanism in Case 2.",
    "Align hydraulic pressure/control trends with reassignment and work history; perform a targeted systemic investigation in Case 2.",
    "Separate losses by mechanism, asset and intervention chronology; inspect process/historian trends before selecting a Case 2 scope.",
]
SIGNALS = ["Known defect / treatment gap", "Recurring known condition", "Detection opportunity",
           "Recurring multidisciplinary condition", "Mixed maintenance context"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(name):
    with (ROOT / "data/processed" / (name + ".csv")).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def amount(rows, field="production_loss_adt"):
    return sum((Decimal(r[field]) for r in rows), Decimal(0))


def fmt(value):
    return f"{Decimal(value):,.2f}"


def pct(value):
    return f"{Decimal(value):.2%}"


def metrics():
    data = {name: read(name) for name in ("maintenance_enriched", "loss_event_analysis", "discipline_performance",
                                         "bad_actor_ranking", "functional_location_ranking", "risk_backlog")}
    losses = data["loss_event_analysis"]
    total = amount(losses)
    areas, campaigns = defaultdict(Decimal), defaultdict(Decimal)
    for r in losses:
        areas[r["area"]] += Decimal(r["production_loss_adt"])
        campaigns[r["campaign_id"]] += Decimal(r["production_loss_adt"])
    locations = sorted(data["functional_location_ranking"], key=lambda r: int(r["location_rank"]))
    assets = sorted(data["bad_actor_ranking"], key=lambda r: int(r["bad_actor_rank"]))
    contexts = {c: {"count": sum(r["maintenance_context"] == c for r in losses),
                    "loss": amount([r for r in losses if r["maintenance_context"] == c])} for c in CONTEXTS}
    opportunities = []
    for i, location in enumerate(locations[:5]):
        fl = location["functional_location"]
        actors = [a for a in assets if a["functional_location"] == fl and int(a["production_loss_event_count"]) > 0]
        actor = actors[0]
        modes = defaultdict(Decimal)
        for r in losses:
            if r["asset_id"] == actor["asset_id"]:
                modes[r["failure_mode"]] += Decimal(r["production_loss_adt"])
        mode = sorted(modes, key=lambda k: (-modes[k], k))[0]
        group = [r for r in losses if r["functional_location"] == fl]
        context_totals = {c: amount([r for r in group if r["maintenance_context"] == c]) for c in CONTEXTS}
        evidence = "; ".join(f"{c.replace('_', ' ').lower()}: {fmt(v)} ADt" for c, v in context_totals.items() if v)
        opportunities.append(dict(priority_rank=i+1, area=location["area"], system_name=location["system_name"],
                                  functional_location=fl, total_loss_adt=Decimal(location["total_production_loss_adt"]),
                                  share_of_total_loss=Decimal(location["total_production_loss_adt"])/total,
                                  loss_event_count=int(location["production_loss_event_count"]), main_bad_actor=actor["asset_id"],
                                  main_failure_mode=mode, maintenance_context_signal=evidence,
                                  active_backlog_count=int(location["active_backlog_count"]),
                                  engineering_question=QUESTIONS[i], recommended_next_step=NEXT_STEPS[i], signal=SIGNALS[i]))
    return dict(data=data, total=total, areas=dict(sorted(areas.items(), key=lambda x: (-x[1], x[0]))),
                campaigns=dict(sorted(campaigns.items())), contexts=contexts, locations=locations, assets=assets,
                opportunities=opportunities, event_count=len(losses),
                asset_loss=amount([r for r in losses if r["asset_id"]]),
                area_share=sum(areas[a] for a in ("Causticizing", "Digester", "Recovery Boiler", "Drying"))/total,
                top4_share=amount(locations[:4], "total_production_loss_adt")/total,
                risks={f"R{i}": sum(r["risk_class"] == f"R{i}" for r in data["risk_backlog"]) for i in range(1,10)})


def setup():
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12, "axes.titlesize": 15,
                         "axes.labelsize": 12, "text.color": INK, "axes.labelcolor": INK,
                         "xtick.color": INK, "ytick.color": INK, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.edgecolor": "#CCD4DA",
                         "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"})


def frame(title, subtitle, size=(12, 7)):
    fig, ax = plt.subplots(figsize=size)
    fig.suptitle(title, x=.04, y=.97, ha="left", fontsize=20, fontweight="bold")
    fig.text(.04, .915, subtitle, fontsize=11.5, ha="left")
    fig.text(.04, .025, "CASE 1  /  Synthetic pulp mill  /  Source: processed analytical layer", fontsize=10, color="#637481")
    fig.subplots_adjust(left=.12, right=.94, top=.83, bottom=.14)
    return fig, ax


def save(fig, index):
    fig.savefig(FIGURES / (NAMES[index-1] + ".png"), dpi=160, metadata={"Software": "Matplotlib / Case 1 report"})
    plt.close(fig)


def horizontal(ax, labels, values, colors=None, unit="Lost production (ADt)"):
    vals = [float(v) for v in values]
    ax.barh(range(len(labels)), vals, color=colors or BLUE, height=.64)
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals)*1.25)
    ax.set_xlabel(unit)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.xaxis.grid(True, alpha=.18)
    ax.set_axisbelow(True)
    for i, value in enumerate(values):
        ax.text(float(value)+max(vals)*.015, i, fmt(value), va="center", fontsize=11)


def charts(m):
    setup()
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig, ax = frame("Production loss by campaign", "Campaign variation reflects event severity; no improvement trend was imposed.")
    bars = ax.bar(list(m["campaigns"]), [float(v) for v in m["campaigns"].values()], color=BLUE, width=.55)
    ax.bar_label(bars, labels=[fmt(v) for v in m["campaigns"].values()], padding=8, fontsize=14)
    ax.set_ylabel("Lost production (ADt)")
    ax.set_ylim(0, float(max(m["campaigns"].values()))*1.20)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.yaxis.grid(alpha=.18); ax.set_axisbelow(True)
    save(fig,1)

    fig, ax = frame("Production impact is concentrated in four areas", f"Causticizing + Digester + Recovery Boiler + Drying = {pct(m['area_share'])} of total lost ADt.", (12,8))
    areas, values = list(m["areas"]), list(m["areas"].values())
    ax.bar(range(len(areas)), [float(v) for v in values], color=[TEAL]*4+[GRAY]*(len(areas)-4))
    ax.set_xticks(range(len(areas)), [a.replace(" & ", " &\n").replace("Recovery Boiler", "Recovery\nBoiler") for a in areas], rotation=35, ha="right")
    ax.set_ylabel("Lost production (ADt)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.set_ylim(0, float(max(values))*1.18)
    twin = ax.twinx()
    cumulative = []
    running = Decimal(0)
    for v in values:
        running += v
        cumulative.append(float(running/m["total"])*100)
    twin.plot(range(len(areas)), cumulative, color=GOLD, marker="o", linewidth=2.3)
    twin.set_ylim(0,110); twin.set_ylabel("Cumulative share of lost ADt")
    twin.yaxis.set_major_formatter(PercentFormatter())
    twin.annotate(pct(m["area_share"]), (3,cumulative[3]), xytext=(10,-23), textcoords="offset points", color=INK, fontweight="bold")
    fig.subplots_adjust(bottom=.24, right=.89)
    save(fig,2)

    fig, ax = frame("Top 10 functional locations by production loss", f"The top four locations account for {pct(m['top4_share'])} of total lost ADt.", (12,9))
    group = m["locations"][:10]
    horizontal(ax, [r["system_name"]+"\n"+r["functional_location"] for r in group],
               [Decimal(r["total_production_loss_adt"]) for r in group], [TEAL]*4+[GRAY]*6)
    ax.tick_params(axis="y", labelsize=11)
    fig.subplots_adjust(left=.31)
    save(fig,3)

    fig, ax = frame("Top 10 assets by production loss", "Ranked by lost ADt, with event count as the tie-breaker; no composite score.", (12,9))
    group = m["assets"][:10]
    horizontal(ax, [r["asset_id"]+"\n"+r["asset_type"]+" / "+r["area"] for r in group],
               [Decimal(r["total_production_loss_adt"]) for r in group], [TEAL]*4+[GRAY]*6)
    ax.tick_params(axis="y", labelsize=11)
    fig.subplots_adjust(left=.31)
    save(fig,4)

    fig, placeholder = frame("Analytical maintenance context", "Event frequency and production impact answer different questions.", (13,8))
    placeholder.remove()
    left, right = fig.subplots(1,2,gridspec_kw={"width_ratios":[1,1.8]})
    labels = [c.replace("_", " ").title().replace("Maintenance Recurrence", "Maintenance\nRecurrence") for c in CONTEXTS]
    counts = [m["contexts"][c]["count"] for c in CONTEXTS]
    values = [m["contexts"][c]["loss"] for c in CONTEXTS]
    left.barh(range(6), counts, color=GRAY, height=.62)
    left.set_yticks(range(6),labels); left.invert_yaxis(); left.set_xlim(0,max(counts)*1.25)
    left.set_xlabel("Event count"); left.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
    for i,n in enumerate(counts): left.text(n+1,i,str(n),va="center")
    horizontal(right,[""]*6,values,[BLUE,TEAL,BLUE,GRAY,GRAY,GRAY])
    right.tick_params(axis="y",left=False)
    fig.subplots_adjust(left=.25,right=.95,wspace=.18,bottom=.20)
    fig.text(.04,.09,"Association based on exact asset/failure-mode history and temporal rules; not proof of causality.",fontsize=11)
    save(fig,5)

    fig, placeholder = frame("Maintenance discipline indicators", "Rates use total discipline notifications (n); columns are separate measures, not a combined score.", (14,8))
    placeholder.remove()
    ax, loss_ax = fig.subplots(1,2,gridspec_kw={"width_ratios":[2.3,1]})
    disciplines = m["data"]["discipline_performance"]
    keys = ["confirmed_defect_rate","conversion_rate","confirmed_closed_without_order_rate","unconfirmed_closed_without_order_rate","recurrence_rate"]
    values = [[float(r[k])*100 for k in keys] for r in disciplines]
    ax.imshow(values, cmap="Blues",vmin=0,vmax=100,aspect="auto")
    ax.set_yticks(range(len(disciplines)),[r["responsible_discipline"]+f"  (n={r['notification_count']})" for r in disciplines])
    ax.set_xticks(range(5),["Defect\nconfirmed","Order\nconversion","Confirmed\nclosed, no WO","Unconfirmed\nclosed, no WO","Notification\nrecurrence"],fontsize=10.5)
    ax.xaxis.tick_top(); ax.tick_params(length=0)
    for i, vals in enumerate(values):
        for j,v in enumerate(vals): ax.text(j,i,f"{v:.1f}%",ha="center",va="center",color="white" if v>=50 else INK,fontsize=12)
    vals = [float(r["known_untreated_loss_adt"]) for r in disciplines]
    loss_ax.barh(range(len(vals)),vals,color=TEAL,height=.60)
    loss_ax.set_ylim(len(vals)-.5,-.5); loss_ax.set_yticks([])
    loss_ax.set_xlim(0,max(vals)*1.42)
    loss_ax.set_title("Known-untreated\nassociated loss (ADt)",fontsize=11,pad=15)
    loss_ax.xaxis.set_major_formatter(FuncFormatter(lambda x,_: f"{x/1000:g}k"))
    for i,v in enumerate(vals): loss_ax.text(v+max(vals)*.02,i,f"{v:,.0f}",va="center",fontsize=11)
    fig.subplots_adjust(left=.23,right=.97,top=.77,bottom=.18,wspace=.08)
    fig.text(.04,.09,"Hydraulics has a small notification population. Loss associations do not establish discipline causality.",fontsize=11)
    save(fig,6)

    fig,ax = frame("Active maintenance backlog by formal risk", "Risk = asset criticality × defect priority. Age/replanning are complementary indicators.")
    counts=list(m["risks"].values())
    bars=ax.bar(list(m["risks"]),counts,color=[GOLD,GOLD]+[BLUE]*7,width=.62)
    ax.bar_label(bars,padding=6,fontsize=14)
    ax.set_ylabel("Active notifications / orders")
    ax.set_ylim(0,max(counts)*1.22); ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.yaxis.grid(alpha=.18); ax.set_axisbelow(True)
    save(fig,7)

    fig,ax = frame("Top 5 reliability opportunities", "Engineering prioritization starts with functional-location production impact.", (12,8))
    opportunities=m["opportunities"]
    labels=[f"{r['priority_rank']:02d}  {r['system_name']}\n{r['area']}" for r in opportunities]
    horizontal(ax,labels,[r["total_loss_adt"] for r in opportunities],[TEAL]*4+[BLUE])
    for bar in ax.patches:
        center=bar.get_y()+bar.get_height()/2
        bar.set_height(.50)
        bar.set_y(center-.25)
    for i,r in enumerate(opportunities):
        ax.text(0,i+.38,r["signal"],fontsize=10.5,va="center",color=INK)
    ax.set_ylim(4.65,-.65)
    fig.subplots_adjust(left=.34,bottom=.15)
    save(fig,8)


def image(index,root=False):
    prefix="reports/figures/" if root else "figures/"
    return f"![{NAMES[index-1][3:].replace('_',' ').title()}]({prefix}{NAMES[index-1]}.png)"


def table(headers,rows):
    return "| "+" | ".join(headers)+" |\n|"+"|".join("---" for _ in headers)+"|\n"+"\n".join("| "+" | ".join(str(v).replace("|","/").replace("\n"," ") for v in row)+" |" for row in rows)


def documents(m):
    d={r["responsible_discipline"]:r for r in m["data"]["discipline_performance"]}
    c=m["contexts"]
    v,h,e,cm=[d[k] for k in ("Valves","Hydraulics","Electrical","Condition Monitoring")]
    backlog=len(m["data"]["risk_backlog"])
    share=lambda key:pct(c[key]["loss"]/m["asset_loss"])
    oppfields="priority_rank area system_name functional_location total_loss_adt share_of_total_loss loss_event_count main_bad_actor main_failure_mode maintenance_context_signal active_backlog_count engineering_question recommended_next_step".split()
    opprows=[]
    for r in m["opportunities"]:
        opprows.append([fmt(r[k]) if k=="total_loss_adt" else pct(r[k]) if k=="share_of_total_loss" else r[k] for k in oppfields])
    context_table=table(["Analytical context","Events","Lost ADt"],[[k,c[k]["count"],fmt(c[k]["loss"])] for k in CONTEXTS])
    r1examples=[r for r in m["data"]["risk_backlog"] if r["risk_class"]=="R1" and r["asset_id"] in {"FV-CAU-WLC-01","HPU-DRY-HYD-01","P-DIG-CIR-01"} and r["work_order_id"]]
    exposure="; ".join(f"{r['asset_id']}: {r['notification_age_days']} days old, {r['replanning_count']} replans" for r in r1examples)
    positive=next(r for r in m["assets"] if r["asset_id"]=="FAN-RB-AIR-01")
    report=f'''# Case 1 — Plant Production Loss & Bad Actor Analysis

## Executive Summary

This synthetic pulp-mill case covers **{m['event_count']} production-loss events**, **{fmt(m['total'])} ADt** of lost production and **{len(m['campaigns'])} operating campaigns**. Causticizing, Digester, Recovery Boiler and Drying account for **{pct(m['area_share'])}** of loss. The top four functional locations account for **{pct(m['top4_share'])}**.

Of **{fmt(m['asset_loss'])} ADt attributed to specific assets**, **{share('KNOWN_UNTREATED_DEFECT')}** is associated with known untreated defects, **{share('NO_PRIOR_DETECTION')}** with no prior detection, and **{share('POST_MAINTENANCE_RECURRENCE')}** with recent completed corrective maintenance. These percentages are analytical maintenance-history associations, not causal attribution.

The scope is production-impact prioritization and management signals. Detailed Root Cause Analysis, FMEA and predictive modeling are reserved for subsequent work. All data is synthetic and does not describe an actual mill.

## 1. Production Loss Overview

{image(1)}

{table(['Campaign','Events','Lost ADt'],[[k,sum(r['campaign_id']==k for r in m['data']['loss_event_analysis']),fmt(value)] for k,value in m['campaigns'].items()])}

Event frequency is equal across campaigns, while lost production varies with interruption duration and rate reduction. The pattern does not demonstrate an improvement trend or a causal relationship with increased maintenance-notification activity.

## 2. Area Pareto

{image(2)}

The leading four areas contribute {pct(m['area_share'])} of lost ADt. This is production impact, not a ranking by event count. Smaller events in other areas remain visible; concentration directs attention without implying that every event in a priority area is severe.

## 3. System Prioritization

{image(3)}

White Liquor Clarification, Cooking Circulation, Black Liquor Firing and the Drying Hydraulic System together represent {pct(m['top4_share'])} of total loss. Functional-location totals include system/process events without a specific asset attribution, providing a complete system-level Pareto.

## 4. Bad Actors

{image(4)}

The leading assets are {', '.join('`'+r['asset_id']+'`' for r in m['assets'][:4])}. Their ranking is based on lost ADt; event count breaks ties. No composite score or assumed causal responsibility is used. Assets with maintenance activity but no loss remain in the analytical ranking with zero production impact.

## 5. Was the Defect Known?

{image(5)}

{context_table}

- **NO_PRIOR_DETECTION:** a detection/monitoring investigation opportunity; no confirmed exact asset/failure-mode notification was found in the prior 180-day window with sufficient history coverage.
- **KNOWN_UNTREATED_DEFECT:** a treatment, prioritization and maintenance-management investigation opportunity; a prior confirmed report exists without recorded meaningful correction after the latest relevant report and before impact.
- **POST_MAINTENANCE_RECURRENCE:** an intervention-effectiveness, diagnosis or recurrence investigation opportunity; meaningful correction was completed 7–120 days earlier without a newer confirmed matching report before impact.

These categories guide questions rather than establish causes. Same-day notifications are not proven prior detection because maintenance timestamps have calendar-date precision. Insufficient-history and ambiguous cases remain separate. Linked closure/action fields are snapshot attributes; their presence alone cannot establish when administrative disposition occurred. See the [processed-layer definitions](../data/processed/README.md).

## 6. Maintenance Discipline Indicators

{image(6)}

- **Valves:** {pct(v['conversion_rate'])} conversion; {pct(v['confirmed_closed_without_order_rate'])} of notifications are confirmed defects closed without order, with {pct(v['recurrence_rate'])} notification recurrence and {fmt(v['known_untreated_loss_adt'])} ADt of associated known-untreated loss. Review disposition and treatment chronology.
- **Hydraulics:** {pct(h['recurrence_rate'])} recurrence across only {h['notification_count']} notifications. This supports focused review, not a broad conclusion about the discipline.
- **Electrical:** {pct(e['conversion_rate'])} conversion and {pct(e['recurrence_rate'])} recurrence, alongside {pct(e['unconfirmed_closed_without_order_rate'])} unconfirmed closures without order. The latter raises a detection-quality question that requires checking the original observations.
- **Condition Monitoring:** {pct(cm['confirmed_defect_rate'])} confirmed defects and {pct(cm['conversion_rate'])} conversion. The positive comparator `FAN-RB-AIR-01` retains its completed early vibration intervention with {positive['production_loss_event_count']} subsequent attributed production-loss events in the extract; this is not proof that all future failures were prevented.

Notification count is shown for every discipline. Chart rates use total discipline notifications as denominator. Notification recurrence is not itself recurrence after corrective work. Loss is associated once with the receiving discipline of the relevant notification; reassignment and ultimate technical ownership require a separate chronology review. The [full discipline matrix](../data/processed/discipline_performance.csv) preserves the detailed counts and rates. Route/team-level questions can be examined in [maintenance enrichment](../data/processed/maintenance_enriched.csv).

## 7. Current Risk Exposure

{image(7)}

At the 2025-11-15 snapshot, active backlog contains **{backlog} notifications/work items**, including **{m['risks']['R1']} R1** and **{m['risks']['R2']} R2** items. Risk comes directly from the existing criticality/priority matrix; age does not override it.

Recurring R1 work-order examples: {exposure}. Age and replanning indicate items for review, not certainty of future failure. Inspect duplicate/related notifications and the current work scope before treating notification counts as distinct physical defects. The [risk backlog](../data/processed/risk_backlog.csv) retains formal ordering and identifiers.

## 8. Top 5 Reliability Opportunities

{image(8)}

The table follows processed functional-location loss ranking. Main asset is the largest asset contributor within each location; main failure mode is that asset's largest lost-ADt mechanism. Signals are prompts for engineering investigation, not proven diagnoses. The full table is intentionally wide to preserve chronology questions and next steps.

{table(oppfields,opprows)}

## 9. Engineering Interpretation

The dataset suggests that production loss is not explained by a single maintenance problem. The analytical evidence separates three different management questions:

A. Was the defect detected before operational impact?

B. If detected, was it converted into effective corrective work before the impact?

C. If corrective work was completed, why did the same failure mechanism recur?

Detection coverage, maintenance workflow and intervention effectiveness therefore require different engineering responses. The analysis prioritizes where to investigate; it does not establish avoidability, human error or a physical root cause.

## 10. Recommended Reliability Roadmap

**Immediate:** review R1/R2 active backlog; review protective measures for the highest-loss known-defect systems; reconcile unresolved recurring notifications with current work scopes and operating conditions.

**Focused investigation:** examine White Liquor Clarification, Cooking Circulation, the Drying Hydraulic System and Black Liquor Firing as candidate scopes, starting with one system. Evaporator Circulation remains a mixed-context follow-on opportunity.

**System development:** improve detection-quality review, notification-to-order workflow visibility, recurrence monitoring and risk-based backlog management. Keep unconfirmed observations distinct from confirmed untreated defects.

The present repository contains synthetic notification/order chronology, loss events, hierarchy and risk references. Vibration spectra, valve travel tests, process/historian traces, detailed job scopes and inspection evidence are not supplied. Case 2 should establish their availability and validate the mechanism before selecting corrective recommendations.

## 11. Connection to Case 2

Begin Case 2 with **one selected high-value system: White Liquor Clarification**, the leading functional location by production loss. Review its valve chronology and operating evidence before extending the investigation to the other opportunities; do not begin all five simultaneously.

Case 1 answered:
"Where should reliability engineering focus?"

Case 2 will answer:
"Why is the selected system repeatedly losing production?"
'''
    root=f'''# Plant Production Loss & Bad Actor Analysis

## Industrial Reliability Case Study

This case demonstrates a production-loss-driven approach to industrial reliability: identify where production was lost, which systems contributed most, and where reliability engineering should focus first.

> All data is synthetic and created exclusively for demonstration. It does not reproduce confidential data from an actual industrial facility.

## Case Results

- Total production loss: **{fmt(m['total'])} ADt**
- Loss events: **{m['event_count']}** across **{len(m['campaigns'])} campaigns**
- Four priority areas: **{pct(m['area_share'])} of loss**
- Top four functional locations: **{pct(m['top4_share'])} of loss**
- Known untreated defect association: **{fmt(c['KNOWN_UNTREATED_DEFECT']['loss'])} ADt**
- No-prior-detection association: **{fmt(c['NO_PRIOR_DETECTION']['loss'])} ADt**
- Active maintenance backlog: **{backlog}**
- R1 backlog: **{m['risks']['R1']}**

These maintenance-history associations do not prove causality. Read the [full Case 1 executive summary](reports/case1_executive_summary.md) for definitions, limitations, discipline indicators and the proposed investigation roadmap.

{image(2,True)}

{image(5,True)}

{image(8,True)}

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

**Khayan Sobral Marques**{'  '}
Reliability & Asset Performance Engineer{'  '}
Production Loss Reduction | Maintenance Strategy | Industrial Analytics

[LinkedIn](https://www.linkedin.com/in/khayansm/)
'''
    return report,root


def validate(m,report,root):
    # Expectations check regression; displayed values always use computed metrics.
    require(m["total"]==Decimal("106546.52"),"Total loss regression mismatch")
    require([r["functional_location"] for r in m["opportunities"]]==SELECTED,"Top five ranking mismatch")
    require(m["event_count"]==240,"Event count regression mismatch")
    require(sum(v["loss"] for v in m["contexts"].values())==m["total"],"Context totals differ")
    require(amount(m["locations"],"total_production_loss_adt")==m["total"],"Location totals differ")
    require(amount(m["assets"],"total_production_loss_adt")==m["asset_loss"],"Asset totals differ")
    require(m["risks"]==dict(zip([f"R{i}" for i in range(1,10)],[7,3,0,2,9,0,14,0,3])),"Backlog regression mismatch")
    for r in m["opportunities"]:
        require(r["signal"] and r["main_failure_mode"] and fmt(r["total_loss_adt"]) in report,"Opportunity evidence missing")
    require(len(re.findall(r"!\[",root))<=3,"Too many root README figures")
    require(len(re.findall(r"!\[",report))==8,"Missing report figures")
    for text,base in [(report,REPORTS),(root,ROOT)]:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)",text):
            if target.startswith("https://"):
                continue
            require(not Path(target).is_absolute() and (base/target).exists(),"Invalid relative Markdown link: "+target)
    for name in NAMES:
        pixels=plt.imread(FIGURES/(name+".png"))
        require(pixels.shape[1]>=1600 and pixels.std()>.01,"Missing/blank/undersized figure")


def main():
    protected={p:p.read_bytes() for folder in ("raw","reference","processed") for p in (ROOT/"data"/folder).rglob("*") if p.is_file()}
    m=metrics()
    signature=json.dumps(m,default=str,sort_keys=True)
    report,root=documents(m)
    charts(m)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS/"case1_executive_summary.md").write_text(report,encoding="utf-8",newline="\n")
    (ROOT/"README.md").write_text(root,encoding="utf-8",newline="\n")
    validate(m,report,root)
    again=metrics()
    require(signature==json.dumps(again,default=str,sort_keys=True) and documents(again)==(report,root),"Data/content determinism failed")
    require(all(p.read_bytes()==contents for p,contents in protected.items()),"Immutable data file changed")
    print(f"QA PASS | {m['event_count']} events | {fmt(m['total'])} ADt | priority areas {pct(m['area_share'])} | top four locations {pct(m['top4_share'])}")
    print(f"Eight figures generated; all Markdown links valid; {len(protected)} immutable files byte-identical.")
    print("Content/data SHA256: "+hashlib.sha256(signature.encode()).hexdigest())
    for r in m["opportunities"]:
        print(f"{r['priority_rank']}. {r['system_name']} | {fmt(r['total_loss_adt'])} ADt | {r['main_bad_actor']} | {r['main_failure_mode']}")


if __name__=="__main__":
    main()
