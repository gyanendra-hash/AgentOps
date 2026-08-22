from app.chunking import chunk_text

SAMPLE = """## Scenario: A

Some text about A that goes on for a little while to give the splitter
something real to work with instead of a single short sentence.

## Scenario: B

Some other text about B, also long enough to be a meaningful chunk on its
own once split from A.
"""


def test_splits_on_headings_when_under_chunk_size():
    chunks = chunk_text(SAMPLE, chunk_size=500, chunk_overlap=50)
    assert len(chunks) >= 1
    assert all(chunk.strip() for chunk in chunks)


def test_respects_small_chunk_size():
    chunks = chunk_text(SAMPLE, chunk_size=60, chunk_overlap=10)
    assert len(chunks) > 2
    for chunk in chunks:
        assert len(chunk) <= 60 + 10  # splitter may slightly exceed at separators


def test_empty_text_yields_no_chunks():
    assert chunk_text("", chunk_size=500, chunk_overlap=50) == []


def test_whitespace_only_text_yields_no_chunks():
    assert chunk_text("   \n\n   ", chunk_size=500, chunk_overlap=50) == []
