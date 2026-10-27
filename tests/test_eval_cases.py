from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.eval_cases import validate_eval_cases


DOCUMENTS = {"a.md": "Private DNS provides a network path.", "b.md": "RBAC grants permissions."}
CASE = {"id": "dns-case", "category": "supported", "question": "What does Private DNS do?",
        "expect_evidence": True, "expected_sources": ["a.md"],
        "reference_evidence": [{"source": "a.md", "quote": "Private DNS provides a network path."}],
        "rationale": "The document explains the networking role."}


def test_checked_in_dataset_labels_have_real_document_evidence():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "evals/retrieval_cases.json").read_text())
    documents = {p.name: p.read_text() for p in (root / "data").glob("*.md")}
    assert validate_eval_cases(cases, documents) == cases
    assert {case["category"] for case in cases} == {"supported", "ambiguous", "unsupported"}
    assert {source for case in cases for source in case["expected_sources"]} == set(documents)


def test_targeted_probe_labels_have_real_document_evidence():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "evals/retrieval_probes.json").read_text())
    documents = {p.name: p.read_text() for p in (root / "data").glob("*.md")}
    assert validate_eval_cases(cases, documents) == cases
    primary = json.loads((root / "evals/retrieval_cases.json").read_text())
    assert {case["question"] for case in cases}.isdisjoint(case["question"] for case in primary)


def test_terminology_boundary_labels_have_documented_references():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "evals/terminology_cases.json").read_text())
    documents = {p.name: p.read_text() for p in (root / "data").glob("*.md")}
    assert validate_eval_cases(cases, documents) == cases
    existing = [case["question"] for name in ["retrieval_cases.json", "retrieval_probes.json"]
                for case in json.loads((root / "evals" / name).read_text())]
    assert {case["question"] for case in cases}.isdisjoint(existing)


@pytest.mark.parametrize("report_name,dataset_name", [
    ("retrieval-baseline.json", "retrieval_cases.json"),
    ("retrieval-improvement.json", "retrieval_cases.json"),
    ("retrieval-probes-baseline.json", "retrieval_probes.json"),
    ("retrieval-probes.json", "retrieval_probes.json"),
    ("terminology-probes.json", "retrieval_probes.json"),
    ("terminology-main.json", "retrieval_cases.json"),
    ("terminology-boundary-baseline.json", "terminology_cases.json"),
    ("terminology-boundary.json", "terminology_cases.json"),
])
def test_recorded_report_is_paired_with_the_current_dataset_and_corpus(report_name, dataset_name):
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "docs" / report_name).read_text())
    dataset = root / "evals" / dataset_name
    assert report["dataset_sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert report["corpus_sha256"] == {
        p.name: hashlib.sha256(p.read_text().encode("utf-8")).hexdigest()
        for p in (root / "data").glob("*.md")
    }
    assert [item["id"] for item in report["cases"]] == [case["id"] for case in json.loads(dataset.read_text())]


@pytest.mark.parametrize("changes,message", [
    ({"id": ""}, "IDs"),
    ({"question": " \n "}, "question"),
    ({"category": "other"}, "category"),
    ({"category": []}, "category"),
    ({"expect_evidence": 1}, "disagree"),
    ({"category": "unsupported"}, "disagree"),
    ({"expected_sources": "a.md"}, "list"),
    ({"expected_sources": ["../outside.md"]}, "unknown"),
    ({"expected_sources": ["a.md", "a.md"]}, "duplicate"),
    ({"rationale": ""}, "rationale"),
    ({"reference_evidence": []}, "require"),
    ({"reference_evidence": [{"source": "a.md", "quote": "invented passage"}]}, "absent"),
    ({"reference_evidence": [{"source": "b.md", "quote": "RBAC grants permissions."}]}, "not expected"),
    ({"expected_sources": ["a.md", "b.md"]}, "every expected source"),
])
def test_bad_labels_fail_validation(changes, message):
    case = deepcopy(CASE)
    case.update(changes)
    with pytest.raises(ValueError, match=message):
        validate_eval_cases([case], DOCUMENTS)


@pytest.mark.parametrize("kind", ["id", "question"])
def test_duplicate_ids_or_normalized_questions_are_rejected(kind):
    first, second = deepcopy(CASE), deepcopy(CASE)
    if kind == "id":
        second["question"] = "Different question?"
    else:
        second["id"] = "another-id"
        second["question"] = "  WHAT does   Private DNS do?  "
    with pytest.raises(ValueError, match="unique|duplicate"):
        validate_eval_cases([first, second], DOCUMENTS)


def test_unsupported_cases_require_an_absence_rationale_and_no_positive_labels():
    negative = dict(CASE, id="unknown", category="unsupported", expect_evidence=False,
                    expected_sources=[], reference_evidence=[], rationale="No HR policy is documented.")
    assert validate_eval_cases([negative], DOCUMENTS) == [negative]
    negative["reference_evidence"] = CASE["reference_evidence"]
    with pytest.raises(ValueError, match="unsupported cases"):
        validate_eval_cases([negative], DOCUMENTS)
