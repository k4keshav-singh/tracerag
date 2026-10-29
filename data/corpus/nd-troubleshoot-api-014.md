---
id: nd-troubleshoot-api-014
title: Troubleshooting API Errors
version: 2.4
status: current
product_area: troubleshooting
synthetic: true
---

# Troubleshooting API Errors

> Synthetic documentation for a fictional product.

## `401 unsupported_auth_scheme`

The request used the 2.3 `X-Nimbus-Token` header. Release 2.4 accepts only
`Authorization: Bearer` with a scoped API key. See API Authentication
(nd-auth-005).

## `401 key_expired`

API keys expire 90 days after creation by default. Keys within 7 days of expiry
return a `Warning: 299` header on every response, and the `apikey.expiring`
webhook event fires at the same 7-day mark. Both exist so this failure is never
a surprise; if it was, nobody was reading the warnings.

## `401 key_rotated`

The request used a secret that was replaced by a rotation more than 24 hours
ago. The rotation grace window is 24 hours and cannot be extended. Deploy the
new secret.

## `403 insufficient_scope`

The key authenticated but lacks the scope for this route. The response body
names the scope required. Scopes cannot be added to an existing key: create a
replacement key with the wider scope and revoke the old one.

## `429 rate_limited`

Check `X-RateLimit-Scope` in the response. When it is absent the request drew on
the workspace budget of 600 requests per minute; when it is present, it names a
separately metered family such as exports. Honour `Retry-After`: retrying early
is always rejected.

## `400 cursor_expired`

Cursors live for 15 minutes. A paginated walk that pauses longer than that
cannot be resumed and must restart. If walks routinely take longer, raise
`limit` toward the 200 maximum so fewer pages are needed.

## `400 unsupported_parameter` on a list endpoint

Offset pagination was removed in 2.4. Replace `?page=` or `?offset=` with
cursor pagination (nd-pagination-008).

## `409 limit_exceeded` when creating a webhook endpoint

The workspace is at the hard limit of 50 active endpoints. Delete or disable an
unused endpoint. Disabled endpoints still count toward the limit; delete them to
free a slot.
