import os


def export_provider_keys(openai_api_key: str, anthropic_api_key: str) -> None:
    """litellm reads provider keys from os.environ; mirror them from Settings."""
    if openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", openai_api_key)
    if anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", anthropic_api_key)
