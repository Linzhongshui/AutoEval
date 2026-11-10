import httpx
import pytest

from autoeval.targets import probe_model_list, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://api.deepseek.com",
        "https://evil.invalid",
        "https://user:pass@api.deepseek.com",
        "https://api.deepseek.com/?key=secret",
    ],
)
def test_endpoint_must_be_explicitly_allowed(url):
    with pytest.raises(ValueError):
        validate_url(url, ["api.deepseek.com"])


async def test_model_list_does_not_generate_and_errors_do_not_echo_secret():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/models"
        return httpx.Response(200, json={"data": [{"id": "test-model"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome, details = await probe_model_list(
            "https://api.deepseek.com", "test-model", "placeholder", client
        )
    assert outcome == "matched"
    assert "placeholder" not in str(details)


async def test_failed_auth_does_not_expose_upstream_body():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="sensitive-placeholder")
        )
    ) as client:
        outcome, details = await probe_model_list(
            "https://api.deepseek.com", "test-model", "placeholder", client
        )
    assert outcome == "upstream_error"
    assert details == {"http_status": 401}
