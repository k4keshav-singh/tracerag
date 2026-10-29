---
id: nd-pagination-008
title: Pagination
version: 2.4
status: current
product_area: api
synthetic: true
---

# Pagination

> Synthetic documentation for a fictional product.

All NimbusDesk list endpoints are cursor-paginated. Offset pagination
(`?page=` / `?offset=`) was removed in 2.4 and now returns `400 unsupported_parameter`.

## Requesting a page

    GET /v2/workspaces/ws_8812/desks?limit=50&cursor=eyJvIjoxMjN9

`limit` defaults to **50** and the maximum accepted value is **200**. A `limit`
above 200 is not an error: the server clamps it to 200 and notes the clamp in
the response envelope.

## Response envelope

    {
      "data": [ ... ],
      "page": {
        "next_cursor": "eyJvIjoxNzN9",
        "has_more": true,
        "limit_applied": 50
      }
    }

`next_cursor` is `null` when `has_more` is `false`. Do not parse cursors: they
are opaque base64 and their contents change between releases.

## Cursor stability

Cursors are **keyset** cursors over an immutable sort key, so items inserted
during a walk never cause an item to be skipped or repeated. Items *deleted*
during a walk simply disappear from later pages.

A cursor stays valid for 15 minutes. An expired cursor returns
`400 cursor_expired`, and the walk must restart from the beginning. There is no
way to resume an expired walk.

## Sorting

`sort` accepts `created_at` or `updated_at`, each with `:asc` or `:desc`. The
default is `created_at:desc`. The sort key cannot be changed mid-walk: passing a
different `sort` with an existing cursor returns `400 cursor_sort_mismatch`.

## Counting

List endpoints do not return a total count. `GET /v2/.../count` is a separate
endpoint, is rate limited as a normal API call, and returns an estimate that may
lag writes by up to 60 seconds.
