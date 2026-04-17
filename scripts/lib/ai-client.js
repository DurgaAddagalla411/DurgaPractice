// ============================================================
// SHARED GROQ AI CLIENT — Reusable helper for all agents.
//
// WHY GROQ:
// Groq provides ultra-fast AI inference (tokens/sec is 10-20x
// faster than other providers). It hosts open-source models
// like Llama 3.3 70B and Mixtral on custom LPU hardware.
// The free tier is generous enough for this demo.
//
// WHAT IT PROVIDES:
// - askAI(systemPrompt, userMessage, options) — sends a
//   message to Groq and returns the text response.
// - askAIJSON(systemPrompt, userMessage, options) — same
//   but parses the response as JSON.
//
// GROQ SDK:
// The `groq-sdk` package follows the same pattern as OpenAI's
// SDK. If you've used the OpenAI SDK, this will feel familiar.
// ============================================================

import Groq from "groq-sdk";

// -----------------------------------------------------------
// Initialize the Groq client.
//
// The SDK reads GROQ_API_KEY from the environment automatically.
// You get your key from: https://console.groq.com/keys
//
// Groq's free tier allows:
//   - 30 requests/minute on most models
//   - 14,400 requests/day
//   - Enough for this demo and light production use
// -----------------------------------------------------------
const groq = new Groq({
  apiKey: process.env.GROQ_API_KEY,
});

// -----------------------------------------------------------
// askAI(systemPrompt, userMessage, options)
//
// A simplified wrapper around Groq's Chat Completions API.
//
// HOW IT WORKS:
// 1. Takes a system prompt (who the AI should act as)
// 2. Takes a user message (what to analyze/generate)
// 3. Sends to Groq's hosted LLM and extracts the text response
//
// PARAMETERS:
//   systemPrompt — instructions for the AI's role/behavior
//   userMessage  — the actual question or task
//   options      — optional overrides:
//     .model       — which model (default: from env or llama-3.3-70b-versatile)
//     .maxTokens   — max response length (default: 4096)
//     .temperature — creativity level 0-1 (default: 0 for code)
//
// RETURNS: string — the AI's text response
//
// EXAMPLE:
//   const fix = await askAI(
//     "You are a senior JavaScript developer.",
//     "Fix this bug: users.find() returns undefined when...",
//     { temperature: 0 }
//   );
// -----------------------------------------------------------
export async function askAI(systemPrompt, userMessage, options = {}) {
  const {
    model = process.env.GROQ_MODEL || "llama-3.3-70b-versatile",
    maxTokens = 4096,
    temperature = 0, // 0 = deterministic (best for code generation)
  } = options;

  console.log(`🤖 Calling Groq AI (${model})...`);

  try {
    // -----------------------------------------------------------
    // Groq uses the OpenAI-compatible Chat Completions format.
    //
    // Messages array:
    //   - "system" role: Sets the AI's persona and rules
    //   - "user" role: The actual question/task
    //
    // This is the same format used by OpenAI, Mistral, and
    // many other providers — making it easy to swap later.
    // -----------------------------------------------------------
    const response = await groq.chat.completions.create({
      model,
      max_tokens: maxTokens,
      temperature,
      messages: [
        {
          role: "system",
          content: systemPrompt,
        },
        {
          role: "user",
          content: userMessage,
        },
      ],
    });

    // Extract the text from the first choice.
    // Groq returns an array of "choices" (usually just 1).
    const text = response.choices[0]?.message?.content;

    if (!text) {
      throw new Error("Groq returned no text content");
    }

    // Log token usage for cost tracking
    // (Groq's free tier has rate limits, so tracking helps)
    console.log(
      `📊 Tokens used — Input: ${response.usage?.prompt_tokens || "?"}, ` +
        `Output: ${response.usage?.completion_tokens || "?"}, ` +
        `Speed: ${response.usage?.total_time ? Math.round(response.usage.completion_tokens / response.usage.total_time) + " tok/s" : "N/A"}`
    );

    return text;
  } catch (error) {
    // -----------------------------------------------------------
    // Common Groq errors:
    // - 401: Invalid API key
    // - 429: Rate limit exceeded (wait and retry)
    // - 503: Model temporarily unavailable
    // -----------------------------------------------------------
    if (error.status === 429) {
      console.error("❌ Groq rate limit hit. Wait a moment and retry.");
      console.error("   Free tier: 30 requests/min, 14,400 requests/day");
    } else {
      console.error("❌ Groq API error:", error.message);
    }
    throw error;
  }
}

// -----------------------------------------------------------
// askAIJSON(systemPrompt, userMessage, options)
//
// Same as askAI, but parses the response as JSON.
//
// Useful when you need structured data back from the AI,
// like a list of review comments or file changes.
//
// TIP: Include "Respond with valid JSON only. No markdown
// code fences." in your system prompt to get clean JSON.
//
// WHY WE STRIP CODE FENCES:
// LLMs often wrap JSON in ```json ... ``` markdown blocks
// even when told not to. We handle this gracefully.
// -----------------------------------------------------------
export async function askAIJSON(systemPrompt, userMessage, options = {}) {
  // Add explicit JSON instruction to system prompt
  const jsonSystemPrompt =
    systemPrompt +
    "\n\nCRITICAL: Return ONLY raw JSON. No markdown code fences, no ```json blocks, no explanation text before or after the JSON.";

  const text = await askAI(jsonSystemPrompt, userMessage, options);

  // Strip markdown code fences if the model added them anyway
  const cleaned = text
    .replace(/^```json\s*\n?/i, "")
    .replace(/^```\s*\n?/, "")
    .replace(/\n?```\s*$/, "")
    .trim();

  try {
    return JSON.parse(cleaned);
  } catch (error) {
    console.error("❌ Failed to parse AI response as JSON:");
    console.error("Raw response:", text);
    throw new Error(`AI returned invalid JSON: ${error.message}`);
  }
}

// Export the raw client for advanced use cases
export { groq };
