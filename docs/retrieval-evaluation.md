# Retrieval evaluation

The dataset evaluates retrieval from the four checked-in Markdown snapshots. It
does not query live infrastructure, refresh another repository's documentation or
generate an answer with Bedrock.

## Dataset and labels

`evals/retrieval_cases.json` contains 32 cases, including the original five questions:

| Category | Cases | Purpose |
| --- | ---: | --- |
| Supported | 20 | Five questions for each document, covering documented operational behaviour |
| Ambiguous | 4 | Project names omitted, overlapping terminology or a cross-project handoff |
| Unsupported | 8 | Four unrelated questions and four related questions whose requested facts are absent |

The ambiguous cases still have a documented answer. They test routing and
cross-project coverage; they do not test an interactive clarification policy.
For example, a question about tracing an application error should retrieve the
observability log-to-trace material rather than a CloudOps Decision Trace.

Each case includes a stable ID, category, question, expected source files,
`expect_evidence`, reference evidence and a label rationale. Unsupported cases
have no positive sources or references, and their rationale explains the missing
information. Every reference quote must exist verbatim in the named source.

Offline CI rejects duplicate IDs/questions, inconsistent categories and labels,
unknown sources, invented reference quotes and missing source annotations. It
also checks that the recorded baseline fingerprints match the current corpus and
dataset. This catches stale annotations; it cannot prove that an absence label or
human rationale is semantically correct, so those still need review.

## Scoring rubric

For a supported or ambiguous question, a source-selection check passes when:

1. Retrieval returns evidence.
2. The first source is expected.
3. Every returned source is expected.
4. Every expected source appears in the results. The cross-project handoff case
   therefore needs both PlatformPilot and CloudOps evidence.

For an unsupported question, the abstention check passes only when retrieval
returns no chunks. A related document is not necessarily evidence for the
requested fact. A negative-case failure does not establish that the agent would
invent an answer: generation is not part of this benchmark.

**Exact reference coverage is reported separately.** All labelled quotes must
occur in returned chunks from their own source, with whitespace normalized. This
helps expose the weakness of filename-only scoring, but it is a diagnostic rather
than part of the pass criterion. The documents repeat some facts in equivalent
wording, and an exact-quote miss does not prove that the returned evidence is
unusable. Conversely, a source-selection pass does not prove sufficient evidence
for every part of an answer.

The CLI exits `0` when all source-selection/abstention cases pass and `1` when any
fail. It saves the report before returning that failure status. Invalid labels,
an empty suite or stale index metadata stop evaluation with an error.

## Recorded local baseline

Run date: 2026-10-23. The index was rebuilt locally from all four documents:
103 chunks, 384 embedding dimensions. The cached embedding and reranker models
were used with offline flags. No AWS or Bedrock calls, cloud deployments or model
downloads were made.

| Category | Passed | Total |
| --- | ---: | ---: |
| Supported | 19 | 20 |
| Ambiguous | 4 | 4 |
| Unsupported | 7 | 8 |
| All source-selection/abstention checks | 30 | 32 |

Exact reference coverage: **12 of 24 answerable cases**. This is not a claim of
93.75% answer accuracy. There are no generated answers, semantic answer grading,
latency benchmarks or production traffic in this evaluation.

The recorded [JSON report](retrieval-baseline.json) contains per-case results,
chunk numbers, scores, model names, library versions, retrieval parameters and
dataset/corpus/index fingerprints. The dataset questions, labels, retrieval
thresholds and models were not tuned after observing these results. The reference
coverage metric is deliberately kept separate to avoid treating equivalent
wording as a source-selection failure.

### Known source-selection/abstention misses

- `observability-no-traffic`: the document explains that idle applications are not
  treated as failures, but retrieval returns no chunks for this question. This is
  a false abstention on a documented fact.
- `unsupported-pilot-tenant`: the corpus provides no production Entra tenant ID,
  but retrieval returns three PlatformPilot identity/roadmap chunks. Those explain
  current identity scope and future SSO work, not the requested ID. This exposes
  a boundary between related background and evidence for a specific answer.

### Examples behind the reference-coverage diagnostic

- The Azure Bastion question returns passages explicitly showing private
  administrative access, but not the exact labelled sentence. This is an example
  of useful evidence that an exact-quote metric misses.
- The CloudOps persistence question retrieves a technology-stack passage naming
  Postgres but misses the labelled in-memory fallback explanation. The correct
  filename alone is insufficient for the requested detail.
- The Decision Trace question retrieves the five steps and a separate passage
  forbidding execution, while missing the exact second reference wording. Human
  review should distinguish this from genuinely missing information.

## Reproduce locally without cloud access

From the repository root with the development environment active, first validate
the labels and evaluator using the offline suite:

```bash
python -m pytest -q --junitxml=test-results/pytest.xml
```

If the two models are already cached, rebuild the ignored local index:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  python -m src.ingest
```

Then run the model-backed benchmark separately:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  python -m src.evaluate --offline --report eval-results/retrieval.json
```

The recorded baseline has two failing cases, so expect exit status `1` and inspect
the saved report. Do not relabel cases just to obtain a green result. The next
retrieval changes can be compared against these frozen questions and parameters.
Cached model revisions or library changes can alter results; the recorded report
is a local baseline, not a guarantee that every environment will reproduce exact
floating-point scores. The model-backed run is separate from CI and needs no
deployment. The deployment gate from the previous update is unchanged.
