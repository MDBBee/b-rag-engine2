"""Text splitter factory for configurable chunking strategies."""

from langchain_text_splitters import (
    CharacterTextSplitter,
    RecursiveCharacterTextSplitter,
)

SPLITTER_CONFIGS = {
    "recursive": {
        "class": RecursiveCharacterTextSplitter,
        "kwargs": {
            "separators": ["\n# ", "\n## ", "\n### ", "\n\n", "\n", " ", ""],
        },
    },
    "character": {
        "class": CharacterTextSplitter,
        "kwargs": {
            "separator": "\n\n",
        },
    },
}


def get_splitter(splitter_type: str, chunk_size: int, chunk_overlap: int):
    """Get a text splitter instance with the specified parameters.
    
    Args:
        splitter_type: One of 'recursive', 'markdown_header', 'character'
        chunk_size: Maximum chunk size (characters or tokens depending on splitter)
        chunk_overlap: Overlap between chunks
        
    Returns:
        Configured text splitter instance
    """
    config = SPLITTER_CONFIGS.get(splitter_type, SPLITTER_CONFIGS["recursive"])
    
    if splitter_type == "markdown_header":
        return config["class"](**config["kwargs"])
    
    kwargs = {
        **config["kwargs"],
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    }
    return config["class"](**kwargs)
