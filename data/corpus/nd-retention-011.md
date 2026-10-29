---
id: nd-retention-011
title: Data Retention
version: 2.4
status: current
product_area: data
synthetic: true
---

# Data Retention

> Synthetic documentation for a fictional product.

Retention windows differ by data class. The windows below are the 2.4 defaults
for NimbusDesk Cloud; self-hosted operators can shorten any of them but cannot
lengthen audit log retention beyond 400 days.

## Retention windows

| Data class | Retained for | Configurable |
| --- | --- | --- |
| Deleted desks (recycle bin) | 30 days | yes, 7-90 days |
| Audit log entries | 400 days | yes, up to 400 days |
| Webhook delivery records | 30 days | no |
| Generated export archives | 7 days | no |
| Workspace pending deletion | 14 days | no |
| Request logs | 14 days | yes, 1-30 days |

## The recycle bin

Deleting a desk moves it to the recycle bin, where it stays for 30 days before
permanent purge. A desk in the recycle bin still counts against the desks-per-space
soft limit but not against the hard limit.

Restoring is `POST /v2/desks/{id}/restore` and works until the purge. After the
purge the desk is unrecoverable; NimbusDesk backups are disaster-recovery
backups and are not used to restore individual deleted objects.

## Audit log

Audit entries record actor, action, target and source IP. They are append-only
and cannot be deleted by any role, including Owner, before their retention
window elapses. Audit entries are **not** included in a standard workspace
export; request them with the dedicated `audit` export type described in
Data Exports (nd-exports-012).

## What survives a workspace purge

After the 14-day pending-deletion window a workspace purge removes desks,
spaces, members, API keys and webhook endpoints. Two things outlive the purge:

- **Billing records**, retained for 7 years for tax purposes.
- **Audit entries recording the deletion itself**, retained for the normal 400 days.
