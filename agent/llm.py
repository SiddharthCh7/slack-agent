"""
Enhanced LLM utilities for Slack Community Agent.

Uses google.genai (the current SDK) with gemini-2.0-flash.
"""

import os
from typing import List, Dict, Any, Optional
from agent.config import Config


async def get_chat_completion(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None
) -> str:
    """
    Get chat completion from LLM provider.

    Args:
        messages: List of message dicts with 'role' and 'content'
        temperature: Temperature for generation
        max_tokens: Maximum tokens in response

    Returns:
        Response text from LLM
    """
    provider = Config.LLM_PROVIDER.lower()

    if provider == "gemini":
        return await _get_gemini_completion(messages, temperature, max_tokens)
    elif provider == "openai":
        return await _get_openai_completion(messages, temperature, max_tokens)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


async def _get_gemini_completion(
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: Optional[int]
) -> str:
    """Get completion from Google Gemini using google.genai SDK."""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=Config.GEMINI_API_KEY)

        # Convert role-based messages into a flat prompt string.
        # google.genai supports full Chat sessions too, but a prompt
        # string is simpler and works for all models.
        prompt = "\n\n".join(
            f"{msg['role'].upper()}: {msg['content']}"
            for msg in messages
        )

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens or 2048,
            ),
        )

        return response.text

    except Exception as e:
        raise RuntimeError(f"Gemini API error: {str(e)}")


async def _get_openai_completion(
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: Optional[int]
) -> str:
    """Get completion from OpenAI."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)

        response = await client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens or 2048
        )

        return response.choices[0].message.content

    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {str(e)}")


def get_chat_completion_sync(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None
) -> str:
    """Synchronous wrapper for get_chat_completion."""
    import asyncio
    return asyncio.run(get_chat_completion(messages, temperature, max_tokens))
