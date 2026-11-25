# External retrieval benchmark

This optional benchmark measures public retrieval services independently of Lean
proof search. Settings are in the ignored local `.env`; reproducible queries are
in `configs/retrieval-api-benchmark.json`; reports go in `runs/`.
No new API keys or paid tactic calls are needed. Offline proof training stays the default.

## Services

| Service | Endpoint | Authentication | What is measured |
|---|---|---|---|
| Stacks Project | `/data/tag/{tag}/content/statement` | No key documented | Statement-only HTML lookup for a known tag |
| LeanExplore | `/api/v2/search?q=...&limit=5&packages=Mathlib` | No key currently required | Natural-language Lean declaration search |
| Loogle | `/json?q=...` | No key documented | Lean declaration/name search |

Official sources checked 2026-11-25:
[Stacks API](https://stacks.math.columbia.edu/api),
[LeanExplore client documentation](https://github.com/lean-explore/lean-explore/blob/main/docs/api-client.md),
[LeanExplore client implementation](https://github.com/lean-explore/lean-explore/blob/main/src/lean_explore/api/client.py),
and [Loogle README](https://github.com/nomeata/loogle#web-service).
Older LeanExplore instructions requesting a key do not describe its current client.

Stacks documents an unstable API and asks prospective users to contact its maintainers.
Its adapter is configured with `AI4ALGEBRA_STACKS_API_ENABLED=false` until that
coordination is complete. No message has been sent on the user's behalf.
The existing pinned Git source importer remains the reproducible offline training source.

## Run

```powershell
# Dry run: validate configuration and queries; send no requests.
uv run python -m ai4algebra.api_benchmark --queries configs/retrieval-api-benchmark.json --output runs/retrieval-api-dry/report.json

# Explicit online retrieval run; Stacks remains skipped while disabled in .env.
uv run python -m ai4algebra.api_benchmark --live --queries configs/retrieval-api-benchmark.json --output runs/retrieval-api-live/report.json
```

Use `--service leanexplore`, `--service loogle`, or `--service stacks` to select
one adapter, and `--dotenv PATH` to choose a different settings file. Real process
environment values override `.env`. URLs may use HTTPS or local HTTP for a self-hosted
service. Requests are sequential, rate-spaced, response-size bounded, and have connection
and response timeouts; there are no hidden retries or redirects. Operating-system DNS
resolution is not interruptible by this timeout. The benchmark uses only its own
settings from `.env` and transmits no credentials.

## Interpretation

The nine initial cases cover three Stacks tags and three elementary algebra topics
for each Lean search service: multiplicative identity, additive commutativity,
and distributivity. LeanExplore uses natural language; Loogle uses quoted name
fragments. They are different query tasks, so their aggregate scores are not a fair
head-to-head semantic-search comparison.

Reports separate request success, nonempty responses, latency, returned declaration
names, and response hashes. Exact-name labels provide diagnostic hit@k and reciprocal
rank for the six Lean cases; they are incomplete relevance judgments. Stacks tag
lookups have no ranking score. An HTTP or parsing failure is not a failed Lean proof;
an empty search result is not an infrastructure failure. Tiny single-run latency
samples do not establish throughput or stable performance.

Success rate uses attempted requests as its denominator; nonempty rate uses valid
responses. Median latency includes failed attempts but excludes intentional spacing
and parsing. Hit@k and MRR@k use labeled, successfully parsed searches; valid empty
searches count as misses. Always read `scored_query_count` alongside
`labeled_query_count`, since errors and skipped requests are not ranking observations.

Remote results are untrusted, may use a different Mathlib revision, and never become
proof candidates automatically. No remote proof bodies are stored or executed.
The benchmark does not access protected reference proofs, train the DDQN, or update
return memory. In particular, fetching a held-out Stacks statement is not a verified
formalization or proof. Future premise integration must apply the existing split,
alias, dependency, pinned-environment, applicability and final replay checks.

## Recorded smoke run

The final setup smoke on 2026-11-25 at 23:10 UTC used the nine unchanged queries,
default endpoints and k=5. The [live report](../runs/retrieval-api-live/report.json)
records LeanExplore 3/3 successful nonempty responses (median 1.82 seconds) and
Loogle 3/3 (median 1.32 seconds). Both scored 0/3 exact expected-name hits in the
top five. Related or specialized declarations do not count as the requested generic
declaration; these labels were not changed after seeing results. All three Stacks
requests were skipped because the adapter was disabled. The
[dry-run report](../runs/retrieval-api-dry/report.json) records nine skipped queries
and zero requests. No paid API calls were made.

## Next benchmark expansion

Keep retrieval availability and theorem-proving success as separate experiments.
For the next offline corpus expansion, curate additional group identities, inverse
and cancellation arguments, ring distributivity/subtraction, and proofs with multiple
goals. Assign semantic families to splits before running search; exclude equivalent
targets and imported answers. Validate each reference certificate independently.
Freeze candidate settings and training checkpoints before held-out evaluation, then
report distinct tasks, family/category coverage, proof depth, probe costs, failure
reasons and per-seed comparisons across deterministic, DDQN and retrieval-guided modes.
Do not infer a learned advantage from the current tiny successful examples.

The earlier 348-test acceptance and frozen training runs are historical evidence for
their recorded source digest. Adding this module changes that digest; do not relabel
old artifacts as current-source training runs or bypass the loader's identity checks.
