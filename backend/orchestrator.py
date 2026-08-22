import asyncio
import json
import os
import re
from datetime import date, timedelta
from typing import AsyncGenerator

from agents import Agent, Runner
from dotenv import load_dotenv

load_dotenv()

from tools.yfinance_tool import get_stock_financials, get_price_history_raw, get_insider_trades_raw
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
        "1. Call get_stock_financials on the subject ticker to get its sector, industry, and market_cap.\n"
        "2. Convert market_cap (in raw dollars) to billions: market_cap_billions = market_cap / 1e9.\n"
        "3. Call search_comparable_companies with company_name, sector, industry, and market_cap_billions.\n"
        "4. Parse the search results to identify candidate tickers.\n"
        "5. Call get_stock_financials for each candidate.\n"
        "6. Apply these MANDATORY filters — reject any candidate that fails either:\n"
        "   a) Market cap outside 0.05x–20x of the subject's market cap\n"
        "   b) Fundamentally different business model (e.g., pure hardware vs. software+services hybrid)\n"
        "7. Select the 3-5 best remaining comps. Prefer direct competitors analysts cite as peers.\n"
        "Return a JSON object with:\n"
        "  subject: {ticker, company_name, market_cap_billions, pe_trailing, pe_forward, ev_ebitda, "
        "gross_margin, operating_margin, revenue_ttm}\n"
        "  peers: array of peer objects with: ticker, company_name, market_cap_billions, pe_trailing, "
        "pe_forward, ev_ebitda, revenue_ttm, gross_margin, operating_margin, justification\n"
        "  peer_median: {pe_trailing, pe_forward, ev_ebitda, gross_margin, operating_margin}\n"
        "  premium_discount: {pe_trailing_pct, pe_forward_pct, ev_ebitda_pct} — subject vs peer median\n"
        "  comps_quality_note: 1 sentence rating the quality/relevance of these comps\n"
        "Output ONLY valid JSON, no prose."
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
        "  risks: array of 5-7 objects each with:\n"
        "    title: short noun phrase (specific, not generic boilerplate)\n"
        "    summary: 2-3 sentences plain English — cite specific figures, jurisdictions, or thresholds "
        "where present. No generic statements like 'macroeconomic conditions may affect revenue'.\n"
        "    severity: 'High'/'Medium'/'Low' based on realistic threat to revenue/margin/going-concern\n"
        "    category: one of 'Regulatory', 'Competitive', 'Macro', 'Operational', 'Financial', 'Geopolitical'\n"
        "Prioritize risks that are SPECIFIC to this company and material to its investment thesis. "
        "Avoid boilerplate risks that apply to every public company.\n"
        "Output ONLY valid JSON, no prose."
    ),
    tools=[get_10k_risk_factors],
    model="gpt-4o",
)

analyst_coverage_agent = Agent(
    name="Analyst Coverage Agent",
    instructions=(
        "You are an Analyst Coverage Agent. Given a ticker:\n"
        "1. Call get_stock_financials to get consensus target prices, recommendation_key, "
        "num_analyst_opinions, and recent_recommendations.\n"
        "2. Call search_analyst_news to find recent analyst upgrades, downgrades, initiations, "
        "and price target changes from Wall Street firms.\n"
        f"3. Today's date is {date.today().isoformat()}. Flag any analyst call older than 90 days "
        "with a staleness warning. Exclude calls older than 12 months from consensus metrics.\n"
        "Return a JSON object with:\n"
        "  consensus_recommendation: human-readable string (e.g. 'Buy', 'Hold', 'Strong Buy')\n"
        "  num_analysts: integer\n"
        "  current_price: float\n"
        "  target_price_low: float — analyst low target from yfinance\n"
        "  target_price_mean: float — analyst mean/consensus target from yfinance\n"
        "  target_price_median: float — analyst median target from yfinance\n"
        "  target_price_high: float — analyst high target from yfinance\n"
        "  implied_upside_to_low_pct: float — % from current price to low target (can be negative = downside)\n"
        "  implied_upside_to_mean_pct: float — % from current price to mean target\n"
        "  implied_upside_to_high_pct: float — % from current price to high target\n"
        "  target_range_width_pct: float — (high - low) / current_price * 100, measures analyst disagreement\n"
        "  data_as_of: today's date string\n"
        "  recent_calls: array of up to 8 objects with "
        "{firm, action, rating, price_target, date, is_stale (bool, true if >90 days old)}\n"
        "  stale_calls_excluded: integer count of calls excluded for being >12 months old\n"
        "  data_freshness_note: 1-2 sentences on how fresh the analyst data is and any caveats\n"
        "  sentiment_summary: 3-4 sentence synthesis of overall analyst sentiment\n"
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
        "  multiple_re_rating_needed: boolean\n"
        "  re_rating_rationale: string\n"
        "Be specific. Reference actual numbers from the inputs. No generic statements.\n"
        "Output ONLY valid JSON, no prose."
    ),
    tools=[],
    model="gpt-4o",
)

