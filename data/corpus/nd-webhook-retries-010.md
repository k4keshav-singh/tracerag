---
id: nd-webhook-retries-010
title: Webhook Delivery and Retries
version: 2.4
status: current
product_area: webhooks
synthetic: true
---

# Webhook Delivery and Retries

> Synthetic documentation for a fictional product.

This page covers what happens after NimbusDesk decides to send a webhook. For
endpoint setup, event types and signature verification see Webhooks (nd-webhooks-009).

## What counts as success

A delivery succeeds on any 2xx response. Every other outcome is a failure and is
retried: 3xx (redirects are never followed), 4xx, 5xx, connection errors and
timeouts alike.

The per-attempt timeout is **10 seconds**, measured from connection start to the
response headers. A slow body after fast headers does not fail the delivery.

## The retry schedule

A failed delivery is retried **up to 6 times** after the initial attempt, for 7
attempts in total. Backoff is exponential with jitter:

| Attempt | Nominal delay after previous |
| --- | --- |
| 1 (initial) | - |
| 2 | 5 seconds |
| 3 | 30 seconds |
| 4 | 5 minutes |
| 5 | 30 minutes |
| 6 | 2 hours |
| 7 | 6 hours |

Each delay carries up to 10% random jitter. The whole schedule spans a little
under 9 hours. A delivery is abandoned once the 7th attempt fails, **or** once it
is 24 hours old, whichever comes first.

Note the distinction that trips people up: the *retry count* is 6 and the
*attempt count* is 7, because the initial attempt is not a retry.

## Automatic disabling

An endpoint that fails **every** delivery for 72 consecutive hours is
automatically disabled, and a `webhook.endpoint_disabled` notification is sent
to workspace Admins by email. A disabled endpoint stops receiving events
entirely; events that occur while it is disabled are not queued and cannot be
backfilled.

Re-enable with `POST /v2/webhooks/{id}/enable`. A single successful delivery
resets the 72-hour counter.

## Concurrency

NimbusDesk delivers at most **4 concurrent requests per endpoint**. This is
independent of the workspace API rate limit described in Rate Limits
(nd-ratelimits-007); outbound deliveries never consume the inbound 600/min
budget.

## Inspecting deliveries

`GET /v2/webhooks/{id}/deliveries` lists recent attempts with status code,
latency and response body excerpt. Delivery records are kept for **30 days**.
`POST /v2/webhooks/{id}/deliveries/{delivery_id}/replay` re-sends one payload;
a replay is a fresh delivery with its own retry schedule.
