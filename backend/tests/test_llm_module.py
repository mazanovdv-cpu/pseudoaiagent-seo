from app.LLM_module import LLMConfig, delta_text, ensure_configured, missing_settings


def test_config_from_env_reads_proxyapi_names() -> None:
    config = LLMConfig.from_env(
        {
            "PROXYAPI_KEY": "key",
            "PROXYAPI_BASE_URL": "https://api.proxyapi.ru/v1",
            "PROXYAPI_MODEL": "vendor/model",
        }
    )
    assert config.api_key == "key"
    assert config.model == "vendor/model"
    assert missing_settings(config) == []


def test_ensure_configured_names_missing_fields() -> None:
    try:
        ensure_configured(LLMConfig(api_key=" ", base_url="", model=""))
    except ValueError as exc:
        assert "PROXYAPI_KEY" in str(exc)
        return
    raise AssertionError("ожидалась ошибка о недостающих настройках")


def test_delta_text_reads_string_and_parts() -> None:
    assert delta_text(type("Delta", (), {"content": "ок"})()) == "ок"
    assert delta_text(type("Delta", (), {"content": None})()) == ""
    assert delta_text(type("Delta", (), {"content": [{"text": "а"}, "б"]})()) == "аб"
