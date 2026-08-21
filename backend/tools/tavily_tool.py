import json
import os
from agents import function_tool


@function_tool
def search_analyst_news(ticker: str, company_name: str) -> str:
    """Search for recent analyst ratings, upgrades, downgrades, and price target changes."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    query = (
        f"{company_name} {ticker} analyst rating upgrade downgrade price target "
        f"wall street coverage initiate 2024 2025"
    )

    try:
        results = client.search(query, max_results=10, search_depth="advanced")
        articles = [
            {
                "title": r.get("title", ""),
                "content": r.get("content", "")[:400],
                "url": r.get("url", ""),
                "published_date": r.get("published_date", ""),
            }
            for r in results.get("results", [])
        ]
        return json.dumps({
            "query": query,
            "articles": articles,
            "instruction": (
                "Extract analyst firm names, rating actions (upgrade/downgrade/initiate/reiterate), "
                "specific ratings (Buy/Hold/Sell/Overweight etc.), and price targets from the articles. "
                "Note the dates of each call."
            ),
        })
    except Exception as e:
        return json.dumps({"error": str(e), "articles": []})


@function_tool
def search_comparable_companies(company_name: str, sector: str, industry: str) -> str:
    """Search for publicly traded comparable companies in the same sector/industry."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    query = (
        f"publicly traded companies comparable to {company_name} "
        f"in {industry} {sector} sector stock ticker competitors peers"
    )

    try:
        results = client.search(query, max_results=10, search_depth="advanced")
        candidates = [
            {
                "title": r.get("title", ""),
                "content": r.get("content", "")[:300],
                "url": r.get("url", ""),
            }
            for r in results.get("results", [])
        ]
        return json.dumps({
            "query": query,
            "candidates": candidates,
            "instruction": (
                "Extract company names and stock tickers from the search results above. "
                "Then call get_stock_financials for each valid ticker to verify it exists "
                "and retrieve its multiples."
            ),
        })
    except Exception as e:
        return json.dumps({"error": str(e), "candidates": []})
