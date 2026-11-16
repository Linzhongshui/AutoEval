"""Resolve benchmark identity from immutable sample provenance."""


def report_dataset(snapshot):
    samples = snapshot.get("samples") or []
    tasks = (snapshot.get("inputs") or {}).get("tasks") or []
    if not samples and len(tasks) == 1:
        samples = tasks[0].get("samples") or []
    if samples and all(
        str(sample.get("sample_id", "")).startswith("gpqa_diamond:")
        for sample in samples
    ):
        return "GPQA-Diamond"
    return "GPQA"
