---
id: nd-webhooks-009
title: Webhooks
version: 2.4
status: current
product_area: webhooks
synthetic: true
---

# Webhooks

> Synthetic documentation for a fictional product.

Webhooks push workspace events to an HTTPS endpoint you control. Creating or
modifying an endpoint requires the `webhooks:admin` scope.

## Creating an endpoint

    POST /v2/workspaces/ws_8812/webhooks
    {
      "url": "https://hooks.example.com/nimbus",
      "events": ["desk.created", "desk.updated"],
      "description": "Primary sink"
    }

The URL must be HTTPS. Plain HTTP is rejected with `400 insecure_url`, including
for `localhost`; use the CLI tunnel for local development.

A workspace may have at most 50 active endpoints (see Workspaces, nd-workspaces-003).

## Event types

| Event | Fires when |
| --- | --- |
| `desk.created` | A desk is created |
| `desk.updated` | A desk's fields or contents change |
| `desk.deleted` | A desk is moved to the recycle bin |
| `member.invited` | An invitation is sent |
| `member.role_changed` | A member's role changes |
| `export.completed` | An export finishes and is ready to download |
| `apikey.expiring` | An API key is 7 days from expiry |

`desk.deleted` fires on the move to the recycle bin, not on the later permanent
purge. There is no event for permanent purge.

## Payload signing

Every delivery carries an `X-Nimbus-Signature` header:

    X-Nimbus-Signature: t=1716300000,v1=5257a869e7...

`v1` is the hex HMAC-SHA256 of the string `"{t}.{raw_body}"` using the endpoint's
signing secret. Verify against the **raw** request body, before any JSON parsing
or re-serialisation.

Reject a delivery whose `t` is more than **5 minutes** from your clock. NimbusDesk
re-signs on every retry, so `t` always reflects the current attempt, not the
original one.

## Ordering

Deliveries are **not ordered**. Two events for the same desk may arrive out of
order, and a retry of an earlier event may land after a later one. Every payload
carries `event_id` and `occurred_at`; use them to order and deduplicate.

Delivery behaviour, timeouts and the retry schedule are covered in
Webhook Delivery and Retries (nd-webhook-retries-010).
