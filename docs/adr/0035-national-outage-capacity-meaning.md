# ADR-0035: Include partial output reductions in national outage capacity

Status: **Accepted**

Date: 2026-10-01

## Context

The national verification brief's last product question concerned capacity and
partial-output meaning. The user accepted the following description after
reviewing official EIA documentation and recorded source observations:

> Daily share of EIA-reported nuclear capacity out of service, including full
> outages and partial output reductions.

## Decision

- Use that description for the existing daily fleet offline-share metric.
- Calculate the share from the same stored national observation's outage and
  capacity in MW; multiply by 100 for percent. Preserve both reported values.
- Include partial reductions as represented in the reported outage value.
  Positive outage does not imply complete shutdown of every affected reactor.
- Describe daily reported status. Do not represent the measure as reactor
  shutdown count, a full-day average, outage duration, lost energy in MWh or
  an explanation of outage causes.
- Use the API-reported national capacity. Do not substitute a separately
  reconstructed capacity estimate or claim knowledge of each historical row's
  exact capacity-data vintage.

This refines ADR-0006's metric meaning. It does not add generator modeling,
cross-grain reconciliation, a frontend, new measures or percentage discrepancy
flags. The focused informal requirements discussion is complete; formal field
contracts and implementation remain subsequent work.

## Evidence and limits

EIA's product overview describes combining NRC morning reactor-status reports
with annual and monthly generator data, and states that the outage product
provides magnitude rather than cause. Its Electricity Monthly Update
methodology ties that publication's nuclear-outage indicator to NRC status
and EIA-860 net summer capacity. The glossary defines net summer capacity as
tested electrical capability supplied to system load, net of station use.
These sources do not establish the capacity vintage of each daily API record.

The recorded September 1, 2026 generator observations include Browns Ferry 1
with capacity 1,227.4 MW, outage 24.548 MW and reported outage percentage 2%.
That date's 95 generator observations include 84 zero, 10 partial and one full
outage, based on reported outage versus capacity. The recorded snapshot's
checksum was verified. These records support the meaning of partial reduction;
they do not independently verify physical operation or complete the later
generator-modeling effort.

## Alternatives and consequences

Counting only fully shut-down reactors would describe a different measure and
discard the partial reductions present in EIA's data. Converting the daily
value to lost energy would require time information these observations do not
establish. The selected description preserves EIA's scope and states its limits.

## References

- [Requirements brief](../specs/national-data-verification/requirements.md)
- [Recorded research and examples](../../data/exploration/eia-capacity-semantics.json)
- [ADR-0006: Daily fleet offline share](0006-daily-fleet-offline-share.md)
- [EIA product overview](https://www.eia.gov/todayinenergy/detail.php?id=60942)
- [EIA methodology, Key Indicators / Nuclear Outages](https://www.eia.gov/electricity/monthly/update/print-version.php)
- [EIA net summer capacity definition](https://www.eia.gov/tools/glossary/index.php?id=net+summer+capacity)
