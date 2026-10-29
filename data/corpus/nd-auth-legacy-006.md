---
id: nd-auth-legacy-006
title: Legacy API Authentication (Workspace Tokens)
version: 2.3
status: superseded
superseded_by: nd-auth-005
product_area: api
synthetic: true
---

# Legacy API Authentication (Workspace Tokens)

> **Superseded.** This page documents NimbusDesk 2.3 and earlier. It is retained
> for operators still running 2.3. For release 2.4 and later see
> API Authentication (nd-auth-005), which replaces everything below.

NimbusDesk API v1 authenticated requests with **static workspace tokens**.

## Presenting a token

    curl https://nimbus.example.com/v1/workspaces/ws_8812/desks \
      -H "X-Nimbus-Token: nwt_1b9c..."

The header is `X-Nimbus-Token`. API v1 did not accept `Authorization: Bearer`.

## Token lifetime

**Workspace tokens do not expire.** A token issued in 2.1 remained valid
indefinitely until an Admin revoked it. There was no rotation grace window and
no expiry warning header, because there was no expiry.

This behaviour is the single largest difference from 2.4 and is why upgrading
workspaces see integrations stop working 90 days after migration if they were
not re-issued as scoped API keys.

## Token permissions

Workspace tokens were not scoped. Every token carried the full permissions of
the workspace, equivalent to an Admin. The granular scope list introduced in 2.4
has no equivalent in v1.

## Migration

API v1 and the `X-Nimbus-Token` header were removed in 2.4.0. See
Migrating to 2.4 (nd-migration-016) for the replacement procedure.
