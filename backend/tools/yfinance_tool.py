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

        def safe(key):
            v = info.get(key)
            if v is None or str(v) == "nan":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        # Annual revenue history (up to 4 years)
        revenue_history: list = []
        revenue_dates: list = []
        try:
            fin = stock.financials
            if fin is not None and not fin.empty:
                for label in ("Total Revenue", "Revenue"):
                    if label in fin.index:
                        row = fin.loc[label].iloc[:4]
                        revenue_history = [
                            float(v) if v is not None and str(v) != "nan" else None
                            for v in row.tolist()
                        ]
                        revenue_dates = [str(c)[:10] for c in row.index.tolist()]
                        break
        except Exception:
            pass

        # YoY revenue growth rates
        revenue_growth_yoy: list = []
        try:
            for i in range(len(revenue_history) - 1):
                curr, prev = revenue_history[i], revenue_history[i + 1]
                if curr is not None and prev and prev != 0:
                    revenue_growth_yoy.append(round((curr - prev) / abs(prev) * 100, 1))
                else:
                    revenue_growth_yoy.append(None)
        except Exception:
            pass

        # Quarterly revenue (last 4 quarters)
        quarterly_revenue: list = []
        quarterly_revenue_dates: list = []
        quarterly_gross_margin: list = []
        quarterly_operating_margin: list = []
        try:
            qfin = stock.quarterly_financials
            if qfin is not None and not qfin.empty:
                for label in ("Total Revenue", "Revenue"):
                    if label in qfin.index:
                        row = qfin.loc[label].iloc[:4]
                        quarterly_revenue = [
                            float(v) if v is not None and str(v) != "nan" else None
                            for v in row.tolist()
                        ]
                        quarterly_revenue_dates = [str(c)[:10] for c in row.index.tolist()]
                        break
                # Gross margin trend
                if "Gross Profit" in qfin.index and "Total Revenue" in qfin.index:
                    gp = qfin.loc["Gross Profit"].iloc[:4]
                    rev = qfin.loc["Total Revenue"].iloc[:4]
                    quarterly_gross_margin = [
                        round(float(g) / float(r) * 100, 1)
                        if g is not None and r is not None and str(g) != "nan" and str(r) != "nan" and float(r) != 0
                        else None
                        for g, r in zip(gp, rev)
                    ]
                # Operating margin trend
                if "Operating Income" in qfin.index and "Total Revenue" in qfin.index:
                    oi = qfin.loc["Operating Income"].iloc[:4]
                    rev = qfin.loc["Total Revenue"].iloc[:4]
                    quarterly_operating_margin = [
                        round(float(o) / float(r) * 100, 1)
                        if o is not None and r is not None and str(o) != "nan" and str(r) != "nan" and float(r) != 0
                        else None
                        for o, r in zip(oi, rev)
                    ]
        except Exception:
            pass

        # Free cash flow
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

        # Shares outstanding history for buyback trend
        shares_history: list = []
        try:
            bs = stock.balance_sheet
            if bs is not None and not bs.empty:
                for label in ("Ordinary Shares Number", "Share Issued", "CommonStock"):
                    if label in bs.index:
                        row = bs.loc[label].iloc[:4]
                        shares_history = [
                            float(v) if v is not None and str(v) != "nan" else None
                            for v in row.tolist()
                        ]
                        break
        except Exception:
            pass

        # Capital structure
        total_debt = safe("totalDebt")
        total_cash = safe("totalCash")
        net_cash = None
        if total_cash is not None and total_debt is not None:
            net_cash = total_cash - total_debt
        elif total_cash is not None:
            net_cash = total_cash

        result = {
            "ticker": ticker.upper(),
            "company_name": info.get("longName") or info.get("shortName") or ticker,
            "sector": info.get("sector") or "Unknown",
            "industry": info.get("industry") or "Unknown",
            "price": safe("currentPrice") or safe("regularMarketPrice"),
            "market_cap": safe("marketCap"),
            "beta": safe("beta"),
            # Valuation
            "pe_trailing": safe("trailingPE"),
            "pe_forward": safe("forwardPE"),
            "ev_ebitda": safe("enterpriseToEbitda"),
            "price_to_sales": safe("priceToSalesTrailing12Months"),
            "price_to_book": safe("priceToBook"),
            "peg_ratio": safe("pegRatio"),
            # Earnings
            "eps_trailing": safe("trailingEps"),
            "eps_forward": safe("forwardEps"),
            "eps_growth_estimate": safe("earningsGrowth"),
            "revenue_growth_yoy_latest": revenue_growth_yoy[0] if revenue_growth_yoy else None,
            # Revenue
            "revenue_ttm": safe("totalRevenue"),
            "revenue_history": revenue_history,
            "revenue_dates": revenue_dates,
            "revenue_growth_yoy": revenue_growth_yoy,
            # Margins
            "gross_margin": safe("grossMargins"),
            "operating_margin": safe("operatingMargins"),
            "net_margin": safe("profitMargins"),
            "ebitda_margin": (
                round(safe("ebitda") / safe("totalRevenue") * 100, 1)
                if safe("ebitda") and safe("totalRevenue")
                else None
            ),
            # Quarterly trends
            "quarterly_revenue": quarterly_revenue,
            "quarterly_revenue_dates": quarterly_revenue_dates,
            "quarterly_gross_margin": quarterly_gross_margin,
            "quarterly_operating_margin": quarterly_operating_margin,
            # P&L
            "ebitda": safe("ebitda"),
            "net_income": safe("netIncomeToCommon"),
            "free_cash_flow": free_cash_flow,
            # Capital structure
            "total_debt": total_debt,
            "total_cash": total_cash,
            "net_cash": net_cash,
            "debt_to_equity": safe("debtToEquity"),
            # Shareholder returns
            "dividend_yield": safe("dividendYield"),
            "dividend_rate": safe("dividendRate"),
            "payout_ratio": safe("payoutRatio"),
            "shares_outstanding": safe("sharesOutstanding"),
            "shares_history": shares_history,
            "buyback_yield": safe("buybackYield"),
            # Price
            "52wk_low": safe("fiftyTwoWeekLow"),
            "52wk_high": safe("fiftyTwoWeekHigh"),
            # Analyst consensus
            "analyst_target_price": safe("targetMeanPrice"),
            "analyst_target_high": safe("targetHighPrice"),
            "analyst_target_low": safe("targetLowPrice"),
            "analyst_target_median": safe("targetMedianPrice"),
            "num_analyst_opinions": info.get("numberOfAnalystOpinions"),
            "recommendation_key": info.get("recommendationKey"),
            "as_of": date.today().isoformat(),
        }

        # Recent recommendations history (last 8)
        try:
            recs = stock.recommendations
            if recs is not None and not recs.empty:
                recent = recs.tail(8).reset_index()
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
