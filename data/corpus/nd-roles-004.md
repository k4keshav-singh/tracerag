---
id: nd-roles-004
title: Roles and Permissions
version: 2.4
status: current
product_area: workspaces
synthetic: true
---

# Roles and Permissions

> Synthetic documentation for a fictional product.

NimbusDesk defines six built-in roles. Roles are assigned per workspace; a
person may hold different roles in different workspaces. Custom roles are not
supported in 2.4.

## The six roles

| Role | Manage billing | Manage members | Manage API keys | Edit desks | Read desks |
| --- | --- | --- | --- | --- | --- |
| Owner | yes | yes | yes | yes | yes |
| Admin | no | yes | yes | yes | yes |
| Maintainer | no | no | yes | yes | yes |
| Contributor | no | no | no | yes | yes |
| Viewer | no | no | no | no | yes |
| Guest | no | no | no | limited | limited |

A workspace must have at least one Owner at all times. Removing the last Owner
fails with `409 last_owner`.

## Guest scope

A Guest sees only the specific desks they have been invited to, never the full
space listing. Guests cannot be granted workspace-wide permissions; promoting a
Guest converts them into a full member and consumes a seat.

## Who can create API keys

Maintainer is the lowest role that can create an API key, and a key can never
carry a scope its creator does not hold. A Maintainer therefore cannot mint a
key with `members:write`. See API Authentication (nd-auth-005) for the scope
list.

## Role changes and active sessions

A role change takes effect on the member's next request. Existing browser
sessions are not invalidated, but every request re-evaluates permissions, so a
demoted member loses access immediately in practice. API keys are a different
matter: their scopes are fixed at creation and are **not** narrowed when the
creator is demoted. Revoke the key explicitly.
