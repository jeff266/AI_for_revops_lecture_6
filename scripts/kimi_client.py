"""
Kimi K3 Client for MEDDICC Agent

Provides cost-effective LLM inference via Fireworks AI using Kimi K3.
Used for context building and evaluation to reduce costs by ~70%.
"""
import os
import json
import requests
from typing import Dict, Optional
import time


class KimiClient:
    """Client for Kimi K3 via Fireworks AI API."""

    BASE_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
    MODEL = "accounts/fireworks/models/kimi-k3"  # Kimi K3 via Fireworks

    # Cost tracking (per million tokens)
    INPUT_COST_PER_M = 0.27  # $0.27 per 1M input tokens
    OUTPUT_COST_PER_M = 0.27  # $0.27 per 1M output tokens

    def __init__(self, api_key: str = None):
        """Initialize with Fireworks API key."""
        self.api_key = api_key or os.getenv("FIREWORKS_API_KEY")
        if not self.api_key:
            raise ValueError("FIREWORKS_API_KEY not set")

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })

        # Simple rate limiter
        self.last_request_time = 0
        self.min_interval = 0.1  # 100ms between requests

    def _rate_limit(self):
        """Simple rate limiting."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    def create_message(
        self,
        system: str,
        messages: list,
        max_tokens: int = 2000,
        temperature: float = 0.0
    ) -> Dict:
        """
        Create a chat completion using Kimi K3.

        Args:
            system: System prompt
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens to generate
            temperature: Temperature (0.0 = deterministic)

        Returns:
            Dict with content, usage, and cost
        """
        self._rate_limit()

        # Kimi K3 uses system message in messages array
        full_messages = [{"role": "system", "content": system}] + messages

        payload = {
            "model": self.MODEL,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        response = self.session.post(self.BASE_URL, json=payload)
        response.raise_for_status()

        data = response.json()

        # Extract content
        content = data["choices"][0]["message"]["content"]

        # Calculate cost
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        cost = (
            input_tokens / 1_000_000 * self.INPUT_COST_PER_M +
            output_tokens / 1_000_000 * self.OUTPUT_COST_PER_M
        )

        return {
            "content": content,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            },
            "cost": cost,
            "model": self.MODEL
        }

    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            result = self.create_message(
                system="You are a helpful assistant.",
                messages=[{"role": "user", "content": "Say 'test' and nothing else."}],
                max_tokens=10
            )
            return "test" in result["content"].lower()
        except Exception as e:
            print(f"Kimi connection failed: {e}")
            return False


def get_kimi_client(api_key: str = None) -> KimiClient:
    """Get configured Kimi client."""
    return KimiClient(api_key)


if __name__ == "__main__":
    # Test Kimi K3 connection
    import sys

    print("Testing Kimi K3 via Fireworks...")

    try:
        client = get_kimi_client()
        print("✓ Kimi client initialized")

        # Test request
        result = client.create_message(
            system="You are a MEDDICC sales methodology expert.",
            messages=[{
                "role": "user",
                "content": "What does MEDDICC stand for? Answer in one sentence."
            }],
            max_tokens=100
        )

        print(f"\n✓ Kimi K3 response:")
        print(f"  Content: {result['content'][:200]}")
        print(f"  Input tokens: {result['usage']['input_tokens']}")
        print(f"  Output tokens: {result['usage']['output_tokens']}")
        print(f"  Cost: ${result['cost']:.6f}")

        print("\n✓ Kimi K3 working correctly!")

    except Exception as e:
        print(f"❌ Kimi K3 test failed: {e}")
        print("\nMake sure FIREWORKS_API_KEY is set:")
        print("  export FIREWORKS_API_KEY='your-key-here'")
        sys.exit(1)
