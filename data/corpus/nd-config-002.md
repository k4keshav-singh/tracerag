---
id: nd-config-002
title: Configuration Reference
version: 2.4
status: current
product_area: installation
synthetic: true
---

# Configuration Reference

> Synthetic documentation for a fictional product.

NimbusDesk Server reads a single TOML file. The default path is
`/etc/nimbusdesk/nimbusdesk.toml`; override it with `--config` or the
`NIMBUSDESK_CONFIG` environment variable.

Configuration is read once at process start. Changing the file does not take
effect until the server is restarted, with the single exception of
`[logging].level`, which is re-read on SIGHUP.

## [server]

    [server]
    bind = "0.0.0.0"
    port = 8787
    external_url = "https://nimbus.example.com"
    request_timeout_seconds = 30

`external_url` must be set before webhooks or SSO are enabled; NimbusDesk uses
it to build callback URLs and signature payloads.

## [database]

    [database]
    url = "postgres://nimbusdesk@localhost:5432/nimbusdesk"
    pool_size = 20
    statement_timeout_seconds = 15

## [limits]

These values tune the per-workspace request budget described in Rate Limits
(nd-ratelimits-007). Lowering them below the documented defaults is supported;
raising them above is not, and the server logs a warning at start-up.

    [limits]
    requests_per_minute = 600
    burst = 120

## [logging]

    [logging]
    level = "info"
    format = "json"
    redact_authorization_header = true

`redact_authorization_header` defaults to `true` and should stay enabled.
NimbusDesk never writes API key material or bearer tokens to the request log
while it is on.

## Secrets

Any value may be replaced by an environment reference of the form `env:NAME`.
Secrets are resolved at start-up and are never echoed by
`nimbusdesk config print`, which prints `env:NAME` verbatim instead.
