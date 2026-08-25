"""
Unified LLM client adapter for Anthropic, OpenAI, and Fireworks.

Providers:
  anthropic  — Claude models via api.anthropic.com
  openai     — GPT models via api.openai.com
  fireworks  — Any Fireworks-hosted model via fireworks.ai
               Uses OpenAI SDK pointing at Fireworks base URL.

Usage:
  from llm_client import LLMClient

  client = LLMClient.from_config(role="generator")
  response = client.complete(
      messages=[{"role": "user", "content": "..."}],
      system="You are...",
      max_tokens=4000,
  )
  text = response.text
  stop = response.stop_reason   # 'end_turn' | 'max_tokens' | 'tool_use'

  # Multi-turn (use this instead of appending response.content directly):
  messages.append(response.as_assistant_message())
"""

from __future__ import annotations
import os
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ── Normalized response ────────────────────────────────────────────────

@dataclass
class LLMResponse:
    """
    Provider-agnostic response object returned by LLMClient.complete().

    Fields
    ------
    text          : str   — The full text content of the response.
    stop_reason   : str   — Normalized stop reason:
                            'end_turn'   — model finished naturally
                            'max_tokens' — token budget exhausted
                            'tool_use'   — model invoked a tool
                              (Anthropic only; not supported for OpenAI/
                               Fireworks in this codebase)
    model         : str   — Model string that was used.
    input_tokens  : int   — Prompt token count.
    output_tokens : int   — Completion token count.
    raw           : object — Original SDK response (provider-specific).
    _provider     : str   — Internal: 'anthropic' | 'openai' | 'fireworks'
    """
    text:          str
    stop_reason:   str
    model:         str
    input_tokens:  int
    output_tokens: int
    raw:           object
    _provider:     str = field(default="anthropic", repr=False)

    def as_assistant_message(self) -> dict:
        """
        Return this response formatted as an assistant turn for multi-turn.

        Anthropic: {"role": "assistant", "content": raw.content}
                   Preserves content blocks so tool_use handling works.

        OpenAI/Fireworks: {"role": "assistant", "content": self.text}
                          OpenAI expects a plain string.

        Always use this method when appending to a message list for a
        follow-up call. Never append raw.content directly — it breaks
        for non-Anthropic providers.
        """
        if self._provider == "anthropic":
            return {"role": "assistant", "content": self.raw.content}
        return {"role": "assistant", "content": self.text}


# ── Main client ────────────────────────────────────────────────────────

