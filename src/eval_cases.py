"""Validate evaluation labels against the checked-in documentation, without models."""


CATEGORIES = {"supported", "ambiguous", "unsupported"}


def validate_eval_cases(cases, documents):
    if not isinstance(cases, list) or not cases:
        raise ValueError("Retrieval evaluation requires at least one case.")

    ids, questions = set(), set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each evaluation case must be an object.")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in ids:
            raise ValueError("Evaluation case IDs must be nonempty and unique.")
        ids.add(case_id)

        question = case.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"{case_id}: question must be nonempty.")
        normalized_question = " ".join(question.casefold().split())
        if normalized_question in questions:
            raise ValueError(f"{case_id}: duplicate question.")
        questions.add(normalized_question)

        category = case.get("category")
        if not isinstance(category, str) or category not in CATEGORIES:
            raise ValueError(f"{case_id}: unknown category.")
        expected = case.get("expect_evidence")
        if type(expected) is not bool or expected != (category != "unsupported"):
            raise ValueError(f"{case_id}: category and expect_evidence disagree.")
        sources = case.get("expected_sources")
        if not isinstance(sources, list) or any(not isinstance(s, str) for s in sources):
            raise ValueError(f"{case_id}: expected_sources must be a list of names.")
        if len(sources) != len(set(sources)) or any(s not in documents for s in sources):
            raise ValueError(f"{case_id}: duplicate or unknown expected source.")

        rationale = case.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"{case_id}: rationale must explain the label.")
        references = case.get("reference_evidence")
        if not isinstance(references, list):
            raise ValueError(f"{case_id}: reference_evidence must be a list.")
        if not expected:
            if sources or references:
                raise ValueError(f"{case_id}: unsupported cases must have no sources or references.")
            continue
        if not sources or not references:
            raise ValueError(f"{case_id}: supported cases require sources and reference evidence.")

        referenced_sources = set()
        seen_references = set()
        for reference in references:
            if not isinstance(reference, dict):
                raise ValueError(f"{case_id}: each reference must be an object.")
            source, quote = reference.get("source"), reference.get("quote")
            if not isinstance(source, str) or source not in sources:
                raise ValueError(f"{case_id}: reference source is not expected.")
            if not isinstance(quote, str) or not quote.strip() or quote not in documents[source]:
                raise ValueError(f"{case_id}: reference quote is absent from {source}.")
            if (source, quote) in seen_references:
                raise ValueError(f"{case_id}: duplicate reference evidence.")
            seen_references.add((source, quote))
            referenced_sources.add(source)
        if referenced_sources != set(sources):
            raise ValueError(f"{case_id}: every expected source needs reference evidence.")

    return cases
