"""Web search via Tavily API."""

import logging

from langchain_tavily import TavilySearch

logger = logging.getLogger(__name__)


async def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web via Tavily. Returns {results, images, answer}."""
    search = TavilySearch(
        max_results=max_results,
        search_depth="advanced",
        include_images=True,
        include_answer=True,
    )

    logger.info("web_search: query=%s, max_results=%d", query[:100], max_results)
    results = await search.ainvoke({"query": query})
    logger.info(
        "web_search: got %d results, %d images",
        len(results.get("results", [])),
        len(results.get("images", [])),
    )
    return results
