const OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions";

exports.handler = async function handler(event) {
  if (event.httpMethod !== "POST") {
    return {
      statusCode: 405,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Method not allowed" }),
    };
  }

  const apiKey = process.env.OPENROUTER_API_KEY;
  if (!apiKey) {
    return {
      statusCode: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        error: "Missing OPENROUTER_API_KEY in Netlify environment variables.",
      }),
    };
  }

  let payload;
  try {
    payload = JSON.parse(event.body || "{}");
  } catch (error) {
    return {
      statusCode: 400,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Invalid JSON body." }),
    };
  }

  const upstreamPayload = {
    model: payload.model || process.env.OPENROUTER_MODEL || "openai/gpt-4o-mini",
    temperature:
      payload.temperature ?? Number(process.env.OPENROUTER_TEMPERATURE || "0.2"),
    top_p: payload.top_p ?? Number(process.env.OPENROUTER_TOP_P || "0.9"),
    messages: Array.isArray(payload.messages) ? payload.messages : [],
  };

  if (Array.isArray(payload.models) && payload.models.length > 0) {
    upstreamPayload.models = payload.models;
  }

  try {
    const response = await fetch(OPENROUTER_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "HTTP-Referer":
          process.env.OPENROUTER_HTTP_REFERER || "https://biblia-app.netlify.app",
        "X-Title": "Biblia App",
      },
      body: JSON.stringify(upstreamPayload),
    });

    const text = await response.text();

    return {
      statusCode: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/json",
      },
      body: text,
    };
  } catch (error) {
    return {
      statusCode: 502,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        error: "Unable to reach OpenRouter.",
        detail: error instanceof Error ? error.message : String(error),
      }),
    };
  }
};

