---
id: nd-exports-012
title: Data Exports
version: 2.4
status: current
product_area: data
synthetic: true
---

# Data Exports

> Synthetic documentation for a fictional product.

Exports produce a downloadable archive of workspace content. Starting an export
requires the `exports:create` scope.

## Export types

| Type | Contents |
| --- | --- |
| `workspace` | Desks, spaces, metadata, attachments |
| `desks` | A named subset of desks |
| `audit` | Audit log entries for a date range |
| `members` | Member list with roles, as CSV |

The `workspace` type does **not** include audit log entries; request those
separately with the `audit` type. This is the most common export surprise.

## Starting an export

    POST /v2/workspaces/ws_8812/exports
    {"type": "workspace", "format": "jsonl"}

Formats are `jsonl` and `csv`. The `workspace` type supports only `jsonl`,
because it contains nested attachment records that do not flatten usefully.

Export creation is limited to **5 per hour per workspace** and is metered
separately from the normal API budget (see Rate Limits, nd-ratelimits-007).

## Completion and download

Exports are asynchronous. Poll `GET /v2/exports/{id}` or subscribe to the
`export.completed` webhook event. A completed export returns a signed download
URL.

**The signed URL is valid for 1 hour, while the export archive itself is
retained for 7 days.** Re-request the export record to mint a fresh URL during
those 7 days; after 7 days the archive is deleted and the export must be re-run.

## Size limits

An export larger than 5 GB is split into numbered parts of at most 5 GB each,
listed in the export record's `parts` array. There is no combined-archive
download; fetch each part.

## Encryption

Supply `"public_key"` with an age-format recipient to have the archive encrypted
before it is written to object storage. NimbusDesk does not retain the plaintext
in that case and cannot help recover an archive whose key was lost.
