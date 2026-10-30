"""Content Tools — write, rewrite, proofread, translate, headline, outline, pitch, email, tag."""

from typing import Annotated
from pydantic import Field

from mcp_tools import (
    metered_tool,
    proofread_inner, rewrite_inner, tag_inner, email_inner,
)


@metered_tool("ai")
def proofread(text: Annotated[str, Field(description="Text to proofread")], style: Annotated[str, Field(description="Writing style: professional, casual, academic")] = "professional") -> dict:
    """Grammar and clarity corrections with tracked changes and writing quality score."""
    return proofread_inner(text, style)


@metered_tool("ai")
def rewrite(text: Annotated[str, Field(description="Text to rewrite")], audience: Annotated[str, Field(description="Target audience for the rewrite")] = "general audience", tone: Annotated[str, Field(description="Desired tone: neutral, formal, casual, enthusiastic")] = "neutral") -> dict:
    """Rewrite text for a specific audience, reading level, or brand voice."""
    return rewrite_inner(text, audience, tone)


@metered_tool("ai")
def tag(text: Annotated[str, Field(description="Text to auto-tag")], taxonomy: Annotated[list[str], Field(description="Predefined taxonomy of valid tags")] = None, max_tags: Annotated[int, Field(description="Maximum number of tags to return")] = 10) -> dict:
    """Auto-tag content using a taxonomy or free-form. Returns tags, primary tag, categories."""
    return tag_inner(text, taxonomy, max_tags)


@metered_tool("ai")
def email(purpose: Annotated[str, Field(description="Purpose or goal of the email")], tone: Annotated[str, Field(description="Email tone: professional, friendly, formal, casual")] = "professional", context: Annotated[str, Field(description="Background context for the email")] = "", recipient: Annotated[str, Field(description="Who the email is for")] = "", length: Annotated[str, Field(description="Email length: short, medium, or long")] = "medium") -> dict:
    """Compose a professional email. Returns subject line and body."""
    return email_inner(purpose, tone, context, recipient, length)
