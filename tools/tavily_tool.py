import json
import os
from datetime import date
from agents import function_tool


@function_tool
def search_analyst_news(ticker: str, company_name: str) -> str:
    """Search for recent analyst ratings, upgrades, downgrades, and price target changes."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    current_year = date.today().year
    query = (
        f"{company_name} {ticker} analyst rating upgrade downgrade price target "
        f"wall street coverage initiate {current_year} {current_year - 1}"
    )

    try:
        results = client.search(query, max_results=12, search_depth="advanced")
        articles = [
            {
                "title": r.get("title", ""),
                "content": r.get("content", "")[:500],
                "url": r.get("url", ""),
                "published_date": r.get("published_date", ""),
            }
            for r in results.get("results", [])
        ]
        staleness_cutoff = date.today().replace(year=date.today().year - 1).isoformat()
        return json.dumps({
            "query": query,
            "as_of": date.today().isoformat(),
            "staleness_cutoff_90d": staleness_cutoff,
            "articles": articles,
            "instruction": (
                "Extract analyst firm names, rating actions (upgrade/downgrade/initiate/reiterate), "
                "specific ratings (Buy/Hold/Sell/Overweight etc.), and price targets from the articles. "
                f"Flag any call dated before {staleness_cutoff} as STALE. "
                "Exclude stale calls from the consensus calculation and note how many were excluded. "
                "Only include calls from the past 12 months in recent_calls; calls 90+ days old must be "
                "labeled with a staleness warning in the date field."
            ),
        })
    except Exception as e:
        return json.dumps({"error": str(e), "articles": []})


@function_tool
def search_comparable_companies(
    company_name: str, sector: str, industry: str, market_cap_billions: float
) -> str:
    """Search for publicly traded comparable companies in the same sector/industry and market-cap tier."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

    # Determine cap tier for better comps
    if market_cap_billions >= 500:
        cap_tier = "mega-cap large-cap"
    elif market_cap_billions >= 50:
        cap_tier = "large-cap mid-cap"
    elif market_cap_billions >= 5:
        cap_tier = "mid-cap"
    else:
        cap_tier = "small-cap mid-cap"

    query = (
        f"publicly traded {cap_tier} companies comparable to {company_name} "
        f"in {industry} {sector} sector stock ticker competitors peers similar business model"
    )

    try:
        results = client.search(query, max_results=12, search_depth="advanced")
        candidates = [
            {
                "title": r.get("title", ""),
                "content": r.get("content", "")[:400],
                "url": r.get("url", ""),
            }
            for r in results.get("results", [])
        ]
        min_cap = round(market_cap_billions * 0.05, 1)
        max_cap = round(market_cap_billions * 20, 1)
        return json.dumps({
            "query": query,
            "subject_market_cap_billions": market_cap_billions,
            "acceptable_market_cap_range_billions": {"min": min_cap, "max": max_cap},
            "candidates": candidates,
            "instruction": (
                "Extract company names and stock tickers from the search results above. "
                "Then call get_stock_financials for each valid ticker. "
                f"REJECT any company whose market_cap differs from {market_cap_billions}B by more than 20x "
                f"(acceptable range: ${min_cap}B–${max_cap}B). "
                "REJECT any company whose business model or revenue mix is fundamentally different "
                "(e.g., hardware-only vs. software+services). "
                "Prefer companies with similar margin profiles and revenue scale. "
                "Prioritize direct competitors and companies that analysts themselves cite as peers."
            ),
        })
    except Exception as e:
        return json.dumps({"error": str(e), "candidates": []})
