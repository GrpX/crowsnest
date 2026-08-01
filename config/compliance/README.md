# Compliance frameworks

The report engine does not hardcode any compliance framework. Each framework
is one file in this directory, and the active one is selected at report time.

## Selecting the active framework

In order of precedence:

1. `--compliance <id>` on `scripts/nuclei_to_report.py`
2. the `COMPLIANCE_FRAMEWORK` environment variable
3. if this directory holds exactly one framework file, that one

If several frameworks are present and none is selected, the engine stops and
lists the available ids rather than guessing.

## File format

One YAML file per framework. The filename is free; the `id` field is what
selects it.

```yaml
id: my-framework            # selector, must be unique
name: My Framework v1       # shown in the report
reference: https://…        # optional, rendered as the source link
description: >-
  One paragraph describing what the framework covers.

mapping:                    # finding category -> applicable control
  email_security:
    control: "Control identifier and title"
    url: https://…          # optional
    note: >-                # optional, why this control applies
      Short explanation.

default:                    # used when a finding's category is not mapped
  control: "…"
  url: https://…
  note: >-
    …
```

## Finding categories

The keys under `mapping` are the `category` values the engine assigns to
findings. The ones currently emitted are:

| Category | Meaning |
|---|---|
| `email_security` | SPF, DKIM, DMARC, MTA-STS, mail transport |
| `misconfiguration` | Missing security headers, default configs, listable dirs |
| `exposure` | Admin panels, internal endpoints, files reachable unauthenticated |
| `encryption` | Missing TLS, obsolete protocols, invalid certificates |
| `vulnerability` | Components with known CVEs |
| `information_disclosure` | Metadata or errors revealing internal details |

A category with no entry in `mapping` falls back to `default`. Adding a
category to the engine without adding it here is not an error — the finding
still appears in the report, mapped to the default control.

## Adding a framework

1. Copy `owasp-top10.yaml`, change `id`, `name` and `reference`.
2. Rewrite `mapping` so every category points at the matching control.
3. Select it with `--compliance <id>` or `COMPLIANCE_FRAMEWORK=<id>`.

The bundled `owasp-top10` uses a public, neutral taxonomy on purpose: it maps
findings to technical controls without requiring any legal interpretation.
Frameworks that restate regulation are the author's responsibility — the
engine only renders what the file declares.
