import asyncio
import json
import os
import re
from typing import AsyncGenerator

from agents import Agent, Runner
from dotenv import load_dotenv

load_dotenv()

from tools.yfinance_tool import get_stock_financials
from tools.tavily_tool import search_comparable_companies, search_analyst_news
from tools.edgar_tool import get_10k_risk_factors

# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

financial_data_agent = Agent(
    name="Financial Data Agent",
    instructions=(
        "You are a Financial Data Agent. Call get_stock_financials with the given ticker. "
        "Return the raw JSON exactly as returned by the tool. "
        "Do not add opinions or speculation. Report missing fields as null. "
        "Output ONLY valid JSON, no prose."
    ),
    tools=[get_stock_financials],
    model="gpt-4o-mini",
)

comps_agent = Agent(
    name="Comps Agent",
    instructions=(
        "You are a Comps Agent. Given a ticker:\n"
        "1. Call get_stock_financials on the subject ticker to get its sector and industry.\n"
        "2. Call search_comparable_companies with the company name, sector, and industry.\n"
        "3. Parse the search results to identify 4-6 candidate tickers.\n"
        "4. Call get_stock_financials for each candidate to verify it resolves and fetch multiples.\n"
        "5. Select the 3-5 best comparable companies (same sector, similar model or market-cap tier).\n"
        "Return a JSON array of peer objects with these fields: "
        "ticker, company_name, pe_trailing, pe_forward, ev_ebitda, revenue_ttm, "
        "gross_margin, operating_margin, justification.\n"
        "justification is a 1-sentence explanation of why this company is a valid comp.\n"
        "Output ONLY a valid JSON array, no prose."
    ),
    tools=[get_stock_financials, search_comparable_companies],
    model="gpt-4o",
)

risk_agent = Agent(
    name="Risk Agent",
    instructions=(
        "You are a Risk Agent. Call get_10k_risk_factors with the given ticker.\n"
        "If status is 'not_available', return that JSON as-is with an empty risks array.\n"
        "If status is 'ok', read the raw_risk_text and produce a JSON object:\n"
        "  status: 'ok'\n"
        "  filing_type: the form type from the tool result\n"
        "  filing_date: the filing date from the tool result\n"
        "  risks: array of 5-7 objects each with title (short noun phrase), "
        "summary (1-2 sentences plain English, no legal boilerplate), "
        "severity ('High'/'Medium'/'Low' based on threat to revenue/margin/going-concern)\n"
        "Output ONLY valid JSON, no prose."
    ),
    tools=[get_10k_risk_factors],
    model="gpt-4o",
)

analyst_coverage_agent = Agent(
    name="Analyst Coverage Agent",
    instructions=(
        "You are an Analyst Coverage Agent. Given a ticker:\n"
        "1. Call get_stock_financials to get the consensus target prices, recommendation_key, "
        "num_analyst_opinions, and recent_recommendations.\n"
        "2. Call search_analyst_news to find recent analyst upgrades, downgrades, initiations, "
        "and price target changes from Wall Street firms.\n"
        "Return a JSON object with:\n"
        "  consensus_recommendation: human-readable string (e.g. 'Buy', 'Hold', 'Strong Buy')\n"
        "  num_analysts: integer\n"
        "  target_price_consensus: float (mean/median target)\n"
        "  target_price_low: float\n"
        "  target_price_high: float\n"
        "  current_price: float\n"
        "  implied_upside_pct: float (% upside from current to consensus target)\n"
        "  recent_calls: array of up to 8 objects with "
        "{firm, action, rating, price_target, date} extracted from search results\n"
        "  sentiment_summary: 3-4 sentence synthesis of overall analyst sentiment, "
        "noting any notable disagreements or conviction calls\n"
        "Output ONLY valid JSON, no prose."
    ),
    tools=[get_stock_financials, search_analyst_news],
    model="gpt-4o",
)

