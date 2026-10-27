# Offline validation

The assistant answers questions from four curated operations documents. Retrieval
finds relevant chunks; MCP exposes that search as a tool; LangGraph coordinates
tool calls and Bedrock responses; FastAPI returns the answer, sources and evidence.
It does not inspect live infrastructure or execute remediation actions.

## Run the automated suite

From the repository root, with the existing virtual environment activated:

```bash
python -m pytest -q --junitxml=test-results/pytest.xml
git diff --check
```

Install `requirements-dev.txt` first if the development dependencies are missing.
Dependency installation needs access to package repositories. The tests themselves
use no AWS credentials, Bedrock calls, MCP subprocess, model downloads or index.
`tests/conftest.py` sets offline flags and blocks network connections, AWS client
creation and real SentenceTransformer/CrossEncoder construction. Individual tests
replace the required boundaries with controlled fakes.

The expanded suite was validated locally with Python 3.11: **144 passed** (including the previous 118 regression checks). GitHub Actions runs the same tests on pull requests and pushes to
`main`, with read-only repository permissions, a timeout and a JUnit artifact.
Local success does not imply that a remote CI run has already passed.

## What the tests establish

| Area | Behaviour checked |
| --- | --- |
| Retrieval | Keyword overlap, semantic/keyword weighting, candidate limits and threshold boundaries |
| Reranking | Final ordering, rejection threshold, result limits and skipping empty candidates |
| Ingestion | Markdown section boundaries, repeated heading context, fenced-code headings, empty sections and oversized paragraphs |
| Terminology retry | Original results take precedence; one retry reuses candidates and cutoff; source text is preserved; literal guards run first; retry errors propagate; report records the retry query |
| Value evidence | Recognized cloud-ID and duration requests reject missing values; valid literal formats and conceptual questions still pass; legacy indexes require a rebuild |
| Provenance | Chunk numbers, sources, context order and stable source deduplication |
| Knowledge-base tool | Real search/reranking functions with controlled vectors and scores; refusal when either stage rejects evidence |
| Agent graph | Real compiled LangGraph with fake Bedrock/MCP boundaries; tool discovery/reuse, evidence propagation and independent question state |
| Guard behaviour | No-evidence ends the graph before another model call; tool errors and unknown tools raise service errors |
| API | Health, response metadata, blank/invalid requests and generic HTTP 500 responses |
| Evaluation | Supported/unsupported source metrics; default and custom case files; passing/failing exit codes; policy and dataset fingerprints; rejecting empty suites and stale indexes |

An MCP error flag takes precedence over structured content. A tool failure now
stops the request before another generation call; `/ask` returns the existing
generic HTTP 500 message. A successful search reporting `found: false` still
returns the normal no-evidence answer. Service failures must not be represented
as a successful search with no matching documents.

## Real retrieval evaluation is separate

```bash
python -m src.evaluate --offline --report eval-results/retrieval.json
```

This command uses the actual embedding model, reranker, current ingested index and
32 labelled questions in `evals/retrieval_cases.json`. `--offline` uses cached
models only; without it, models may download. Neither mode calls Bedrock. The
command rejects stale index metadata and writes fingerprints and category results
to the optional JSON report, including when cases fail.

The updated recorded run passes **32/32 source-selection/abstention checks**
and exits `0`, compared with the preserved **30/32** baseline. Exact reference
coverage is a separate diagnostic: **17/24 answerable cases**, previously 12/24.
The fixed questions and four documents are unchanged. These are development
cases used to inform the change, rather than an independent test set.

The separate targeted probes now pass **12/12** after a curated terminology retry,
compared with 11/12 before this follow-up. A further 12 terminology boundary cases
improve from **11/12 to 12/12**, with all six missing-fact questions still refused.
The retry only runs when the first reranking returns no evidence, and keeps the
same candidate set, literal-value checks and rejection cutoff. Reports record
the reranking policy and the alias used for retry scores.

See [the evaluation rubric](retrieval-evaluation.md),
[the section comparison](retrieval-improvement.md) and
[the terminology results and limits](terminology-retrieval.md). The terminology
update does not require another index rebuild if the section index is already
current; older chunking formats still require `python -m src.ingest`. Cached
models are required for offline ingestion.

The automated tests validate every dataset label and reference against the corpus,
and exercise the module entry point and JSON reporting with synthetic models.
They do not run the model-backed benchmark. Neither the benchmark nor the tests
measure generated-answer faithfulness, prompt-injection resistance, live MCP
interoperability or AWS deployment health.

## Deployment gate

Automatic ECS deployment requires the GitHub Actions repository variable
`ENABLE_AUTOMATIC_ECS_DEPLOY` to be exactly `true`, successful Tests on `main`,
and deployment-relevant changes. Leaving the variable unset or `false` keeps
automatic deployment disabled. PR validation never requests AWS credentials.

The existing manual **Run workflow** option on `main` remains an explicit AWS
deployment request. It does not wait for a new test run: check that the selected
revision passed Tests before using it. No deployment is needed to verify this PR.
This gate does not stop existing AWS resources or change their running costs.
