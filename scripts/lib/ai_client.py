# ============================================================
# SHARED GROQ AI CLIENT — Talks to Groq's Llama 3.3 70B model.
#
# WHY GROQ:
# - Ultra-fast inference (500+ tokens/sec on free tier)
# - Hosts Llama 3.3 70B — great for code generation
# - Free tier: 30 req/min, 14,400 req/day
#
# USAGE:
#   from lib.ai_client import ask_ai, ask_ai_json
#
#   response = ask_ai("You are a developer.", "Fix this bug...")
#   data = ask_ai_json("You are a reviewer.", "Review this PR...")
# ============================================================

import os
import json
import time
import re
from groq import Groq
from lib.logger import create_logger

# Create logger for AI operations
log = create_logger("Groq-AI")

# -----------------------------------------------------------
# Initialize Groq client.
# Reads GROQ_API_KEY from environment automatically.
# -----------------------------------------------------------
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


def ask_ai(system_prompt: str, user_message: str, **options) -> str:
    """
    Send a message to Groq AI and get a text response.

    Parameters:
        system_prompt — Instructions for the AI's role/behavior
        user_message  — The actual question or task
        **options:
            model       — Which Groq model (default: llama-3.3-70b-versatile)
            max_tokens  — Max response length (default: 4096)
            temperature — Creativity 0-1 (default: 0 for code)

    Returns:
        str — The AI's text response
    """
    model = options.get("model", os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"))
    max_tokens = options.get("max_tokens", 4096)
    temperature = options.get("temperature", 0)

    log.info(f"Calling Groq model: {model}")
    log.debug(f"System prompt length: {len(system_prompt)} chars")
    log.debug(f"User message length: {len(user_message)} chars")
    log.debug(f"Temperature: {temperature}, Max tokens: {max_tokens}")

    start_time = time.time()

    try:
        # -----------------------------------------------------------
        # Groq uses the OpenAI-compatible Chat Completions format.
        # Messages array:
        #   - "system" role: Sets the AI's persona
        #   - "user" role: The actual question/task
        # -----------------------------------------------------------
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )

        # Extract the response text
        text = response.choices[0].message.content
        if not text:
            log.error("Groq returned no text content")
            raise ValueError("Groq returned no text content")

        # Calculate performance metrics
        elapsed_ms = int((time.time() - start_time) * 1000)
        input_tokens = getattr(response.usage, "prompt_tokens", 0)
        output_tokens = getattr(response.usage, "completion_tokens", 0)
        tokens_per_sec = int(output_tokens / (elapsed_ms / 1000)) if elapsed_ms > 0 else 0

        log.success(f"AI response received in {elapsed_ms}ms")
        log.info(f"Tokens — Input: {input_tokens}, Output: {output_tokens}, Speed: {tokens_per_sec} tok/s")
        log.debug(f"Response length: {len(text)} chars")

        return text

    except Exception as error:
        elapsed_ms = int((time.time() - start_time) * 1000)
        status = getattr(error, "status_code", None)

        if status == 429:
            log.error(f"Rate limit hit after {elapsed_ms}ms. Free tier: 30 req/min")
        elif status == 401:
            log.error("Invalid GROQ_API_KEY — check your .env or GitHub secret")
        elif status == 503:
            log.error(f"Model {model} temporarily unavailable")
        else:
            log.error(f"Groq API error after {elapsed_ms}ms: {error}")
        raise


def ask_ai_json(system_prompt: str, user_message: str, **options) -> dict:
    """
    Same as ask_ai, but parses the response as JSON.

    Automatically:
    - Adds "return only JSON" instruction to the prompt
    - Strips markdown code fences from the response
    - Parses and returns a Python dict

    Returns:
        dict — Parsed JSON response from the AI
    """
    log.info("Requesting JSON response from AI")

    # Add explicit JSON instruction
    json_system_prompt = (
        system_prompt
        + "\n\nCRITICAL: Return ONLY raw JSON. No markdown code fences, "
        "no ```json blocks, no explanation text before or after the JSON."
    )

    text = ask_ai(json_system_prompt, user_message, **options)

    # Strip markdown code fences if the model added them
    cleaned = re.sub(r"^```json\s*\n?", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        log.success("JSON response parsed successfully")
        log.debug(f"JSON keys: {', '.join(parsed.keys()) if isinstance(parsed, dict) else 'array'}")
        return parsed
    except json.JSONDecodeError as error:
        log.error("Failed to parse AI response as JSON")
        log.error(f"Raw response: {text[:200]}...")
        raise ValueError(f"AI returned invalid JSON: {error}")
