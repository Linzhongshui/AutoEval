import pytest

from autoeval.secrets import FileSecretStore


def test_secret_reference_is_opaque_and_retrievable(tmp_path):
    store = FileSecretStore(tmp_path / "secrets")
    reference = store.put("test-only-placeholder")
    assert "test-only-placeholder" not in reference
    assert store.get(reference) == "test-only-placeholder"
    assert store.put("second-placeholder") != reference


@pytest.mark.parametrize("reference", ["../key", "C:/key", "a/../b", "", "A" * 32])
def test_secret_reference_cannot_select_arbitrary_path(tmp_path, reference):
    with pytest.raises(ValueError):
        FileSecretStore(tmp_path).get(reference)


def test_header_injection_secret_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        FileSecretStore(tmp_path).put("placeholder\r\nAuthorization: injected")
