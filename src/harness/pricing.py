"""Price table for the spend cap. Unknown models (the scripted agents) cost nothing."""

# USD per million tokens: (input, output).
PRICES: dict[str, tuple[float, float]] = {
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5-nano": (0.05, 0.40),  # OpenAI list price, checked 2026-11-10; reasoning tokens bill as output
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
