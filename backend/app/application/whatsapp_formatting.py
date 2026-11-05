"""WhatsApp presentation, shared by chat replies and asynchronous results."""

from __future__ import annotations

import re

_PROTECTED = re.compile(r"```[\s\S]*?```|`[^`\n]+`|https?://[^\s<>()]+")


def format_whatsapp(text: str) -> str:
    """Adapt common Markdown without rewriting code, URLs or message meaning."""
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        value = match.group()
        if value.startswith("```"):
            value = re.sub(r"^```[\w+-]+\n", "```\n", value)
        protected.append(value)
        return f"\x00{len(protected) - 1}\x00"

    # Expose destinations: WhatsApp does not support Markdown link labels.
    text = _PROTECTED.sub(protect, text.replace("\r\n", "\n"))
    text = re.sub(r"\[([^\]\n]+)\]\(([^)\n]+)\)", r"\1\n\2", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"*\1*", text)
    text = re.sub(r"__([^_\n]+)__", r"*\1*", text)
    text = re.sub(r"~~([^~\n]+)~~", r"~\1~", text)
    text = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", r"*\1*", text)
    text = re.sub(r"(?m)^[ \t]*[•●]\s+", "- ", text)
    text = re.sub(r"(?m)^(\s*\d+)\)\s+", r"\1. ", text)
    text = re.sub(r"(?m)^- ([^:\n*]{1,60}): ", r"- *\1*: ", text)
    text = re.sub(r"\A([\wÁÉÍÓÚáéíóúñ -]{2,60})\n\n", r"*\1*\n\n", text)
    # Existing Artemis section labels and command hints get consistent emphasis.
    text = re.sub(r"(?m)^([\wÁÉÍÓÚáéíóúñ /→·-]{2,70}):$", r"*\1*", text)
    text = re.sub(r"‘([^’\n]+)’", r"`\1`", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    for index, value in enumerate(protected):
        text = text.replace(f"\x00{index}\x00", value)
    return text


def whatsapp_chunks(text: str, limit: int = 3900) -> list[str]:
    """Prefer paragraph/line boundaries and keep fenced code balanced per message."""
    remaining = format_whatsapp(text)
    chunks: list[str] = []
    in_code = False
    while remaining:
        # Reserve space for closing a code block at the message boundary.
        budget = limit - 4
        if len(remaining) <= budget:
            part, remaining = remaining, ""
        else:
            cut = remaining.rfind("\n\n", 0, budget + 1)
            if cut < budget // 2:
                cut = remaining.rfind("\n", 0, budget + 1)
            if cut < budget // 2:
                cut = remaining.rfind(" ", 0, budget + 1)
            if cut < budget // 2:
                cut = budget
            # Never cut through the three-character fence itself.
            while cut > 0 and remaining[cut - 1 : cut + 1] == "``":
                cut -= 1
            part, remaining = remaining[:cut], remaining[cut:]
        if part.count("```") % 2:
            in_code = not in_code
        chunks.append(part + ("\n```" if in_code else ""))
        if remaining and in_code:
            remaining = "```\n" + remaining
            in_code = False
    return chunks
