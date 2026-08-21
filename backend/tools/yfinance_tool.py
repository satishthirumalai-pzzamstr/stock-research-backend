import json
from datetime import date
from agents import function_tool


@function_tool
def get_stock_financials(ticker: str) -> str:
    """Get financial data for a stock ticker using yfinance."""
    import yfinance as yf

    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}

        # Revenue history from annual financials
        revenue_history: list = []
        try:
            fin = stock.financials
            if fin is not None and not fin.empty:
                for label in ("Total Revenue", "Revenue"):
                    if label in fin.index:
                        revenue_history = [
                            float(v) if v is not None and str(v) != "nan" else None
                            for v in fin.loc[label].iloc[:3].tolist()
                        ]
                        break
        except Exception:
            pass

        # Free cash flow from cash flow statement
        free_cash_flow = None
        try:
            cf = stock.cashflow
            if cf is not None and not cf.empty:
                for label in ("Free Cash Flow", "FreeCashFlow"):
                    if label in cf.index:
                        val = cf.loc[label].iloc[0]
                        free_cash_flow = float(val) if val is not None and str(val) != "nan" else None
                        break
        except Exception:
            pass

        def safe(key):
            v = info.get(key)
            if v is None or str(v) == "nan":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        result = {
            "ticker": ticker.upper(),
            "company_name": info.get("longName") or info.get("shortName") or ticker,
            "sector": info.get("sector") or "Unknown",
            "industry": info.get("industry") or "Unknown",
            "price": safe("currentPrice") or safe("regularMarketPrice"),
            "market_cap": safe("marketCap"),
            "pe_trailing": safe("trailingPE"),
            "pe_forward": safe("forwardPE"),
            "ev_ebitda": safe("enterpriseToEbitda"),
            "revenue_ttm": safe("totalRevenue"),
            "revenue_history": revenue_history,
            "gross_margin": safe("grossMargins"),
            "operating_margin": safe("operatingMargins"),
            "ebitda": safe("ebitda"),
            "net_income": safe("netIncomeToCommon"),
            "free_cash_flow": free_cash_flow,
            "52wk_low": safe("fiftyTwoWeekLow"),
            "52wk_high": safe("fiftyTwoWeekHigh"),
            "analyst_target_price": safe("targetMeanPrice"),
            "analyst_target_high": safe("targetHighPrice"),
            "analyst_target_low": safe("targetLowPrice"),
            "analyst_target_median": safe("targetMedianPrice"),
            "num_analyst_opinions": info.get("numberOfAnalystOpinions"),
            "recommendation_key": info.get("recommendationKey"),
            "as_of": date.today().isoformat(),
        }

        # Recent recommendations history (last 5 changes)
        try:
            recs = stock.recommendations
            if recs is not None and not recs.empty:
                recent = recs.tail(5).reset_index()
                result["recent_recommendations"] = [
                    {
                        "date": str(row.get("Date", row.get("date", ""))),
                        "firm": row.get("Firm", row.get("firm", "")),
                        "to_grade": row.get("To Grade", row.get("toGrade", "")),
                        "from_grade": row.get("From Grade", row.get("fromGrade", "")),
                        "action": row.get("Action", row.get("action", "")),
                    }
                    for _, row in recent.iterrows()
                ]
        except Exception:
            result["recent_recommendations"] = []

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e), "ticker": ticker})
