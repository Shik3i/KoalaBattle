from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Lock

from koalabattle.core.models import ProviderKind

PROVIDER_KEY_VARIABLES: dict[ProviderKind, str] = {
    ProviderKind.OPENAI: "KOALABATTLE_OPENAI_API_KEY",
    ProviderKind.GEMINI: "KOALABATTLE_GEMINI_API_KEY",
    ProviderKind.ANTHROPIC: "KOALABATTLE_ANTHROPIC_API_KEY",
    ProviderKind.DEEPSEEK: "KOALABATTLE_DEEPSEEK_API_KEY",
    ProviderKind.OPENAI_COMPATIBLE: "KOALABATTLE_OPENAI_COMPATIBLE_API_KEY",
}


class ProviderCredentialStore:
    """Persist provider credentials in one explicitly configured gitignored dotenv file."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def load(self) -> dict[ProviderKind, str]:
        if self.path is None or not self.path.is_file():
            return {}
        values = self._parse(self.path.read_text(encoding="utf-8"))
        return {
            provider: value
            for provider, variable in PROVIDER_KEY_VARIABLES.items()
            if (value := values.get(variable, "").strip())
        }

    def save(self, provider: ProviderKind, api_key: str | None) -> None:
        if self.path is None:
            return
        variable = PROVIDER_KEY_VARIABLES.get(provider)
        if variable is None:
            return
        value = api_key.strip() if api_key else ""
        if "\n" in value or "\r" in value:
            raise ValueError("provider API keys cannot contain line breaks")
        with self._lock:
            self._write_variable(variable, value)

    def _write_variable(self, variable: str, value: str) -> None:
        assert self.path is not None
        if not self.path.is_file():
            raise ValueError(f"provider credentials file is missing: {self.path}")
        original = self.path.read_text(encoding="utf-8")
        replacement = f"{variable}={value}"
        lines = original.splitlines()
        output: list[str] = []
        replaced = False
        pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(variable)}\s*=")
        for line in lines:
            if pattern.match(line):
                if not replaced:
                    output.append(replacement)
                    replaced = True
                continue
            output.append(line)
        if not replaced:
            if output and output[-1]:
                output.append("")
            output.append(replacement)
        normalized = "\n".join(output) + "\n"
        with self.path.open("r+", encoding="utf-8") as handle:
            handle.seek(0)
            handle.write(normalized)
            handle.truncate()
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(self.path, 0o600)

    @staticmethod
    def _parse(content: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.removeprefix("export ").split("=", 1)
            key = key.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                values[key] = value.strip().strip("\"'")
        return values
