# Retrieval improvement: local evidence and limits

## What changed and why

The old idle-application paragraph shared a chunk with alert and dashboard text.
It fell below both the hybrid prefilter and final reranker thresholds. Ingestion
now separates ATX Markdown sections and repeats document and parent headings on
long sections. Headings inside fenced code remain content. The 800-character
limit remains soft: a single oversized paragraph is preserved. This is a focused
Markdown chunker, not a complete Markdown parser.

Section-only testing recovered the idle passage but introduced two regressions:
a useful log-to-trace passage scored about `0.389`, just below the `0.40`
prefilter, and shorter retention-roadmap passages passed reranking despite having
no retention duration. The prefilter is now `0.35`, admitting more material for
the unchanged reranker threshold (`-1.0`). The weighting remains 75% semantic and
25% keyword, with eight candidates and at most three results.

The production Entra tenant-ID question previously retrieved an SSO roadmap.
A narrow value guard now rejects candidates without a labelled literal for
recognized tenant/client/subscription/account ID requests. Recognized “how many
[time units]” requests need a numeric or one-to-twelve duration in the candidate.
Conceptual questions keep the normal retrieval path. The guard runs in the shared
reranking function used by both the knowledge-base tool and the evaluator.

The index records `markdown-sections-v1`. Loading an older index stops with a
rebuild command, so existing local indexes cannot silently bypass the new
chunking. Reports also record `literal-cloud-ids-duration-v1`. Docker already
runs ingestion during its build; the generated local index is not committed.

## Recorded comparison

The updated measurements were run locally on 2026-10-26 using cached
`all-MiniLM-L6-v2` and `cross-encoder/ms-marco-MiniLM-L-6-v2` models. No cloud
services, Bedrock calls, deployments or model downloads were used.

| Check | Before | After |
| --- | ---: | ---: |
| Fixed supported cases | 19/20 | 20/20 |
| Fixed ambiguous/cross-project cases | 4/4 | 4/4 |
| Fixed unsupported cases | 7/8 | 8/8 |
| All fixed source-selection/abstention checks | 30/32 | 32/32 |
| Exact reference coverage (diagnostic) | 12/24 | 17/24 |
| Separate targeted probes | 7/12 | 11/12 |
| Probe exact reference coverage (diagnostic) | 5/9 | 6/9 |
| Indexed chunks | 103 | 194 |

The 32 development questions, their labels, all four corpus files and the
historical baseline report are byte-identical to the merged evaluation update.
Their case-file SHA-256 remains
`fdde464a5af56a533cc58f2f30a69208daceb3004eb8c411ad634714298aa3b8`.
The scoring rubric is unchanged. These cases informed development and threshold
selection; 32/32 is not a claim of unseen-question or generated-answer accuracy.

Reports: [fixed baseline](retrieval-baseline.json),
[fixed updated run](retrieval-improvement.json),
[probe baseline](retrieval-probes-baseline.json) and
[probe updated run](retrieval-probes.json). The probe baseline was run with the
previous source and 103-chunk index, selecting the separate case file through the
old evaluator's `EVAL_FILE` setting. The updated CLI exposes `--cases` directly.
Reports include case/corpus/index fingerprints, model names, package versions,
parameters and per-case results; they contain no generated answers.

## Separate probes and remaining limits

`evals/retrieval_probes.json` contains 12 targeted paraphrase, concept and value
boundary probes. They were written during this investigation and are not an
independent held-out benchmark. Nine have document evidence and three request
absent values. Labels and reference quotes are validated offline against the
corpus. The source-selection rubric is the same as for the fixed dataset.

“Will a quiet service show zero availability when nobody is using it?” still
returns no evidence in both versions. The updated probe run therefore exits `1`
and records 11/12, even though the main run exits `0`. This is a remaining recall
limit. Other paraphrases may fail too; twelve probes do not establish general
robustness.

The literal guard is a necessary-evidence filter, not semantic verification. It
recognizes specific question forms, Azure UUID-shaped IDs, UUID/12-digit account
IDs, and labelled `:`, `=`, `|` or “is” values. It rejects all-zero ID placeholders
but cannot prove that an example value belongs to a real production system.
Other identifier formats or wording may be rejected or bypass the guard. Duration
presence does not prove that the duration describes the requested setting, and
multiple requested facts may not all survive final ranking. The reranker still
controls final relevance. This does not solve arbitrary missing-fact detection.

Exact reference coverage remains diagnostic: equivalent wording can support an
answer without matching a labelled quote, while a matching source filename alone
can still miss a requested detail. Generated-answer faithfulness, latency,
prompt-injection resistance, live MCP operation and deployment health were not
measured.

## Reproduce with cached models

From the repository root with its virtual environment active:

```bash
python -m pytest -q --junitxml=test-results/pytest.xml
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  python -m src.ingest
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  python -m src.evaluate --offline --report eval-results/retrieval.json
```

The recorded main run returns `0`. Check the probes separately:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  python -m src.evaluate --offline --cases evals/retrieval_probes.json \
  --report eval-results/retrieval-probes.json
```

Expect exit `1` for the documented 11/12 probe result, and inspect the saved
report. Offline ingestion/evaluation require already-cached models. Neither is
part of the deterministic CI test suite. No deployment is required.
