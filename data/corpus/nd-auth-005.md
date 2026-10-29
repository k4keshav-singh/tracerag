---
id: nd-auth-005
title: API Authentication
version: 2.4
status: current
supersedes: nd-auth-legacy-006
product_area: api
synthetic: true
---

# API Authentication

> Synthetic documentation for a fictional product.
> This page replaces Legacy API Authentication (nd-auth-legacy-006), which
> described static workspace tokens and is no longer accurate for release 2.4.

NimbusDesk API v2 authenticates requests with **scoped API keys** presented as a
bearer token.

## Presenting a key

    curl https://nimbus.example.com/v2/workspaces/ws_8812/desks \
      -H "Authorization: Bearer ndk_live_7f3a..."

The header is `Authorization: Bearer`. The 2.3-era `X-Nimbus-Token` header is
rejected in 2.4 with `401 unsupported_auth_scheme`.

## Key format and expiry

Keys are prefixed `ndk_live_` or `ndk_test_`. The secret is shown exactly once at
creation; NimbusDesk stores only a hash and cannot recover it.

**API keys expire 90 days after creation by default.** The expiry is chosen at
creation time and may be set to any value up to a maximum of 365 days.
Non-expiring keys are not available in 2.4. This is the most common upgrade
surprise for workspaces moving from 2.3, where workspace tokens did not expire
at all.

A key that is within 7 days of expiry still works, but every response carries a
`Warning: 299 - "api key expires at <timestamp>"` header.

## Scopes

| Scope | Grants |
| --- | --- |
| `desks:read` | Read desks and their contents |
| `desks:write` | Create and modify desks |
| `members:read` | List workspace members |
| `members:write` | Invite, remove and re-role members |
| `webhooks:admin` | Manage webhook endpoints |
| `exports:create` | Start and download exports |

Scopes are additive and are fixed at creation. There is no way to widen an
existing key; create a replacement and revoke the old one.

## Rotation

`POST /v2/api-keys/{id}/rotate` issues a new secret for the same key record and
starts a grace window during which both secrets are accepted. The grace window
is 24 hours and is not configurable. After it closes the previous secret is
rejected with `401 key_rotated`.

## Revocation

Revocation is immediate and is not subject to any grace window. A revoked key
returns `401 key_revoked`.
