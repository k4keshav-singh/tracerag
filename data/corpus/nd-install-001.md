---
id: nd-install-001
title: Installing NimbusDesk Server
version: 2.4
status: current
product_area: installation
synthetic: true
---

# Installing NimbusDesk Server

> Synthetic documentation for a fictional product. NimbusDesk does not exist.

NimbusDesk Server is distributed as a single self-contained binary and as an OCI
image. This page covers a first-time install of release 2.4 on a single host.

## System requirements

| Component | Minimum | Recommended |
| --- | --- | --- |
| CPU | 2 vCPU | 4 vCPU |
| Memory | 4 GB RAM | 8 GB RAM |
| Disk | 20 GB SSD | 100 GB SSD |
| PostgreSQL | 15.0 | 16.x |
| Node.js (for the CLI only) | 20.11 LTS | 20.11 LTS |

NimbusDesk Server 2.4 does not support PostgreSQL 14 or earlier. The installer
refuses to start against an unsupported database rather than migrating it.

## Install the binary

Download the release archive and verify its checksum before extracting:

    curl -LO https://downloads.nimbusdesk.example/2.4.0/nimbusdesk-linux-amd64.tar.gz
    sha256sum -c nimbusdesk-linux-amd64.tar.gz.sha256
    tar -xzf nimbusdesk-linux-amd64.tar.gz -C /usr/local/bin

## Prepare the database

Create a dedicated role and database. NimbusDesk applies its own migrations on
first boot and requires ownership of the schema it manages:

    createuser --pwprompt nimbusdesk
    createdb --owner nimbusdesk nimbusdesk

## First boot

The server listens on port 8787 by default. The bootstrap command creates the
first workspace and its Owner account:

    nimbusdesk server bootstrap --config /etc/nimbusdesk/nimbusdesk.toml

Bootstrap prints a one-time setup URL valid for 60 minutes. The URL can only be
redeemed once; re-run bootstrap if it expires.

## Verify the install

    curl -fsS http://localhost:8787/healthz

A healthy server returns `{"status":"ok"}` together with the schema revision. If
the health check fails, see Troubleshooting Installation (nd-troubleshoot-install-013).
