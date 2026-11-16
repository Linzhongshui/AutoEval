from autoeval.dataset_identity import report_dataset


def test_identity():
    assert report_dataset({"samples": [{"sample_id": "gpqa_diamond:1"}]}) == "GPQA-Diamond"
    assert report_dataset({"samples": []}) == "GPQA"
    assert report_dataset({"samples": [{"sample_id": "other:1"}]}) == "GPQA"
