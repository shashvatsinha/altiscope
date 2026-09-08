from pathlib import Path

from altiscope.llm.registry import Registry


def test_openrouter_examples_are_provider_neutral_and_selectable():
    root = Path(__file__).parents[1] / "config" / "examples"
    anthropic = Registry.load(root / "openrouter-anthropic.yaml")
    openai = Registry.load(root / "openrouter-openai.yaml")
    assert anthropic.providers["openrouter"].base_url == "https://openrouter.ai/api/v1"
    assert anthropic.providers["openrouter"].api_key_env == "OPENROUTER_API_KEY"
    assert anthropic.models["openrouter-anthropic"].wire_name.startswith("anthropic/")
    assert openai.models["openrouter-openai"].wire_name.startswith("openai/")
    assert anthropic.models["openrouter-anthropic"].structured_output_mode == "native"
    assert openai.models["openrouter-openai"].structured_output_mode == "native"
