from plural.config import DEFAULT_SETTINGS, resolve_gateway_url


def test_resolve_gateway_url_prefers_explicit() -> None:
    assert (
        resolve_gateway_url(
            "http://127.0.0.1:8005/v1",
            environ={"PLURAL_GATEWAY_URL": "https://ignored.example/v1"},
        )
        == "http://127.0.0.1:8005/v1"
    )


def test_resolve_gateway_url_prefers_gateway_over_api_url() -> None:
    assert (
        resolve_gateway_url(
            environ={
                "PLURAL_GATEWAY_URL": "http://127.0.0.1:8005/v1",
                "PLURAL_API_URL": "http://localhost:3001/v1",
            }
        )
        == "http://127.0.0.1:8005/v1"
    )


def test_resolve_gateway_url_falls_back_to_default() -> None:
    assert resolve_gateway_url(environ={}) == DEFAULT_SETTINGS.gateway_base_url.rstrip("/")
