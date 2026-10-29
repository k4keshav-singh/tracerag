---
id: nd-changelog-015
title: Release Notes
version: 2.4
status: current
product_area: releases
synthetic: true
---

# Release Notes

> Synthetic documentation for a fictional product.

## 2.4.0

**Breaking changes**

- API v1 and the `X-Nimbus-Token` header are removed. All clients must use
  `Authorization: Bearer` with a scoped API key (nd-auth-005).
- Static workspace tokens no longer exist. Scoped API keys expire after 90 days
  by default, with a maximum of 365 days.
- Offset pagination (`?page=`, `?offset=`) is removed; list endpoints are
  cursor-only (nd-pagination-008).
- PostgreSQL 14 is no longer supported. Minimum is PostgreSQL 15.

**Added**

- Six built-in roles, replacing the 2.3 Admin/Member split. Maintainer is the
  new lowest role that can mint API keys.
- Per-family rate limit budgets for exports, key rotation and webhook tests,
  surfaced through `X-RateLimit-Scope`.
- `apikey.expiring` webhook event, fired 7 days before a key expires.
- Age-encrypted exports via the `public_key` field.

**Changed**

- Webhook retry schedule lengthened: 6 retries over a little under 9 hours,
  abandoned at 24 hours. 2.3 retried 3 times over 15 minutes.
- Audit log retention raised from 180 days to 400 days.
- Export archive retention shortened from 14 days to 7 days.

## 2.3.4

- Fixed a bug where a rotated workspace token could be accepted after
  revocation.
- Webhook delivery timeout raised from 5 to 10 seconds.

## 2.3.0

- Introduced workspace tokens with optional IP allowlists.
- Added the recycle bin with a fixed 30-day window.
