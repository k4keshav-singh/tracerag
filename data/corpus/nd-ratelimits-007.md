---
id: nd-ratelimits-007
title: Rate Limits
version: 2.4
status: current
product_area: api
synthetic: true
---

# Rate Limits

> Synthetic documentation for a fictional product.

NimbusDesk applies rate limits per workspace, not per API key. Ten keys in one
workspace share one budget.

## The default budget

The default sustained limit is **600 requests per minute per workspace**, with a
**burst capacity of 120 requests**. The limiter is a token bucket: the bucket
holds at most 120 tokens and refills at 10 tokens per second.

Self-hosted operators may lower these values in `[limits]` (see Configuration
Reference, nd-config-002). Raising them above the defaults is not supported.

## Response headers

Every API response carries the current budget state:

| Header | Meaning |
| --- | --- |
| `X-RateLimit-Limit` | Sustained limit per minute |
| `X-RateLimit-Remaining` | Tokens currently left in the bucket |
| `X-RateLimit-Reset` | Unix seconds until the bucket is full again |

## Being limited

An over-budget request is rejected with `429 rate_limited` and a `Retry-After`
header in whole seconds. `Retry-After` is advisory but accurate: retrying before
it elapses will be rejected again and the rejection itself consumes no tokens.

## Endpoints with their own budgets

Three endpoint families are metered separately and do **not** draw on the 600/min
workspace budget:

| Endpoint family | Limit |
| --- | --- |
| `POST /v2/exports` | 5 per hour per workspace |
| `POST /v2/api-keys/*/rotate` | 10 per hour per workspace |
| `POST /v2/webhooks/*/test` | 60 per hour per endpoint |

Exceeding one of these returns `429 rate_limited` with a `X-RateLimit-Scope`
header naming the family, so clients can tell which budget they exhausted.

## Rate limits and webhook delivery

Outbound webhook delivery is not metered by this limiter at all. Webhook
delivery has its own concurrency control, described in Webhook Delivery and
Retries (nd-webhook-retries-010).
