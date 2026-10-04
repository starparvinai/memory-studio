from memory_studio.storage import Store


def test_dotenv_overrides_saved_settings_and_process_env_takes_priority(tmp_path, monkeypatch):
    data = tmp_path / "data"
    store = Store(data)
    store.save_settings({"immich_url": "https://saved.example", "immich_api_key": "saved-key"})
    dotenv = tmp_path / ".env"
    dotenv.write_text("IMMICH_URL=https://dotenv.example\nIMMICH_API_KEY=dotenv-key\n")
    monkeypatch.setenv("MEMORY_STUDIO_ENV_FILE", str(dotenv))

    assert store.settings()["immich_url"] == "https://dotenv.example"
    assert store.settings()["immich_api_key"] == "dotenv-key"

    monkeypatch.setenv("IMMICH_API_KEY", "process-key")
    assert store.settings()["immich_api_key"] == "process-key"

    monkeypatch.delenv("IMMICH_API_KEY")
    dotenv.write_text("IMMICH_API_KEY=edited-key\n")
    assert store.settings()["immich_api_key"] == "edited-key"
    assert store.settings()["immich_url"] == "https://saved.example"
