"""Frame -> text description using a local vision model via Ollama."""

import ollama

from .cameras import to_jpeg


def describe_frame(frame, model: str, question: str | None = None,
                   unload: str | None = None) -> str:
    prompt = question or (
        "Describe what you see in this camera image in 2-3 short sentences. "
        "Mention people, what they are doing, and notable objects."
    )
    if unload:  # limited RAM can't hold chat + vision models at once
        try:
            ollama.generate(model=unload, prompt="", keep_alive=0)
        except Exception:
            pass
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt, "images": [to_jpeg(frame)]}],
        keep_alive=0,  # release memory right away so the chat model can return
        options={"num_ctx": 2048},  # small context keeps it inside limited RAM
    )
    return (response["message"]["content"] or "").strip()
