"""
Enhanced LLM utilities for Slack Community Agent.

Supports: Google Gemini, OpenAI, OpenRouter, and Ollama (local).
"""

import asyncio
from typing import List, Dict, Optional
from agent.config import Config


async def get_chat_completion(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None
) -> str:
    """
    Get chat completion from LLM provider.
    Uses a timeout to avoid hanging when the API is slow or unresponsive.

    Args:
        messages: List of message dicts with 'role' and 'content'
        temperature: Temperature for generation
        max_tokens: Maximum tokens in response

    Returns:
        Response text from LLM
    """
    provider = Config.LLM_PROVIDER.lower()
    timeout = Config.LLM_REQUEST_TIMEOUT_SECONDS

    async def _call():
        if provider == "gemini":
            return await _get_gemini_completion(messages, temperature, max_tokens)
        elif provider in ("openai", "openrouter"):
            return await _get_openai_completion(messages, temperature, max_tokens)
        elif provider == "ollama":
            return await _get_ollama_completion(messages, temperature, max_tokens)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    try:
        return await asyncio.wait_for(_call(), timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"LLM request timed out after {timeout}s. The API may be slow or unresponsive — try again later."
        )


async def _get_gemini_completion(
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: Optional[int]
) -> str:
    """Get completion from Google Gemini using google.genai SDK."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=Config.GEMINI_API_KEY)
    try:
        prompt = "\n\n".join(
            f"{msg['role'].upper()}: {msg['content']}"
            for msg in messages
        )
        response = client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens or 2048,
            ),
        )
        return response.text
    except Exception as e:
        raise RuntimeError(f"Gemini API error: {str(e)}")
    finally:
        if hasattr(client, "close"):
            client.close()


async def _get_openai_completion(
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: Optional[int]
) -> str:
    """Get completion from OpenAI or OpenRouter."""
    from openai import AsyncOpenAI

    if Config.LLM_PROVIDER.lower() == "openrouter":
        api_key = Config.OPENROUTER_API_KEY
        model = Config.OPENROUTER_MODEL
        base_url = Config.OPENROUTER_BASE_URL
    else:
        api_key = Config.OPENAI_API_KEY
        model = Config.OPENAI_MODEL
        base_url = None

    timeout = Config.LLM_REQUEST_TIMEOUT_SECONDS
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        if not response.choices:
            raise RuntimeError("OpenAI/OpenRouter returned no choices")
        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("OpenAI/OpenRouter returned empty content")
        return content
    except Exception as e:
        raise RuntimeError(f"OpenAI/OpenRouter API error: {str(e)}")
    finally:
        await client.close()


async def _get_ollama_completion(
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: Optional[int]
) -> str:
    """Get completion from local Ollama (OpenAI-compatible API)."""
    from openai import AsyncOpenAI

    base_url = Config.OLLAMA_BASE_URL.rstrip("/")
    model = Config.OLLAMA_MODEL
    timeout = Config.LLM_REQUEST_TIMEOUT_SECONDS
    # Ollama does not require an API key; use a placeholder for the client
    client = AsyncOpenAI(api_key="ollama", base_url=base_url, timeout=timeout)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens or 2048,
        )
        if not response.choices:
            raise RuntimeError("Ollama returned no choices")
        content = response.choices[0].message.content
        # print("Ollama content:", content)
        if content is None:
            raise RuntimeError("Ollama returned empty content")
        return content
    except Exception as e:
        raise RuntimeError(f"Ollama API error: {str(e)}")
    finally:
        await client.close()


def get_chat_completion_sync(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None
) -> str:
    """Synchronous wrapper for get_chat_completion."""
    import asyncio
    return asyncio.run(get_chat_completion(messages, temperature, max_tokens))
