---
id: nd-cli-018
title: CLI Reference
version: 2.4
status: current
product_area: installation
synthetic: true
---

# CLI Reference

> Synthetic documentation for a fictional product.

`nimbusdesk` is the administrative CLI. It talks to the API over HTTPS and
authenticates with the same scoped API keys as any other client, read from
`NIMBUSDESK_API_KEY` or `~/.config/nimbusdesk/credentials.toml`.

The CLI requires Node.js 20.11 LTS. The server binary does not.

## Global flags

| Flag | Effect |
| --- | --- |
| `--workspace` | Target workspace ID or slug |
| `--output` | `table` (default), `json`, or `csv` |
| `--config` | Path to the server config, for `server` subcommands only |
| `--verbose` | Log each HTTP request, with credentials redacted |

## Commands

### `nimbusdesk server bootstrap`

Creates the first workspace and Owner, printing a single-use setup URL valid for
60 minutes.

### `nimbusdesk apikeys create`

    nimbusdesk apikeys create --workspace ws_8812 \
      --scopes desks:read,exports:create --expires-in 90d

`--expires-in` accepts a duration up to `365d` and defaults to `90d`. The secret
prints once to stdout and is never recoverable afterwards.

### `nimbusdesk exports run`

Starts an export and, with `--wait`, polls until completion and downloads the
archive. Remember the signed download URL is valid for 1 hour even though the
archive is kept for 7 days.

### `nimbusdesk webhooks tail`

Streams recent delivery attempts for an endpoint, including status code and
latency. This reads the same records as `GET /v2/webhooks/{id}/deliveries` and
is therefore limited to the last 30 days.

### `nimbusdesk tunnel`

Opens a temporary HTTPS tunnel to a local port so webhooks can be received in
development. Webhook endpoint URLs must be HTTPS, so plain `http://localhost`
cannot be registered directly; the tunnel exists for exactly this reason.

Tunnels last 8 hours, then close. A closed tunnel's URL is not reused.

### `nimbusdesk config print`

Prints the resolved server configuration with `env:NAME` references left
unexpanded, so the output is safe to paste into a support ticket.
