import json
from datetime import date
from agents import function_tool


def get_earnings_data_raw(ticker: str) -> dict:
    """Fetch earnings history, forward estimates, EPS revisions, and next earnings date."""
    import yfinance as yf

    try:
        stock = yf.Ticker(ticker)
        result: dict = {"ticker": ticker.upper(), "as_of": date.today().isoformat()}

        # Historical quarterly earnings (EPS actual vs estimate)
        quarterly_eps = []
        try:
            qe = stock.quarterly_earnings
            if qe is not None and not qe.empty:
                df = qe.reset_index()
                for _, row in df.head(8).iterrows():
                    actual = row.get("Earnings", row.get("actual", None))
                    estimate = row.get("Revenue", None)  # fallback
                    # Try better column names
                    for col in df.columns:
                        cl = col.lower()
                        if "actual" in cl or "earnings" in cl:
                            actual = row[col]
                        if "estimate" in cl:
                            estimate = row[col]
                    quarter = str(row.get("Quarter", row.get("index", row.get("Date", ""))))
                    actual_f = float(actual) if actual is not None and str(actual) != "nan" else None
                    est_f = float(estimate) if estimate is not None and str(estimate) != "nan" else None
                    surprise_pct = None
                    if actual_f is not None and est_f is not None and est_f != 0:
                        surprise_pct = round((actual_f - est_f) / abs(est_f) * 100, 1)
                    quarterly_eps.append({
                        "quarter": quarter,
                        "eps_estimate": est_f,
                        "eps_actual": actual_f,
                        "surprise_pct": surprise_pct,
                        "beat": (actual_f > est_f) if (actual_f is not None and est_f is not None) else None,
                    })
        except Exception:
            pass
        result["quarterly_eps_history"] = quarterly_eps

        # Earnings dates (upcoming + recent)
        earnings_dates = []
        next_earnings_date = None
        try:
            ed = stock.earnings_dates
            if ed is not None and not ed.empty:
                df = ed.reset_index()
                today_str = date.today().isoformat()
                for _, row in df.head(6).iterrows():
                    dt = str(row.get("Earnings Date", row.iloc[0] if len(row) > 0 else ""))[:10]
                    eps_est = None
                    eps_act = None
                    for col in df.columns:
                        cl = col.lower()
                        if "estimate" in cl:
                            v = row[col]
                            eps_est = float(v) if v is not None and str(v) != "nan" else None
                        if "reported" in cl or "actual" in cl:
                            v = row[col]
                            eps_act = float(v) if v is not None and str(v) != "nan" else None
                    earnings_dates.append({"date": dt, "eps_estimate": eps_est, "eps_actual": eps_act})
                    if dt >= today_str and next_earnings_date is None:
                        next_earnings_date = dt
        except Exception:
            pass
        result["earnings_dates"] = earnings_dates
        result["next_earnings_date"] = next_earnings_date

        # Forward EPS estimates (next 2 quarters + 2 annual)
        eps_forward = []
        try:
            ef = stock.earnings_forecast
            if ef is not None and not ef.empty:
                df = ef.reset_index()
                for _, row in df.head(6).iterrows():
                    period = str(row.get("Period", row.iloc[0] if len(row) > 0 else ""))
                    avg = row.get("Avg", None)
                    low = row.get("Low", None)
                    high = row.get("High", None)
                    num = row.get("No. of Analysts", row.get("NumberOfAnalysts", None))
                    eps_forward.append({
                        "period": period,
                        "eps_avg": float(avg) if avg is not None and str(avg) != "nan" else None,
                        "eps_low": float(low) if low is not None and str(low) != "nan" else None,
                        "eps_high": float(high) if high is not None and str(high) != "nan" else None,
                        "num_analysts": int(num) if num is not None and str(num) != "nan" else None,
                    })
        except Exception:
            pass
        result["eps_forward_estimates"] = eps_forward

        # Revenue estimates
        revenue_estimates = []
        try:
            re = stock.revenue_estimate
            if re is not None and not re.empty:
                df = re.reset_index()
                for _, row in df.head(4).iterrows():
                    period = str(row.get("Period", row.iloc[0] if len(row) > 0 else ""))
                    avg = row.get("Avg", None)
                    low = row.get("Low", None)
                    high = row.get("High", None)
                    growth = row.get("Growth", None)
                    revenue_estimates.append({
                        "period": period,
                        "revenue_avg": float(avg) if avg is not None and str(avg) != "nan" else None,
                        "revenue_low": float(low) if low is not None and str(low) != "nan" else None,
                        "revenue_high": float(high) if high is not None and str(high) != "nan" else None,
                        "yoy_growth_est": float(growth) if growth is not None and str(growth) != "nan" else None,
                    })
        except Exception:
            pass
        result["revenue_estimates"] = revenue_estimates

        # EPS revisions (analysts raising vs lowering)
        eps_revisions = {}
        try:
            er = stock.eps_revisions
            if er is not None and not er.empty:
                df = er.reset_index()
                for _, row in df.iterrows():
                    period = str(row.get("Period", row.iloc[0] if len(row) > 0 else ""))
                    up = row.get("Up Last 7 Days", row.get("upLast7days", None))
                    down = row.get("Down Last 7 Days", row.get("downLast7days", None))
                    up30 = row.get("Up Last 30 Days", row.get("upLast30days", None))
                    down30 = row.get("Down Last 30 Days", row.get("downLast30days", None))
                    eps_revisions[period] = {
                        "up_7d": int(up) if up is not None and str(up) != "nan" else None,
                        "down_7d": int(down) if down is not None and str(down) != "nan" else None,
                        "up_30d": int(up30) if up30 is not None and str(up30) != "nan" else None,
                        "down_30d": int(down30) if down30 is not None and str(down30) != "nan" else None,
                    }
        except Exception:
            pass
        result["eps_revisions"] = eps_revisions

        # Long-term growth estimates
        growth_estimates = {}
        try:
            ge = stock.growth_estimates
            if ge is not None and not ge.empty:
                df = ge.reset_index()
                for _, row in df.iterrows():
                    period = str(row.get("Period", row.iloc[0] if len(row) > 0 else ""))
                    val = row.get(ticker.upper(), row.get("Value", None))
                    if val is None:
                        for col in df.columns:
                            if col not in ("Period", "index"):
                                val = row[col]
                                break
                    growth_estimates[period] = float(val) if val is not None and str(val) != "nan" else None
        except Exception:
            pass
        result["growth_estimates"] = growth_estimates

        return result
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_insider_trades_raw(ticker: str) -> dict:
    """Fetch recent insider transactions from SEC Form 4 filings via yfinance."""
    import yfinance as yf
    try:
        stock = yf.Ticker(ticker)
        transactions = stock.insider_transactions
        purchases = stock.insider_purchases

        trades = []
        if transactions is not None and not transactions.empty:
            df = transactions.reset_index()
            for _, row in df.head(20).iterrows():
                shares = row.get("Shares", row.get("shares", None))
                value = row.get("Value", row.get("value", None))
                trade = {
                    "date": str(row.get("Start Date", row.get("startDate", row.get("Date", "")))),
                    "insider": str(row.get("Insider", row.get("insider", ""))),
                    "title": str(row.get("Insider Title", row.get("insiderTitle", row.get("title", "")))),
                    "transaction": str(row.get("Transaction", row.get("transaction", ""))),
                    "shares": int(shares) if shares is not None and str(shares) != "nan" else None,
                    "value": float(value) if value is not None and str(value) != "nan" else None,
                    "shares_total": None,
                }
                trades.append(trade)

        # Net summary from insider_purchases
        summary = {}
        if purchases is not None and not purchases.empty:
            df2 = purchases.reset_index()
            for _, row in df2.iterrows():
                label = str(row.get("Insider Purchases Last 6m", row.get("", ""))).strip()
                purchases_val = row.get("Purchases", None)
                sales_val = row.get("Sales", None)
                if purchases_val is not None or sales_val is not None:
                    summary = {
                        "purchases_6m": int(purchases_val) if purchases_val is not None and str(purchases_val) != "nan" else None,
                        "sales_6m": int(sales_val) if sales_val is not None and str(sales_val) != "nan" else None,
                    }
                    break

        # Compute net signal
        buys = sum(1 for t in trades if "buy" in t["transaction"].lower() or "purchase" in t["transaction"].lower())
        sells = sum(1 for t in trades if "sell" in t["transaction"].lower() or "sale" in t["transaction"].lower())
        net_signal = "Bullish" if buys > sells * 1.5 else ("Bearish" if sells > buys * 1.5 else "Neutral")

        return {
            "ticker": ticker.upper(),
            "trades": trades,
            "summary_6m": summary,
            "buys_count": buys,
            "sells_count": sells,
            "net_signal": net_signal,
            "as_of": date.today().isoformat(),
        }
    except Exception as e:
        return {"ticker": ticker, "trades": [], "error": str(e), "net_signal": "Unknown"}


def get_price_history_raw(ticker: str) -> dict:
    """Fetch 1Y of daily price history for a ticker. Returns dict with prices list."""
    import yfinance as yf
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="max")
        if hist is None or hist.empty:
            return {"ticker": ticker, "prices": [], "error": "No price history available"}
        prices = [
            {
                "date": str(idx.date()),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]) if row["Volume"] else 0,
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
            }
            for idx, row in hist.iterrows()
        ]
        closes = [p["close"] for p in prices if p["close"]]
        return {
            "ticker": ticker.upper(),
            "prices": prices,
            "as_of": date.today().isoformat(),
            "52wk_high": max(closes) if closes else None,
            "52wk_low": min(closes) if closes else None,
        }
    except Exception as e:
        return {"ticker": ticker, "prices": [], "error": str(e)}


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
