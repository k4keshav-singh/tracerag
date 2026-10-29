---
id: nd-troubleshoot-install-013
title: Troubleshooting Installation
version: 2.4
status: current
product_area: troubleshooting
synthetic: true
---

# Troubleshooting Installation

> Synthetic documentation for a fictional product.

## The server exits immediately with `unsupported_database_version`

NimbusDesk 2.4 requires PostgreSQL 15 or newer. The server deliberately refuses
to run against PostgreSQL 14 rather than attempting a migration. Upgrade the
database first; there is no override flag.

## `bind: address already in use` on port 8787

Another process holds the default port. Either stop it or set `[server].port`.
Remember that configuration is read only at start-up, so the server must be
restarted after the change.

## The bootstrap URL says `token_already_redeemed`

Bootstrap URLs are single-use and valid for 60 minutes. Re-run
`nimbusdesk server bootstrap` to mint a new one. Re-running bootstrap on a
workspace that already has an Owner fails with `409 already_bootstrapped`; in
that case use the normal password reset flow instead.

## `healthz` returns 200 but the UI is blank

The API is up and the static assets are not being served. This is almost always
`external_url` being unset or wrong in `nimbusdesk.toml`: the UI bootstraps
itself from that value, and a mismatch leaves the browser requesting assets from
the wrong origin.

## Migrations hang on first boot

NimbusDesk takes an advisory lock before applying migrations so that two servers
starting at once cannot race. A hang usually means a previous process died
holding the lock. Confirm with:

    SELECT * FROM pg_locks WHERE locktype = 'advisory';

Clearing the stale session releases it. Do not delete rows from the migrations
table by hand.

## Clock skew warnings in the log

Webhook signatures and bootstrap URLs are both time-sensitive. A host whose
clock drifts more than 5 minutes from real time will produce signature
verification failures at receivers. Run NTP.