catalyst_agent = Agent(
    name="Catalyst Agent",
    instructions=(
        "You are a Catalyst Agent. You do not call external tools. "
        "You receive JSON containing financial_snapshot, analyst_coverage, comps, and analyst_verdict.\n"
        "Your job: reason concretely about what has to change for this stock to move meaningfully higher.\n"
        "Return a JSON object with:\n"
        "  what_needs_to_change: array of 5-8 specific, quantified statements — each is a concrete "
        "threshold or milestone the company must hit (e.g. 'Revenue growth must reaccelerate from "
        "current 6% to 12%+ YoY', 'Operating margin must expand from 18% to 22%+ over 2 years', "
        "'Multiple must re-rate from 22x to 28x forward P/E as growth premium returns'). "
        "Always cite current figures vs. required figures.\n"
        "  near_term_catalysts: array of 4-6 upcoming events or triggers that could move the stock "
        "(earnings prints, product launches, regulatory decisions, macro shifts, M&A). "
        "Each has: event (string), timing (string), potential_impact ('High'/'Medium'/'Low'), "
        "direction ('Upside'/'Downside'/'Neutral')\n"
        "  bear_case: {narrative: string, key_risk: string, implied_price: float or null}\n"
        "  base_case: {narrative: string, key_driver: string, implied_price: float or null}\n"
        "  bull_case: {narrative: string, key_catalyst: string, implied_price: float or null}\n"
        "  multiple_re_rating_needed: boolean — true if the stock must expand its multiple "
        "(not just grow earnings) to reach the analyst consensus target\n"
        "  re_rating_rationale: string — explain why or why not\n"
        "Be specific. Reference actual numbers from the inputs. No generic statements.\n"
        "Output ONLY valid JSON, no prose."
    ),
    tools=[],
    model="gpt-4o",
)

analyst_agent = Agent(
    name="Analyst Agent",
    instructions=(
        "You are the Analyst Agent. You receive JSON with financial_snapshot, comps, and risk_summary.\n"
        "Produce a JSON object:\n"
        "  signal: exactly 'BUY', 'HOLD', or 'SELL'\n"
        "  confidence: 'High', 'Medium', or 'Low' (lower if data is incomplete)\n"
        "  rationale: paragraph citing at least one valuation metric, one risk factor, "
        "and one growth/margin trend WITH specific numbers — no generic statements\n"
        "  comps_analysis: object with pe, ev_ebitda, revenue keys each containing "
        "{subject, peer_median, premium_discount_pct}\n"
        "  risk_summary: 2-3 sentence synthesis of the key risks\n"
        "This is for educational/research purposes — do not frame as personalized financial advice.\n"
        "Output ONLY valid JSON, no prose."
    ),
    tools=[],
    model="gpt-4o",
)

