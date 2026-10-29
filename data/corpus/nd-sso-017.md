---
id: nd-sso-017
title: SSO and SCIM Provisioning
version: 2.4
status: current
product_area: workspaces
synthetic: true
---

# SSO and SCIM Provisioning

> Synthetic documentation for a fictional product.

NimbusDesk supports SAML 2.0 single sign-on and SCIM 2.0 user provisioning.
Both are configured per workspace by an Owner; Admins can view the configuration
but not change it.

## SAML

`external_url` must be set before SSO can be enabled, because the ACS URL is
derived from it. The ACS URL is `{external_url}/sso/saml/acs` and the entity ID
is `{external_url}/sso/saml/metadata`.

NimbusDesk requires signed assertions. Signed *responses* are accepted but not
required. Encrypted assertions are not supported in 2.4.

## Enforcing SSO

Enforcement is off by default. When enabled, password login is disabled for all
members **except Owners**, who retain a password path so a misconfigured identity
provider cannot lock the workspace out permanently. This exemption cannot be
turned off, and it is the usual answer to "we enforced SSO but Owners can still
use passwords".

API keys are unaffected by SSO enforcement. They authenticate machine traffic
and continue to work regardless.

## SCIM

The SCIM base URL is `{external_url}/scim/v2`. SCIM uses its own bearer token,
generated in workspace settings, which is **not** an API key: it is not listed
by `/v2/api-keys`, carries no scopes, and does not expire after 90 days. It is
revoked by regenerating it.

### Supported operations

| Operation | Supported |
| --- | --- |
| Create user | yes |
| Update user attributes | yes |
| Deactivate user (`active: false`) | yes |
| Hard delete user | no |
| Group push | yes, mapped to roles |

A SCIM deactivation suspends the member and frees the seat; it does not delete
their audit history. Hard delete via SCIM is rejected with `400 unsupported_operation`.

### Role mapping

Group push maps an identity-provider group to one of the six built-in roles. A
member in two mapped groups receives the **more permissive** of the two roles.
Guests cannot be provisioned over SCIM.
