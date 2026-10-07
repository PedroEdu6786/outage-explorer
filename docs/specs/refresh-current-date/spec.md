# Refresh through the current date

Accepted direction: [ADR-0063](../../adr/0063-configured-start-current-end-refresh.md).

- When a new authorized HTTP refresh is admitted, the application shall use the
  configured start date and today's UTC date, inclusively.
- When the API stays running across midnight, new admissions shall resolve the
  new date; replaying a key shall return the original run without resolving dates.
- The system shall permit subsequent intervals longer than 183 days, passing the
  exact inclusive length to source and model adapters through the saved run.
- The system shall retain all non-date resource bounds, initial-load constraints,
  all-grain refresh, verification, retention and publication fencing.
- When the configured start is in the future, admission shall fail without source
  work. HTTP clients shall continue to have no date override.
- Connector CLI date selection and default resource profile shall remain unchanged.

The current day can have no published source observations. Supporting an interval
is not evidence that it fits finite row/byte/request/time budgets.