class LLMClient:
    """
    Unified LLM client. One interface for Anthropic, OpenAI, Fireworks.

    Instantiate via:
      LLMClient.from_config(role="generator")   ← preferred: reads config
      LLMClient(model="gpt-4o", provider="openai")  ← direct
    """

    _FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"

    _ROLE_DEFAULTS = {
        "generator":       ("claude-sonnet-4-6",        "anthropic"),
        "evaluator":       ("claude-haiku-4-5-20251001", "anthropic"),
        "context_builder": ("claude-haiku-4-5-20251001", "anthropic"),
        "classifier":      ("claude-haiku-4-5-20251001", "anthropic"),
        "assessor":        ("claude-haiku-4-5-20251001", "anthropic"),
        "enrichment":      ("claude-haiku-4-5-20251001", "anthropic"),
    }

    _ENV_KEYS = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai":    "OPENAI_API_KEY",
        "fireworks": "FIREWORKS_API_KEY",
    }

    def __init__(self, model: str, provider: str = "anthropic",
                 api_key: str = None):
        self.model    = model
        self.provider = provider
        self._sdk     = self._init_sdk(api_key)
        self._fallback_client = None

    def _init_sdk(self, api_key: str = None):
        key = api_key or os.environ.get(
            self._ENV_KEYS.get(self.provider, "ANTHROPIC_API_KEY"), "")

        if not key:
            logger.warning(
                f"[LLM] {self._ENV_KEYS.get(self.provider)} not set "
                f"for provider '{self.provider}'"
            )

        if self.provider == "anthropic":
            import anthropic
            return anthropic.Anthropic(api_key=key)

        elif self.provider in ("openai", "fireworks"):
            from openai import OpenAI
            kwargs: dict = {"api_key": key}
            if self.provider == "fireworks":
                kwargs["base_url"] = self._FIREWORKS_BASE_URL
            return OpenAI(**kwargs)

        else:
            raise ValueError(
                f"Unknown provider: {self.provider!r}. "
                f"Valid options: anthropic | openai | fireworks"
            )

    def validate(self):
        """
        Validate that the API key is set for this provider.

        Raises ValueError if the required environment variable is missing.
        Call this at startup to fail fast rather than at first API call.
        """
        env_key = self._ENV_KEYS.get(self.provider)
        if not env_key:
            raise ValueError(f"Unknown provider: {self.provider!r}")

        api_key = os.environ.get(env_key, "")
        if not api_key:
            raise ValueError(
                f"API key not set: {env_key} is required for provider '{self.provider}'"
            )

    @classmethod
    def from_config(cls, role: str,
                    config: dict = None,
                    validate: bool = True) -> "LLMClient":
        """
        Instantiate from config/client.yaml models block.

        Reads models.<role>.name and models.<role>.provider.
        Falls back to _ROLE_DEFAULTS when keys are absent.

        Parameters
        ----------
        role     : 'generator' | 'evaluator' | 'context_builder' |
                   'classifier' | 'assessor' | 'enrichment'
        config   : Optional config dict (defaults to loading client.yaml)
        validate : If True (default), validates API key is set at startup.
                   Set to False only for testing/mocking scenarios.
        """
        if config is None:
            import sys
            from pathlib import Path
            scripts_dir = str(Path(__file__).resolve().parent)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from utils import load_client_config
            config = load_client_config()

        role_cfg = (config or {}).get("models", {}).get(role, {})
        default_model, default_provider = cls._ROLE_DEFAULTS.get(
            role, ("claude-haiku-4-5-20251001", "anthropic")
        )

        model    = role_cfg.get("name",     default_model)
        provider = role_cfg.get("provider", default_provider)

        client = cls(model=model, provider=provider)

        # Validate API key if requested
        if validate:
            client.validate()

        # Configure Anthropic fallback if enabled
        fallback_enabled = role_cfg.get("fallback_to_anthropic", False)
        if fallback_enabled and provider != "anthropic":
            logger.info(
                f"[LLM] Anthropic fallback enabled for {role} ({provider})"
            )
            fallback_model, _ = cls._ROLE_DEFAULTS.get(
                role, ("claude-haiku-4-5-20251001", "anthropic")
            )
            client._fallback_client = cls(
                model=fallback_model, provider="anthropic"
            )
            if validate:
                client._fallback_client.validate()

        return client

    def complete(
        self,
        messages:   list[dict],
        system:     Optional[str] = None,
        max_tokens: int = 1000,
        temperature: Optional[float] = None,
    ) -> LLMResponse:
        """
        Send a chat completion request.

        Parameters
        ----------
        messages   : list of {"role": "user"|"assistant", "content": str}
                     For multi-turn, build the assistant turn with
                     previous_response.as_assistant_message().
        system     : Optional system prompt string.
        max_tokens : Maximum output tokens.

        Returns
        -------
        LLMResponse — provider-agnostic, always has .text and .stop_reason.

        If the primary provider fails and fallback_to_anthropic is enabled,
        automatically retries with Anthropic.
        """
        try:
            if self.provider == "anthropic":
                return self._complete_anthropic(messages, system, max_tokens,
                                                 temperature)
            return self._complete_openai(messages, system, max_tokens,
                                         temperature)
        except Exception as e:
            if self._fallback_client:
                logger.warning(
                    f"[LLM] {self.provider} failed ({e}), "
                    f"falling back to Anthropic"
                )
                return self._fallback_client.complete(
                    messages, system, max_tokens, temperature
                )
            raise

    # ── Anthropic ──────────────────────────────────────────────────────

    def _complete_anthropic(self, messages, system, max_tokens,
                            temperature=None) -> LLMResponse:
        kwargs: dict = {
            "model":      self.model,
            "max_tokens": max_tokens,
            "messages":   messages,
        }
        if system:
            kwargs["system"] = system
        if temperature is not None:
            # anthropic-python 1.x dropped `temperature` from the typed
            # messages.create() signature (sampling params were removed from
            # the top-level API on Opus 4.7+/5/Fable, and the SDK stopped
            # exposing them as named kwargs). Sonnet 4.6 / Haiku 4.5 — the
            # models used on the scoring path — still honour temperature, but
            # it must go through the extra_body passthrough now, not a kwarg
            # (a kwarg raises TypeError: unexpected keyword argument).
            kwargs.setdefault("extra_body", {})["temperature"] = temperature

        resp = self._sdk.messages.create(**kwargs)

        text = "".join(
            block.text
            for block in resp.content
            if hasattr(block, "text")
        )

        stop_map = {
            "end_turn":   "end_turn",
            "max_tokens": "max_tokens",
            "tool_use":   "tool_use",
        }
        stop = stop_map.get(resp.stop_reason, resp.stop_reason or "end_turn")

        return LLMResponse(
            text=text,
            stop_reason=stop,
            model=self.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            raw=resp,
            _provider="anthropic",
        )

    # ── OpenAI / Fireworks ─────────────────────────────────────────────

    def _complete_openai(self, messages, system, max_tokens,
                         temperature=None) -> LLMResponse:
        oai_messages: list[dict] = []

        if system:
            oai_messages.append({"role": "system", "content": system})

        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                # Flatten Anthropic content block list to plain string
                text = "".join(
                    b.text if hasattr(b, "text") else
                    (b.get("text", "") if isinstance(b, dict) else "")
                    for b in content
                )
                oai_messages.append({"role": msg["role"], "content": text})
            else:
                oai_messages.append({"role": msg["role"], "content": content})

        oai_kwargs: dict = {
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            oai_kwargs["temperature"] = temperature
        resp = self._sdk.chat.completions.create(**oai_kwargs)

        choice = resp.choices[0]
        text   = choice.message.content or ""

        stop_map = {
            "stop":       "end_turn",
            "length":     "max_tokens",
            "tool_calls": "tool_use",
        }
        stop = stop_map.get(
            choice.finish_reason, choice.finish_reason or "end_turn"
        )

        usage = resp.usage
        return LLMResponse(
            text=text,
            stop_reason=stop,
            model=self.model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            raw=resp,
            _provider=self.provider,
        )

    # ── Connection testing ─────────────────────────────────────────────

    def test_connection(self) -> dict:
        """
        Test provider connection with a minimal API call.

        Returns dict with:
            success: bool
            provider: str
            model: str
            response_text: str (if successful)
            error: str (if failed)

        Useful for validating credentials and provider availability
        before running expensive operations.
        """
        try:
            response = self.complete(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1
            )
            return {
                "success": True,
                "provider": self.provider,
                "model": self.model,
                "response_text": response.text,
            }
        except Exception as e:
            return {
                "success": False,
                "provider": self.provider,
                "model": self.model,
                "error": str(e),
            }


# ── CLI entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Test LLM provider connection"
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai", "fireworks"],
        default="anthropic",
        help="Provider to test"
    )
    parser.add_argument(
        "--model",
        help="Model to use (defaults to provider default)"
    )
    args = parser.parse_args()

    # Select default model for provider
    model_defaults = {
        "anthropic": "claude-haiku-4-5-20251001",
        "openai": "gpt-4o-mini",
        "fireworks": "accounts/fireworks/models/deepseek-v3",
    }
    model = args.model or model_defaults.get(args.provider)

    print(f"Testing {args.provider} connection...")
    print(f"Model: {model}")
    print()

    client = LLMClient(model=model, provider=args.provider)

    # Validate API key first
    try:
        client.validate()
        print("✓ API key found")
    except ValueError as e:
        print(f"✗ API key validation failed: {e}")
        import sys
        sys.exit(1)

    # Test connection
    result = client.test_connection()

    if result["success"]:
        print("✓ Connection successful")
        print(f"Response: {result['response_text']}")
    else:
        print("✗ Connection failed")
        print(f"Error: {result['error']}")
        import sys
        sys.exit(1)
