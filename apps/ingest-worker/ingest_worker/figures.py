"""DESCRIBE step (multimodal plan, Phase 3): figures are saved and described by a vision model.

Each image element from the parser is stored as `<document prefix>/figures/NNN.png` in the
object store (shown in the source panel) and described by an OpenAI vision model, so a question
about a chart can find it. The chunk text is the caption, the description and the words printed
in the figure. Best effort: when the model call fails the figure keeps its caption and printed
words, and the upload still succeeds. Figures past FIGURE_MAX_PER_DOC become their words only.
"""

import asyncio
import base64
import logging
from dataclasses import replace

import litellm
from eagleeye_core.config import Settings, get_settings
from eagleeye_core.storage import ObjectStore
from eagleeye_llm.env import export_provider_keys
from eagleeye_llm.litellm_adapter import is_reasoning_model

from ingest_worker.errors import TransientIngestError
from ingest_worker.parsing.base import ParsedDocument, ParsedElement
from ingest_worker.parsing.clean import strip_stamps

logger = logging.getLogger(__name__)

PROMPT = (
    "Describe this figure from a document so it can be found by search and quoted accurately. "
    "Say what kind of figure it is and what it shows, then give every number, label, axis title "
    "and legend entry you can read, and the main trend or takeaway. Report only values printed "
    "in the figure; never estimate a value from a bar height or a line's position. Ignore "
    "watermarks and stamps such as CONFIDENTIAL or DRAFT. Plain text, at most 150 words."
)
MAX_TOKENS = 400
TIMEOUT_S = 60
CONCURRENCY = 4
PLACEHOLDER = "Figure"  # the parser's text for a figure without a caption


def _models(s: Settings) -> list[str]:
    primary = s.vision_model or s.model_fast
    fallback = s.vision_fallback_model or s.model_fast_fallback
    return [m for m in dict.fromkeys((primary, fallback)) if m]


async def _ask(model: str, png: bytes, context: str) -> str:
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    kwargs: dict = {}
    if is_reasoning_model(model):  # no billed thinking for a description
        kwargs["reasoning_effort"] = "none" if "gpt-6" in model else "minimal"
    response = await litellm.acompletion(
        model=model,
        max_tokens=MAX_TOKENS,
        timeout=TIMEOUT_S,
        num_retries=1,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{PROMPT}\n\n{context}".strip()},
                    {"type": "image_url", "image_url": {"url": url, "detail": "low"}},
                ],
            }
        ],
        **kwargs,
    )
    return (response.choices[0].message.content or "").strip()


async def describe_image(png: bytes, caption: str, labels: str, s: Settings) -> str:
    """The vision model's description, or "" when every model failed."""
    context = "\n".join(
        part
        for part in (
            f"Caption: {caption}" if caption else "",
            f"Words printed in the figure: {labels[:1500]}" if labels else "",
        )
        if part
    )
    for model in _models(s):
        try:
            return await _ask(model, png, context)
        except Exception:  # noqa: BLE001 - try the fallback, then keep the printed words
            logger.warning("figure description failed with %s", model, exc_info=True)
    return ""


def figure_text(caption: str, description: str, labels: str) -> str:
    parts = [caption, description, f"Printed in the figure: {labels}" if labels else ""]
    return "\n\n".join(p for p in parts if p) or PLACEHOLDER


async def _one(
    el: ParsedElement, key: str, store: ObjectStore, s: Settings, gate: asyncio.Semaphore
) -> ParsedElement:
    try:
        await store.put(key, el.image_png or b"", "image/png")
    except Exception as exc:
        raise TransientIngestError("Storage is temporarily unavailable.") from exc
    caption = "" if el.text == PLACEHOLDER else el.text
    async with gate:
        description = await describe_image(el.image_png or b"", caption, el.labels, s)
    return replace(
        el, text=figure_text(caption, description, el.labels), asset_key=key, image_png=None
    )


def _words_only(el: ParsedElement) -> ParsedElement | None:
    caption = "" if el.text == PLACEHOLDER else el.text
    text = "\n\n".join(p for p in (caption, el.labels) if p)
    return replace(el, kind="text", text=text, image_png=None) if text else None


async def describe(doc: ParsedDocument, store: ObjectStore, prefix: str) -> ParsedDocument:
    s = get_settings()
    figures = [i for i, el in enumerate(doc.elements) if el.kind == "image"]
    if not figures:
        return doc
    export_provider_keys(s.openai_api_key, s.anthropic_api_key)
    keep, extra = figures[: s.figure_max_per_doc], set(figures[s.figure_max_per_doc :])
    gate = asyncio.Semaphore(CONCURRENCY)
    described = await asyncio.gather(
        *(
            _one(doc.elements[i], f"{prefix}/figures/{n:03d}.png", store, s, gate)
            for n, i in enumerate(keep)
        )
    )
    by_index = dict(zip(keep, described, strict=True))
    elements: list[ParsedElement] = []
    for i, el in enumerate(doc.elements):
        if i in by_index:
            elements.append(by_index[i])
        elif i in extra:
            words = _words_only(el)
            if words is not None:
                elements.append(words)
        else:
            elements.append(el)
    logger.info("described %d figures (%d over the cap kept as words)", len(keep), len(extra))
    # the vision model may still name a watermark it saw; drop the stamps the clean step found
    elements = [
        replace(el, text=strip_stamps(el.text, doc.removed)) if el.asset_key else el
        for el in elements
    ]
    return replace(doc, elements=tuple(elements))
