"""
Model mapping configuration for different providers.

Maps user-friendly model names to their actual API model IDs.
"""

MODEL_MAPS = {
    "claude": {
        # Claude models (Anthropic API)
        "opus-4.7": "opus",
        "opus": "opus",
        "claude-opus-4-7": "opus",
        "sonnet-4.6": "sonnet",
        "sonnet": "sonnet",
        "claude-sonnet-4-6": "sonnet",
        "haiku-4.5": "haiku",
        "haiku": "haiku",
        "claude-haiku-4-5": "haiku",
    },
    "codex": {
        # OpenAI/Codex models
        "gpt-5.5": "gpt-5.5",
        "gpt-5.4": "gpt-5.4",
        "gpt-5.4-mini": "gpt-5.4-mini",
        "gpt-5.3-codex": "gpt-5.3-codex",
        "gpt-5.2": "gpt-5.2",
        # Aliases
        "gpt-5.5-current": "gpt-5.5",
        "gpt-5.4-turbo": "gpt-5.4",
    }
}


def get_model_id(provider: str, model_name: str) -> str:
    """
    Get the actual model ID for a given provider and model name.

    Args:
        provider: Either 'claude' or 'codex'
        model_name: User-friendly model name

    Returns:
        The actual model ID to use in API calls

    Example:
        >>> get_model_id("claude", "sonnet-4.6")
        "sonnet"
        >>> get_model_id("codex", "gpt-5.4")
        "gpt-5.4"
    """
    provider_maps = MODEL_MAPS.get(provider, {})
    return provider_maps.get(model_name, model_name)


def get_default_model(provider: str) -> str:
    """Get the default model for a provider."""
    if provider == "claude":
        return "opus-4.7"  # Default (recommended)
    elif provider == "codex":
        return "gpt-5.5"  # Current
    else:
        return "opus-4.7"


def list_models(provider: str = None) -> dict:
    """
    List all available models for a provider or all providers.

    Args:
        provider: If specified, only return models for this provider

    Returns:
        Dictionary mapping provider names to their available models
    """
    if provider:
        return {provider: list(MODEL_MAPS.get(provider, {}).keys())}
    return {k: list(v.keys()) for k, v in MODEL_MAPS.items()}
