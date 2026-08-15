from __future__ import annotations

from koalabattle.config import Settings


def test_cors_origins_accept_compose_comma_separated_value(monkeypatch) -> None:
    monkeypatch.setenv("KOALABATTLE_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == (
        "http://localhost:3000",
        "http://localhost:5173",
    )
