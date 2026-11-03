"""Tests for SemanticChunker — type-aware text splitting."""

from __future__ import annotations

import pytest

from vortis.connectors.chunker import ChunkResult, SemanticChunker


@pytest.fixture()
def chunker() -> SemanticChunker:
    return SemanticChunker(max_tokens=50)


def test_short_message_single_chunk(chunker: SemanticChunker) -> None:
    """A message shorter than max_tokens is returned as a single chunk."""
    text = "Hello, world! How are you today?"
    results = chunker.chunk(text, doc_type="message")
    assert len(results) == 1
    assert results[0].content == text
    assert results[0].index == 0


def test_document_splits_on_headings() -> None:
    """Documents with ## headings produce chunks with section metadata."""
    chunker = SemanticChunker(max_tokens=512)
    text = (
        "## Introduction\n"
        "This is the introduction paragraph. It explains the context.\n\n"
        "## Methods\n"
        "This section describes the methods used in the study.\n\n"
        "## Results\n"
        "Here are the results of the experiment."
    )
    results = chunker.chunk(text, doc_type="document")
    sections = {r.metadata.get("section") for r in results}
    assert "Introduction" in sections
    assert "Methods" in sections
    assert "Results" in sections


def test_document_splits_on_paragraphs() -> None:
    """Within a section, long content splits on double-newline paragraph breaks."""
    chunker = SemanticChunker(max_tokens=15)
    para1 = " ".join(["word"] * 20)
    para2 = " ".join(["text"] * 20)
    text = f"## Section One\n{para1}\n\n{para2}"
    results = chunker.chunk(text, doc_type="document")
    assert len(results) >= 2
    for r in results:
        assert r.metadata.get("section") == "Section One"


def test_no_mid_sentence_splits() -> None:
    """Chunks (except possibly the last) must end with sentence-ending punctuation."""
    chunker = SemanticChunker(max_tokens=10)
    text = (
        "## Analysis\n"
        "The first result was positive. The second outcome was negative. "
        "The third finding was inconclusive. The final conclusion is pending."
    )
    results = chunker.chunk(text, doc_type="document")
    for r in results[:-1]:
        stripped = r.content.rstrip()
        assert stripped[-1] in {".", "?", "!"}, (
            f"Non-final chunk does not end with sentence punctuation: {stripped!r}"
        )


def test_email_splits_on_reply_boundaries() -> None:
    """Emails split on 'On ... wrote:' reply headers."""
    chunker = SemanticChunker(max_tokens=512)
    text = (
        "Hi Alice, please see my comments below.\n\n"
        "On Mon, Jan 1, 2024, Alice Smith <alice@example.com> wrote:\n"
        "> Original message here.\n"
        "> More original text.\n\n"
        "On Sun, Dec 31, 2023, Bob Jones <bob@example.com> wrote:\n"
        "> Even earlier message content."
    )
    results = chunker.chunk(text, doc_type="email")
    assert len(results) >= 2


def test_event_always_single_chunk() -> None:
    """Events are never split regardless of length."""
    chunker = SemanticChunker(max_tokens=5)
    text = " ".join(["word"] * 100)
    results = chunker.chunk(text, doc_type="event")
    assert len(results) == 1
    assert results[0].content == text


def test_contact_always_single_chunk() -> None:
    """Contacts are never split regardless of length."""
    chunker = SemanticChunker(max_tokens=5)
    text = " ".join(["info"] * 100)
    results = chunker.chunk(text, doc_type="contact")
    assert len(results) == 1
    assert results[0].content == text


def test_parent_metadata_inherited() -> None:
    """All chunks carry the parent metadata passed to chunk()."""
    chunker = SemanticChunker(max_tokens=10)
    parent_meta = {"source": "gmail", "doc_id": "abc-123", "priority": "high"}
    text = (
        "## Section A\n"
        "First sentence of section A. Second sentence of section A. "
        "Third sentence here. Fourth sentence concludes.\n\n"
        "## Section B\n"
        "First sentence of section B. Second sentence of section B."
    )
    results = chunker.chunk(text, doc_type="document", metadata=parent_meta)
    for r in results:
        assert r.metadata.get("source") == "gmail"
        assert r.metadata.get("doc_id") == "abc-123"
        assert r.metadata.get("priority") == "high"


def test_sequential_chunk_indexes() -> None:
    """Chunks are indexed sequentially from 0 across all splits."""
    chunker = SemanticChunker(max_tokens=10)
    text = (
        "## Alpha\n"
        "Sentence one ends here. Sentence two ends here. Sentence three ends here.\n\n"
        "## Beta\n"
        "Sentence four ends here. Sentence five ends here."
    )
    results = chunker.chunk(text, doc_type="document")
    for i, r in enumerate(results):
        assert r.index == i, f"Expected index {i}, got {r.index}"


def test_note_doc_type_treated_as_document() -> None:
    """doc_type='note' uses the same document splitting strategy."""
    chunker = SemanticChunker(max_tokens=512)
    text = (
        "## My Note\n"
        "This is a note with section headings.\n\n"
        "## Another Section\n"
        "More content here."
    )
    results = chunker.chunk(text, doc_type="note")
    sections = {r.metadata.get("section") for r in results}
    assert "My Note" in sections
    assert "Another Section" in sections


def test_unknown_doc_type_treated_as_document() -> None:
    """Unknown doc_type uses the document splitting strategy."""
    chunker = SemanticChunker(max_tokens=512)
    text = "## Header\nContent under the header.\n\n"
    results = chunker.chunk(text, doc_type="unknown_type")
    sections = {r.metadata.get("section") for r in results}
    assert "Header" in sections


def test_empty_text_returns_empty_list() -> None:
    """Empty string input returns an empty list."""
    chunker = SemanticChunker(max_tokens=512)
    results = chunker.chunk("", doc_type="document")
    assert results == []


def test_whitespace_only_text_returns_empty_list() -> None:
    """Whitespace-only input returns an empty list."""
    chunker = SemanticChunker(max_tokens=512)
    results = chunker.chunk("   \n\n  \t  ", doc_type="document")
    assert results == []


def test_chunk_result_is_dataclass() -> None:
    """ChunkResult has the expected fields with correct defaults."""
    cr = ChunkResult(content="hello")
    assert cr.content == "hello"
    assert cr.index == 0
    assert cr.metadata == {}


def test_message_accumulates_into_max_tokens() -> None:
    """Message chunks accumulate paragraphs up to max_tokens."""
    chunker = SemanticChunker(max_tokens=20)
    para = "one two three four five six seven eight"
    text = f"{para}\n\n{para}\n\n{para}\n\n{para}"
    results = chunker.chunk(text, doc_type="message")
    assert len(results) >= 2
    for r in results[:-1]:
        assert len(r.content.split()) <= 20 * 2


def test_document_no_headings_uses_paragraphs() -> None:
    """Documents without ## headings fall back to paragraph splitting."""
    chunker = SemanticChunker(max_tokens=15)
    para1 = " ".join(["alpha"] * 20)
    para2 = " ".join(["beta"] * 20)
    text = f"{para1}\n\n{para2}"
    results = chunker.chunk(text, doc_type="document")
    assert len(results) >= 2
