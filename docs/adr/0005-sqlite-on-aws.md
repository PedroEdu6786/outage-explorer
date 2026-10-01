# ADR-0005: Use SQLite for operational data on AWS

Status: **Accepted**

Date: 2026-10-01

## Context and decision

The user accepted the proposed SQLite operational database and requested AWS
hosting. Keep one active backend replica. SQLite holds operational records
such as users, sessions, refresh runs and the active snapshot reference;
analytical Parquet remains in S3 and is queried with DuckDB.

## Alternatives and consequences

SQLite fits the selected single-backend topology without a separate database
server. A managed client/server database would be a different engine choice;
none was selected by this request.

SQLite is embedded in the backend. Its live database file needs durable
storage on the selected AWS runtime, independently of disposable analytical
staging. Do not place the active database file in S3 or assume that a container
filesystem persists across replacement. The AWS compute service, storage
attachment/recovery mechanism, backups and region remain open. No AWS
resources have been provisioned.

The choice does not make multi-replica writes part of the scope. Revisit the
engine if future hosting or concurrency requirements cannot support its file
and ownership lifecycle.

- [SQLite deployment guidance](https://www.sqlite.org/whentouse.html)
- [Backend architecture](../context/architecture.md)
