"""
Enhanced LLM utilities for Slack Community Agent.
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
    """Get completion from Google Gemini."""
    try:
        import google.generativeai as genai
        
        genai.configure(api_key=Config.GEMINI_API_KEY)
        
        # Convert messages to Gemini format
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        # Combine messages into single prompt for now
        # (Gemini's chat has different format)
        prompt = "\n\n".join([
            f"{msg['role'].upper()}: {msg['content']}"
            for msg in messages
        ])
        
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens or 2048,
        }
        
        response = model.generate_content(
            prompt,
            generation_config=generation_config
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
