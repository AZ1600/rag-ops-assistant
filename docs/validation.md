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

The expanded suite was validated locally with Python 3.11: **54 passed** (previously
five API tests). GitHub Actions runs the same tests on pull requests and pushes to
`main`, with read-only repository permissions, a timeout and a JUnit artifact.
Local success does not imply that a remote CI run has already passed.

## What the tests establish

| Area | Behaviour checked |
| --- | --- |
| Retrieval | Keyword overlap, semantic/keyword weighting, candidate limits and threshold boundaries |
| Reranking | Final ordering, rejection threshold, result limits and skipping empty candidates |
| Provenance | Chunk numbers, sources, context order and stable source deduplication |
| Knowledge-base tool | Real search/reranking functions with controlled vectors and scores; refusal when either stage rejects evidence |
| Agent graph | Real compiled LangGraph with fake Bedrock/MCP boundaries; tool discovery/reuse, evidence propagation and independent question state |
| Guard behaviour | No-evidence ends the graph before another model call; tool errors and unknown tools raise service errors |
| API | Health, response metadata, blank/invalid requests and generic HTTP 500 responses |
| Evaluation | Supported/unsupported source metrics; module entry point; passing/failing exit codes; rejecting an empty suite |

An MCP error flag takes precedence over structured content. A tool failure now
stops the request before another generation call; `/ask` returns the existing
generic HTTP 500 message. A successful search reporting `found: false` still
returns the normal no-evidence answer. Service failures must not be represented
as a successful search with no matching documents.

## Real retrieval evaluation is separate

```bash
python -m src.evaluate
```

This command uses the actual embedding model, reranker, ingested index and the
questions in `evals/retrieval_cases.json`. It may download models unless they are
cached; it does not call Bedrock. Run it from the repository root after ingestion.
It exits `0` when every case passes and `1` when any case fails. An empty suite
raises an error before loading the index or models.

The automated tests exercise this module entry point with synthetic cases and
fake models. They do not run the model-backed dataset. They establish routing and
ranking behaviour, not semantic model accuracy, generated-answer faithfulness,
prompt-injection resistance, live MCP interoperability or AWS deployment health.

## Deployment gate

Automatic ECS deployment requires the GitHub Actions repository variable
`ENABLE_AUTOMATIC_ECS_DEPLOY` to be exactly `true`, successful Tests on `main`,
and deployment-relevant changes. Leaving the variable unset or `false` keeps
automatic deployment disabled. PR validation never requests AWS credentials.

The existing manual **Run workflow** option on `main` remains an explicit AWS
deployment request. It does not wait for a new test run: check that the selected
revision passed Tests before using it. No deployment is needed to verify this PR.
This gate does not stop existing AWS resources or change their running costs.