analyst_agent = Agent(
    name="Analyst Agent",
    instructions=(
        "You are the Analyst Agent. You receive JSON with financial_snapshot, comps, risk_summary, "
        "analyst_coverage, and insider_activity.\n"
        "Produce a JSON object:\n"
        "  signal: exactly 'BUY', 'HOLD', or 'SELL'\n"
        "  confidence: 'High', 'Medium', or 'Low'\n"
        "  confidence_drivers: array of 2-4 strings — list the specific inputs that most drove or "
        "limited your confidence (e.g. 'Strong earnings growth trajectory', 'Stale analyst data — "
        "most calls >6 months old', 'Comps set is thin/poorly matched', 'No balance sheet data'). "
        "ALWAYS populate this — never leave empty. This is how readers know what to trust.\n"
        "  rationale: paragraph citing at least one valuation metric, one risk factor, and one "
        "growth/margin trend WITH specific numbers — no generic statements\n"
        "  valuation_context: object with:\n"
        "    current_pe_trailing: float\n"
        "    current_pe_forward: float\n"
        "    peer_median_pe_forward: float or null\n"
        "    premium_to_peers_pct: float or null\n"
        "    valuation_assessment: 'Rich'/'Fair'/'Cheap' with 1-sentence rationale\n"
        "  capital_return_summary: 2-3 sentences covering dividend yield, buyback program, "
        "net cash/debt position — use data from financial_snapshot\n"
        "  insider_signal: object with net_signal ('Bullish'/'Bearish'/'Neutral'/'Unknown'), "
        "buys_count, sells_count, and a 1-sentence interpretation of what recent insider activity implies\n"
        "  price_target_range: object with low, mean, median, high, current_price, "
        "upside_to_low_pct, upside_to_mean_pct, upside_to_high_pct, range_width_pct, "
        "and range_interpretation ('Wide disagreement'/'Moderate spread'/'Tight consensus')\n"
        "  comps_analysis: object with pe, ev_ebitda, revenue keys each containing "
        "{subject, peer_median, premium_discount_pct}\n"
        "  risk_summary: 2-3 sentence synthesis of the highest-severity risks\n"
        "  data_quality_flags: array of strings — list any data quality issues: stale analyst calls, "
        "thin comps set, missing balance sheet, etc. Empty array if no issues.\n"
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
        "### Balance Sheet & Capital Returns\n"
        "### Revenue & Margin Trends\n"
        "### Peer Comparison\n"
        "### Analyst Coverage & Consensus\n"
        "### Risk Factors\n"
        "### Path to Upside — What Needs to Change\n"
        "### Investment Signal\n"
        "### Insider Activity\n"
        "### Data Sources & As-Of Dates\n\n"
        "Formatting rules:\n"
        "- Use Markdown tables for: Key Financials, Peer Comparison, analyst calls, scenarios.\n"
        "- Key Financials table: include price, market cap, PE trailing/forward, EV/EBITDA, PEG, "
        "P/S, gross margin, operating margin, net margin, EPS trailing/forward, revenue TTM.\n"
        "- Balance Sheet & Capital Returns: table with total debt, total cash, net cash/debt, "
        "D/E ratio, dividend yield, annual dividend rate, shares outstanding, shares trend "
        "(note if shrinking = buybacks). 1-2 sentences on capital return program significance.\n"
        "- Revenue & Margin Trends: show YoY revenue growth rates for the past 3 years. "
        "Show quarterly revenue for last 4 quarters if available. Note whether gross/operating "
        "margins are expanding or contracting vs. prior year. Flag segment mix if known.\n"
        "- Peer Comparison: table with all peers. Note the comps_quality_note below the table. "
        "Show premium/discount to peer median for PE and EV/EBITDA.\n"
        "- Analyst Coverage: show price target range prominently — format as:\n"
        "  **Price Target Range: $LOW — $HIGH (Mean: $MEAN · Median: $MEDIAN)**\n"
        "  Then a sub-line: 'Downside to low: X% | Upside to mean: Y% | Upside to high: Z%'\n"
        "  Note target_range_width_pct: if >30% say 'Wide analyst disagreement'; if <15% say 'Tight consensus'.\n"
        "  Then show the recent calls table (Firm | Action | Rating | Target | Date). "
        "  Mark stale calls (>90 days) with ⚠ STALE. Show data_freshness_note as a callout.\n"
        "- Risk Factors: include severity [High/Medium/Low] and category tags. "
        "Bold the most company-specific, material risks.\n"
        "- Path to Upside: numbered list of what_needs_to_change with current vs. required figures. "
        "Bear/Base/Bull scenario table. Near-term catalysts table.\n"
        "- Insider Activity: table of recent trades (Date | Insider | Title | Transaction | Shares | Value). "
        "Show net_signal as a badge (Bullish/Bearish/Neutral) with buys vs sells count. "
        "Include 1-2 sentences interpreting the insider activity. "
        "If no trades available, note 'No recent insider transactions reported.'\n"
        "- Investment Signal: show signal, confidence, confidence_drivers as a bulleted list, "
        "valuation_assessment, capital_return_summary, and rationale. "
        "If data_quality_flags is non-empty, show a ⚠ Data Quality Notice section listing them.\n"
        "Always add this disclaimer:\n"
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

    # Fan out — financial, comps, risk, analyst coverage, and price history run in parallel
    yield sse({"stage": "financial_data", "status": "running"})
    yield sse({"stage": "comps", "status": "running"})
    yield sse({"stage": "risk", "status": "running"})
    yield sse({"stage": "analyst_coverage", "status": "running"})

    loop = asyncio.get_event_loop()
    financial_raw, comps_raw, risk_raw, coverage_raw, price_history, insider_data = await asyncio.gather(
        run_agent(financial_data_agent, f"Fetch financial data for ticker: {ticker}"),
        run_agent(comps_agent, f"Find comparable companies for ticker: {ticker}"),
        run_agent(risk_agent, f"Get 10-K risk factors for ticker: {ticker}"),
        run_agent(analyst_coverage_agent, f"Get analyst coverage and consensus for ticker: {ticker}"),
        loop.run_in_executor(None, get_price_history_raw, ticker),
        loop.run_in_executor(None, get_insider_trades_raw, ticker),
    )

    # Stream price data immediately so chart renders before the report is ready
    yield sse({"stage": "price_data", "status": "done", "price_history": price_history})

    yield sse({"stage": "financial_data", "status": "done"})
    yield sse({"stage": "comps", "status": "done"})
    yield sse({"stage": "risk", "status": "done"})
    yield sse({"stage": "analyst_coverage", "status": "done"})

    financial_data = safe_parse(financial_raw, {"error": "Financial data unavailable", "ticker": ticker})
    comps_data = safe_parse(comps_raw, {"peers": [], "comps_quality_note": "No comps data available."})
    risk_data = safe_parse(
        risk_raw,
        {"status": "not_available", "risks": [], "reason": "Risk data unavailable"},
    )
    coverage_data = safe_parse(
        coverage_raw,
        {
            "consensus_recommendation": "N/A",
            "recent_calls": [],
            "sentiment_summary": "Data unavailable.",
            "data_freshness_note": "No analyst data retrieved.",
            "stale_calls_excluded": 0,
        },
    )

    # Analyst verdict
    yield sse({"stage": "analyst", "status": "running"})
    analyst_input = json.dumps(
        {
            "financial_snapshot": financial_data,
            "comps": comps_data,
            "risk_summary": risk_data,
            "analyst_coverage": coverage_data,
            "insider_activity": insider_data,
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
            "confidence_drivers": ["Insufficient data for analysis"],
            "rationale": "Insufficient data for analysis.",
            "comps_analysis": {},
            "risk_summary": "Data unavailable.",
            "data_quality_flags": ["Insufficient data"],
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
            "insider_activity": insider_data,
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
