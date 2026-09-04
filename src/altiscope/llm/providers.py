"""Build provider adapters from registry entries, one instance per configured provider."""

from __future__ import annotations

from altiscope.llm.provider import Provider
from altiscope.llm.registry import ProviderSpec, Registry


def build_provider(spec: ProviderSpec) -> Provider:
    if spec.kind == "anthropic":
        # Vendor SDKs load only when their provider is configured.
        from altiscope.llm.anthropic_provider import AnthropicProvider  # noqa: PLC0415

        return AnthropicProvider(spec)
    if spec.kind == "openai_compatible":
        from altiscope.llm.openai_compatible_provider import (  # noqa: PLC0415
            OpenAICompatibleProvider,
        )

        return OpenAICompatibleProvider(spec)
    msg = f"unknown provider kind {spec.kind!r}"  # pyright: ignore[reportUnreachable]
    raise ValueError(msg)


class ProviderPool:
    """Lazily constructs and caches one adapter per provider name."""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry
        self._built: dict[str, Provider] = {}

    def for_model(self, model_id: str) -> Provider:
        spec = self._registry.provider_for(model_id)
        if spec.name not in self._built:
            self._built[spec.name] = build_provider(spec)
        return self._built[spec.name]
