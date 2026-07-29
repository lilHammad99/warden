"""Frame -> text description using a local vision model via Ollama."""

import ollama

from .cameras import to_jpeg


def describe_frame(frame, model: str, question: str | None = None) -> str:
    prompt = question or (
        "Describe what you see in this camera image in 2-3 short sentences. "
        "Mention people, what they are doing, and notable objects."
    )
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt, "images": [to_jpeg(frame)]}],
    )
    return (response["message"]["content"] or "").strip()
