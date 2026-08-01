"""
Evidence photo understanding — uses the local vision model (moondream, via
Ollama) to produce a factual, non-speculative description of an image,
which then gets indexed into rag_search so Case Chat can answer questions
about photo content, not just face matches.
"""
import llm_client

_PROMPT = (
    "Describe this evidence photo factually and plainly: the setting, "
    "visible objects, any readable text or signage, and general "
    "time-of-day/lighting cues if apparent. Do not speculate about the "
    "identity, age, or intent of any person shown. 2-4 sentences."
)


def describe_image(image_path: str) -> str:
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        result = llm_client.call_llm(_PROMPT, image_bytes=image_bytes)
        return result.text.strip()
    except Exception as e:
        return f"(Image description unavailable right now: {e})"
