# Tooling decisions

Which reconnaissance tools were evaluated for this pipeline, which were
adopted, and why. The deciding question in every case is the same one the
[passive-only constraint](../README.md#design-constraints--why-passive-only)
asks: **does this tool send traffic to the target's own infrastructure?**

Each tool below was installed and run for real, in a throwaway image
extending the production one, against infrastructure the evaluator owned.
Anything that would have touched third-party infrastructure was documented
without being executed.

None of these are wired into the pipeline. This records the evaluation, not
an integration.

## Summary

| Tool | Passive against third parties? | Verdict |
|---|---|---|
| [subjack](#subjack) | **No** — sends HTTP to every subdomain | Not adopted as-is; only its DNS-reading half fits |
| [pymeta](#pymeta) | Yes — reads search indexes, fetches already-published files | Adopted-eligible |
| [crosslinked](#crosslinked) | Yes — reads search indexes only | Adopted-eligible, with rate limits |
| [GitMiner](#gitminer) | **No** — requires an authenticated session | Rejected |

## Where the line sits

A tool is passive here if every byte it collects comes from a third party
that already publishes it: search engine indexes, public DNS, public
repositories, certificate logs. It stops being passive the moment it sends a
request to the target and interprets the response — that is probing, however
gentle the request looks.

This is a property of the tool's mechanism, not of its intent or its
traffic volume. One HTTP GET per subdomain is still one HTTP GET per
subdomain.

A second rule applies to what survives into a report: findings are expressed
as aggregate indicators, not as the raw exploitable detail. "One subdomain
has a dangling CNAME" is an indicator. The hostname an attacker could claim
is the exploit, and it belongs in a technical annex for the system owner,
not in a summary.

---

## subjack

**What it does.** Subdomain takeover detection. Takes a list of subdomains,
resolves each CNAME, and compares the HTTP response against a signature
database of hosting services. A "vulnerable" result means the subdomain
points at an external service that is decommissioned or unclaimed — an
attacker could register it and serve content under the target's domain.

**What it detects.** Dangling DNS assets: phishing under a legitimate
domain, cookie theft, CSP/CORS bypass.

**Output.** One line per host on stdout, plus a file with `-o`. With a
`.json` extension it writes a JSON array of `{subdomain: str, vulnerable:
bool}`. A finding sets `vulnerable: true` and names the service in the text
output.

**Cost.** Roughly 20 s for 10 subdomains, dominated by `-timeout` rather
than CPU. One HTTP request per subdomain; scales linearly. Needs a subdomain
list as input, which `subfinder` already produces.

**Why it is not passive.** subjack reads the CNAME *and then requests the
host* to fingerprint the response. Against infrastructure you own that is
trivial. Against a third party it is an active check and needs written
authorisation from the system owner before it runs. The tool cannot
distinguish the two cases — that is the operator's judgment, made before
invocation, and a pipeline that ships it makes that judgment easy to skip.

**Verdict.** Not adopted as-is. The takeover signal is genuinely valuable
and the tool is cheap and clean, but only its first half is admissible
unattended: reading CNAME records from public DNS is passive, and that alone
identifies a subdomain pointing at an external service. Confirming the
service is unclaimed requires touching the host. The passive half yields a
weaker finding — "points at an external service that may be unclaimed"
rather than "is takeover-able" — and that weaker finding is the honest one
to report without authorisation.

**Install note.** Requires Go, absent from the production image. Signatures
are compiled into the binary in the current version; the `-c
fingerprints.json` flag described in older documentation no longer exists.

---

## pymeta

**What it does.** Extracts metadata from publicly indexed office documents.
Queries search engines for `site:<domain> filetype:pdf|docx|xlsx|…`,
downloads what it finds, and runs `exiftool` over it.

**What it detects.** Passive leakage of internal information through
document metadata: username conventions, software and version numbers,
operating systems, internal file paths, occasionally addresses.

**Output.** Standard exiftool CSV — a `SourceFile` column plus one column
per metadata tag encountered, so the schema varies with the documents. Each
row is prefixed with the source URL.

```
SourceFile,Author,Creator,Producer,Software,CreateDate,Company
report.pdf,jsmith,Microsoft Word,Acrobat,Word 2016,2024:03:01,Example Ltd
```

**Cost.** About 7 s against a target with nothing indexed — 16 search
queries with a 2 s jitter. With documents present, add download time (5
threads by default, capped by `-m`) and one exiftool invocation per file.

**Passive assessment.** Reads search engine indexes and downloads files the
target itself published. It never contacts the target's systems directly —
the documents come from the index and from wherever they are hosted, as any
visitor would fetch them. Admissible against third parties.

The one caution is search engine terms of service rather than the target:
this is scraping, so keep jitter on and volume low.

**Live-run result.** Zero documents indexed for the evaluated target — a
small site publishing no office files. The mechanism was still verified: all
16 queries were emitted and returned HTTP 200 before the tool reported no
results. A zero here is a real finding about the target, not a tool failure.

**Install note.** Requires `exiftool`; without it the tool exits
immediately. Install from git, not PyPI — the PyPI package named `pymeta` is
an unrelated project.

---

## crosslinked

**What it does.** Employee enumeration through search engines. Scrapes
search results for public professional profiles matching an organisation
name, extracts names, and formats them into a likely corporate address
pattern such as `{first}.{last}@domain`.

**What it detects.** Social engineering surface: an enumerable roster plus a
deducible email format.

**Output.** Two files. A `.txt` with one formatted name or address per line,
and a `.csv` with `Datetime, Search, Name, Title, URL, rawText`.

**Cost.** About 32 s against a target with no results — 12 pages from each
of two search engines, 1 s jitter. Low CPU.

**Passive assessment.** It never accesses the professional network directly
and never touches the target's systems; it reads what the search engine
already indexed. Admissible against third parties at low volume, with the
same search-engine terms-of-service caution as pymeta.

**Reporting constraint.** The aggregate indicator is the count and the fact
that the address format is deducible. The nominal list of addresses is the
exploitable artefact and does not belong in a report. Note also that this
output is personal data about individuals who are not the assessment's
subject; what may be done with it afterwards is a separate question from
whether collecting it is passive, and out of scope here.

**Live-run result.** Zero employees found for the evaluated organisation
name — no indexed profile footprint. Queries emitted and returned HTTP 200,
so the mechanism is verified.

---

## GitMiner

**What it does, in theory.** Automated search for leaked credentials, keys
and sensitive files in public repositories, by query plus predefined
modules.

**Why it was rejected.** It does not run without an authenticated session
cookie. The tool checks for `--cookie` before doing anything and prints its
usage otherwise; it scrapes the authenticated web search interface rather
than calling the API. Run without a cookie it re-prints usage and exits,
having emitted no query at all.

No cookie was supplied, deliberately. Three reasons, in order of weight:

1. **It is not passive, and not anonymous.** An authenticated session ties
   every query to a real, identifiable account. That is a different activity
   from reading public data, regardless of what the query returns.
2. **It violates the platform's terms of service.** Scraping the
   authenticated search interface risks suspension of whatever account is
   used — a cost borne by the operator, for data that is available
   legitimately elsewhere.
3. **It is fragile.** The tool is old enough to emit syntax warnings on
   current Python, and it depends on the search page's HTML, which changes
   without notice.

The first reason alone is disqualifying. The other two mean that even
setting the constraint aside, this is not the way to get the signal.

**Alternative, if the indicator is wanted.** The platform's official code
search API, with a token, inside its documented rate limits. It covers the
same objective — public references to the target's domain — legitimately and
stably, in sub-second queries. The aggregate indicator would be the count of
public references, without exposing the matched snippet.

---

## What this evaluation concluded

- **pymeta** and **crosslinked** are the clean candidates: both read only
  what third parties already publish.
- **subjack** produces a valuable signal but cannot be run unattended
  against third-party infrastructure. Adopting it would mean splitting it —
  keeping the DNS read, dropping the HTTP fingerprint — and accepting a
  weaker, honestly-stated finding.
- **GitMiner** is rejected. Where the signal is wanted, use the official
  API rather than authenticated scraping.
- Whatever is integrated, the report exposes aggregate indicators rather
  than the raw exploitable detail.

None of the above is in the pipeline today. The point of recording it is
that the passive-only constraint has already cost this project a tool it
wanted and reduced another to half its capability — which is what a
constraint looks like when it is real rather than declared.