writer_agent = Agent(
    name="Writer Agent",
    instructions=(
        "You are the Writer Agent. Format a Markdown equity research report.\n"
        "Use these exact sections in this order:\n"
        "## {TICKER} — {Company Name} Research Report\n"
        "### Company Overview\n"
        "### Key Financials\n"
        "### Peer Comparison\n"
        "### Analyst Coverage & Consensus\n"
        "### Risk Factors\n"
        "### Path to Upside — What Needs to Change\n"
        "### Investment Signal\n"
        "### Data Sources & As-Of Dates\n\n"
        "Use Markdown tables for financials, peer comparison, and analyst calls. Keep prose concise.\n"
        "For Risk Factors, include severity tags like **[High]**, **[Medium]**, **[Low]** inline.\n"
        "For Analyst Coverage, include a table of recent analyst calls (Firm | Action | Rating | Target | Date) "
        "and note the consensus target vs current price with implied upside %.\n"
        "For Path to Upside, list the what_needs_to_change items as a numbered list with current vs required "
        "figures clearly shown. Include the bear/base/bull scenario table. List near-term catalysts with "
        "impact and direction tags.\n"
        "Note any missing data in the relevant section rather than silently omitting it.\n"
        "Always include this disclaimer line at the end of Investment Signal:\n"
        "> This report is generated for educational purposes and is not personalized investment advice.\n"
        "Output ONLY the Markdown report, no extra commentary."
    ),
    tools=[],
    model="gpt-4o",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def safe_parse(raw: str, default):
    """Parse JSON from agent output, tolerating prose wrapping."""
    try:
        return json.loads(raw)
    except Exception:
        # Try to extract the first JSON object or array
        for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
            match = re.search(pattern, raw)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
        return default


async def run_agent(agent: Agent, input_text: str) -> str:
    try:
        result = await Runner.run(agent, input_text)
        return result.final_output
    except Exception as e:
        return json.dumps({"error": str(e)})


async def validate_ticker(ticker: str) -> dict:
    import yfinance as yf
    try:
        info = yf.Ticker(ticker).info or {}
        has_name = bool(info.get("longName") or info.get("shortName"))
        has_price = info.get("regularMarketPrice") or info.get("currentPrice")
        if not has_name and not has_price:
            return {"valid": False, "reason": f"Ticker '{ticker}' not found or returned no data"}
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "reason": str(e)}


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_research_pipeline(ticker: str) -> AsyncGenerator[str, None]:
    ticker = ticker.upper().strip()

    # Validate
    yield sse({"stage": "validation", "status": "running"})
    v = await validate_ticker(ticker)
    if not v["valid"]:
        yield sse({"stage": "error", "status": "failed", "message": v.get("reason", "Invalid ticker")})
        return
    yield sse({"stage": "validation", "status": "done"})

    # Fan out — financial, comps, risk, and analyst coverage run in parallel
    yield sse({"stage": "financial_data", "status": "running"})
    yield sse({"stage": "comps", "status": "running"})
    yield sse({"stage": "risk", "status": "running"})
    yield sse({"stage": "analyst_coverage", "status": "running"})

    financial_raw, comps_raw, risk_raw, coverage_raw = await asyncio.gather(
        run_agent(financial_data_agent, f"Fetch financial data for ticker: {ticker}"),
        run_agent(comps_agent, f"Find comparable companies for ticker: {ticker}"),
        run_agent(risk_agent, f"Get 10-K risk factors for ticker: {ticker}"),
        run_agent(analyst_coverage_agent, f"Get analyst coverage and consensus for ticker: {ticker}"),
    )

    yield sse({"stage": "financial_data", "status": "done"})
    yield sse({"stage": "comps", "status": "done"})
    yield sse({"stage": "risk", "status": "done"})
    yield sse({"stage": "analyst_coverage", "status": "done"})

    financial_data = safe_parse(financial_raw, {"error": "Financial data unavailable", "ticker": ticker})
    comps_data = safe_parse(comps_raw, [])
    risk_data = safe_parse(
        risk_raw,
        {"status": "not_available", "risks": [], "reason": "Risk data unavailable"},
    )
    coverage_data = safe_parse(
        coverage_raw,
        {"consensus_recommendation": "N/A", "recent_calls": [], "sentiment_summary": "Data unavailable."},
    )

    # Analyst verdict
    yield sse({"stage": "analyst", "status": "running"})
    analyst_input = json.dumps(
        {
            "financial_snapshot": financial_data,
            "comps": comps_data,
            "risk_summary": risk_data,
            "analyst_coverage": coverage_data,
        },
        indent=2,
    )
    analyst_raw = await run_agent(
        analyst_agent,
        f"Analyze this equity research data and produce a BUY/HOLD/SELL verdict:\n{analyst_input}",
    )
    analyst_verdict = safe_parse(
        analyst_raw,
        {
            "signal": "HOLD",
            "confidence": "Low",
            "rationale": "Insufficient data for analysis.",
            "comps_analysis": {},
            "risk_summary": "Data unavailable.",
        },
    )
    yield sse({"stage": "analyst", "status": "done"})

    # Catalyst analysis
    yield sse({"stage": "catalyst", "status": "running"})
    catalyst_input = json.dumps(
        {
            "financial_snapshot": financial_data,
            "analyst_coverage": coverage_data,
            "comps": comps_data,
            "analyst_verdict": analyst_verdict,
        },
        indent=2,
    )
    catalyst_raw = await run_agent(
        catalyst_agent,
        f"Identify what needs to change for this stock to move higher and produce scenario analysis:\n{catalyst_input}",
    )
    catalyst_data = safe_parse(
        catalyst_raw,
        {
            "what_needs_to_change": ["Insufficient data for catalyst analysis."],
            "near_term_catalysts": [],
            "bear_case": {"narrative": "N/A", "key_risk": "N/A", "implied_price": None},
            "base_case": {"narrative": "N/A", "key_driver": "N/A", "implied_price": None},
            "bull_case": {"narrative": "N/A", "key_catalyst": "N/A", "implied_price": None},
            "multiple_re_rating_needed": False,
            "re_rating_rationale": "N/A",
        },
    )
    yield sse({"stage": "catalyst", "status": "done"})

    # Writer
    yield sse({"stage": "writer", "status": "running"})
    writer_input = json.dumps(
        {
            "ticker": ticker,
            "financial_snapshot": financial_data,
            "comps": comps_data,
            "risk_summary": risk_data,
            "analyst_coverage": coverage_data,
            "catalyst_analysis": catalyst_data,
            "analyst_verdict": analyst_verdict,
        },
        indent=2,
    )
    report_markdown = await run_agent(
        writer_agent,
        f"Write the equity research report for this data:\n{writer_input}",
    )
    yield sse({"stage": "writer", "status": "done"})

    signal = analyst_verdict.get("signal", "HOLD") if isinstance(analyst_verdict, dict) else "HOLD"
    confidence = analyst_verdict.get("confidence", "Low") if isinstance(analyst_verdict, dict) else "Low"

    yield sse({
        "stage": "complete",
        "status": "done",
        "report": report_markdown,
        "signal": signal,
        "confidence": confidence,
    })
