# Recovering the quiet-service question

## Cause and focused change

For “Will a quiet service show zero availability when nobody is using it?”,
hybrid retrieval already ranks the correct no-traffic passage first. Its hybrid
score is about `0.381`, above the existing `0.35` prefilter. The reranker gives
that passage about `-8.879`, below the unchanged `-1.0` rejection threshold.
The failure is in reranking rather than candidate recall.

Removing Markdown formatting and scoring shorter passage windows did not recover
it. A curated operations alias does: retry “quiet service”, “quiet application”
or “quiet app” as “idle application”, preserving plural forms and adjusting “a”
to “an”. The probe's retry score is about `-0.010`, passing the same cutoff.

The shared reranking function now follows this order:

1. Apply the existing literal cloud-ID and duration evidence guards.
2. Score the original question against the existing candidates.
3. If any candidate passes, return those results normally without a retry.
4. If none passes and the question contains the bounded alias phrase, rerank
   the same candidates once with the alias. Keep the same rejection threshold
   and three-result limit. If this also fails, return no evidence.

No new chunks or answers are invented. Embedding search still runs once with the
original question. Context uses the original source text and chunk/source IDs.
The alias is confined to an extra local reranker call; retry failures propagate
as service errors rather than pretending evidence is absent.

The policy is recorded as `quiet-service-alias-v1`. Successful retry results in
evaluation JSON include `rerank_query`, identifying which wording produced their
score. The API response schema is unchanged; its score can now come from the
original or retry wording. This is a relevance score, not an answer-confidence
probability. No new index format or rebuild is required for this update.

## Local results on 2026-10-27

The embedding/reranker models, 194-chunk index, candidate limits, literal guards
and thresholds are unchanged. All original 32 questions, the previous 12 probes,
the four Markdown snapshots and historical reports are preserved byte-for-byte.

| Check | Before retry | After retry |
| --- | ---: | ---: |
| Fixed source-selection/abstention cases | 32/32 | 32/32 |
| Fixed exact reference coverage (diagnostic) | 17/24 | 17/24 |
| Existing targeted probes | 11/12 | 12/12 |
| Probe exact reference coverage (diagnostic) | 6/9 | 7/9 |
| New terminology boundary cases | 11/12 | 12/12 |
| Boundary supported cases | 5/6 | 6/6 |
| Boundary unsupported cases | 6/6 | 6/6 |
| Boundary exact reference coverage (diagnostic) | 5/6 | 6/6 |

The new boundary cases are in `evals/terminology_cases.json`. They cover singular
and plural wording, SLI samples without requests, unused-service wording, absent
production IDs/passwords, historical uptime, refunds, costs and fan noise.
The additional recovered case asks whether a quiet application generates
availability samples without requests. Labels and quotes are validated offline.
The questions were written before observing their model results and were not
changed afterwards; they are still targeted development cases, not an
independent held-out benchmark.

Reports: [main](terminology-main.json), [existing probes](terminology-probes.json),
[new boundary cases before](terminology-boundary-baseline.json) and
[new boundary cases after](terminology-boundary.json). The before boundary run
uses the merged PR #12 source with the same index and case file. Historical
32-case and probe reports from earlier PRs remain unchanged. Main-case metrics
and selected chunks match PR #12; tiny floating-point differences can occur after
an index is regenerated, and current report fingerprints identify this run's
index. The reports do not contain generated answers.

## Limits and costs

This is a deliberately narrow terminology fix informed by an observed miss.
It does not establish general paraphrase accuracy. “Quiet” can have other
meanings, so an alias can misinterpret an unseen question. The unchanged reranker
is a relevance filter, not a guarantee of semantic equivalence or answerability.
All six nearby missing-fact cases remained refused in this local run, but that
does not prove all unsupported questions will be refused.

The retry cannot help if the original hybrid search finds no candidates. It
also does not add synonyms such as “unused” or “quiescent” to the alias map.
The new unused-service case happens to pass through ordinary retrieval. The
existing literal-value guard retains its documented format and semantic limits.

Only a failed first reranking with the recognized phrase incurs a second batch,
of at most the existing eight candidates. This adds local inference work; latency
was not benchmarked. No Bedrock/AWS calls, model downloads, cloud changes or
deployments were performed. Generated-answer quality, prompt-injection resistance,
live MCP interoperability and production deployment health were not measured.

## Reproduce locally with cached models

With the repository virtual environment active and the existing index current:

```bash
python -m pytest -q --junitxml=test-results/pytest.xml
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  python -m src.evaluate --offline --report eval-results/retrieval.json
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  python -m src.evaluate --offline --cases evals/retrieval_probes.json \
  --report eval-results/retrieval-probes.json
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  python -m src.evaluate --offline --cases evals/terminology_cases.json \
  --report eval-results/terminology.json
```

All three model evaluations exit `0` in the recorded environment. The deterministic
CI suite uses fake models and does not run these real-model evaluations.
