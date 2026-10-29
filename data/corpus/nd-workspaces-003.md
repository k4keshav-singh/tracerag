---
id: nd-workspaces-003
title: Workspaces
version: 2.4
status: current
product_area: workspaces
synthetic: true
---

# Workspaces

> Synthetic documentation for a fictional product.

A workspace is the unit of isolation in NimbusDesk. Every document, automation,
API key and webhook endpoint belongs to exactly one workspace. Nothing is shared
between workspaces implicitly.

## Structure

Workspaces contain **spaces**, and spaces contain **desks**. A desk is the
object end users actually work in. The hierarchy is fixed at three levels; there
are no nested spaces.

    workspace
      +- space
           +- desk

## Workspace slugs

Each workspace has an immutable numeric ID and a mutable human-readable slug.
API routes accept either form: `/v2/workspaces/ws_8812/desks` and
`/v2/workspaces/acme-support/desks` resolve to the same workspace.

Renaming a slug does not break existing API keys, which are bound to the numeric
ID. It does break hard-coded URLs in external systems, so the old slug is
reserved for 30 days after a rename and returns `308 Permanent Redirect` to the
new one during that window.

## Limits per workspace

| Object | Soft limit | Hard limit |
| --- | --- | --- |
| Spaces | 200 | 500 |
| Desks per space | 1,000 | 5,000 |
| Active webhook endpoints | 25 | 50 |
| Active API keys | 50 | 100 |

Crossing a soft limit raises a warning banner for workspace Admins. Crossing a
hard limit causes creation requests to fail with `409 limit_exceeded`.

## Deleting a workspace

Deletion is a two-phase operation. The workspace is first marked `pending_delete`
and becomes read-only; after the grace period it is purged. The grace period is
14 days and is not configurable. See Data Retention (nd-retention-011) for what
survives a purge and for how long.
