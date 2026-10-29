---
id: nd-migration-016
title: Migrating to 2.4
version: 2.4
status: current
product_area: releases
synthetic: true
---

# Migrating to 2.4

> Synthetic documentation for a fictional product.

Upgrading from 2.3 is a one-way migration. Take a database backup first; there
is no supported downgrade path once 2.4 migrations have run.

## Before you upgrade

1. **Move to PostgreSQL 15 or newer.** 2.4 refuses to start otherwise.
2. **Inventory your workspace tokens.** `nimbusdesk tokens list --all-workspaces`
   prints every v1 token with its last-used timestamp. Tokens unused for 90 days
   are usually safe to drop rather than migrate.
3. **Set `external_url`.** It was optional in 2.3 and is required in 2.4 for
   webhooks and SSO.

## Replacing tokens with API keys

There is no automatic conversion, and this is deliberate: workspace tokens
carried full Admin permissions, so converting them would mint over-privileged
keys. Each integration needs a key with the narrowest scope that works.

    nimbusdesk apikeys create \
      --workspace ws_8812 \
      --scopes desks:read,desks:write \
      --expires-in 365d

The single behaviour change that breaks integrations silently is expiry: v1
tokens never expired, and the replacement keys do. A key created with the
default expiry stops working 90 days after the migration. Set `--expires-in`
deliberately and subscribe to `apikey.expiring`.

## Pagination clients

Any client passing `?page=` or `?offset=` breaks at upgrade with
`400 unsupported_parameter`. Switch to cursors before upgrading, not after: the
cursor endpoints already exist in 2.3.4 and work identically there.

## Webhook receivers

The retry schedule is much longer in 2.4 (6 retries spanning nearly 9 hours,
abandoned at 24 hours) than the 2.3 schedule of 3 retries over 15 minutes.
Receivers that were effectively idempotent because retries arrived within
minutes may now see a retry arrive hours later. Deduplicate on `event_id`.

## Rollback

If 2.4 must be rolled back, restore the pre-upgrade database backup and
reinstall the 2.3 binary. Data written by 2.4 after the upgrade is lost. There
is no in-place downgrade.
