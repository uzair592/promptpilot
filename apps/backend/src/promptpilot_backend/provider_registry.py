"""Provider protocols and public endpoints shared by chat and delivery tasks."""

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    label: str
    base_url: str
    protocol: str = "openai"
    default_model: str = ""


PROVIDERS = {
    item.id: item
    for item in (
        ProviderDefinition(
            "openrouter",
            "OpenRouter",
            "https://openrouter.ai/api/v1",
            default_model="openrouter/free",
        ),
        ProviderDefinition(
            "openai", "OpenAI", "https://api.openai.com/v1", default_model="gpt-5-mini"
        ),
        ProviderDefinition(
            "anthropic",
            "Anthropic",
            "https://api.anthropic.com/v1",
            "anthropic",
            "claude-sonnet-4-5",
        ),
        ProviderDefinition(
            "gemini",
            "Google Gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "gemini",
            "gemini-2.5-flash",
        ),
        ProviderDefinition("grok", "xAI / Grok", "https://api.x.ai/v1"),
        ProviderDefinition("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
        ProviderDefinition("mistral", "Mistral", "https://api.mistral.ai/v1"),
        ProviderDefinition("groq", "Groq", "https://api.groq.com/openai/v1"),
        ProviderDefinition("custom", "Custom OpenAI-compatible provider", ""),
    )
}


def validate_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in {None, 443}
        or parsed.hostname.lower() in {"localhost", "metadata.google.internal"}
        or parsed.hostname.lower().endswith((".localhost", ".local", ".internal"))
    ):
        raise ValueError("Use a public HTTPS API base URL without credentials, query, or fragment")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Provider endpoints must use a public address")
    return value.strip().rstrip("/")


def provider_definition(provider: str, base_url: str | None = None) -> ProviderDefinition:
    if provider not in PROVIDERS:
        raise ValueError("Unknown provider; choose Custom for an OpenAI-compatible API")
    definition = PROVIDERS[provider]
    if provider == "custom":
        if not base_url:
            raise ValueError("A custom provider needs its API base URL")
        return ProviderDefinition("custom", definition.label, validate_base_url(base_url))
    if base_url and base_url.rstrip("/") != definition.base_url:
        raise ValueError("Use the official endpoint or choose Custom")
    return definition
