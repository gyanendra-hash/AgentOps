"""Runbook/log chunking (ROADMAP 3.3), per SRS 6.5.3: RecursiveCharacterTextSplitter,
~500 tokens, 50 overlap. Uses character count as a token-count proxy rather than
pulling in a tokenizer (tiktoken) dependency -- close enough for runbook-sized
prose, and easy to swap later if chunk quality demands it."""

from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""],
    )
    return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]
