import json
from datetime import date
from agents import function_tool


@function_tool
def get_10k_risk_factors(ticker: str) -> str:
    """Fetch risk factors from the most recent 10-K or 20-F filing via EDGAR."""
    try:
        from edgar import Company, set_identity

        set_identity("Stock Research Agent research@example.com")
        company = Company(ticker)

        filing = None
        form_type = None
        for form in ("10-K", "20-F"):
            try:
                filings = company.get_filings(form=form)
                if filings and len(filings) > 0:
                    filing = filings.latest()
                    form_type = form
                    break
            except Exception:
                continue

        if filing is None:
            return json.dumps({
                "status": "not_available",
                "reason": "No 10-K or 20-F filing found (may be ETF, SPAC, ADR, or recent IPO)",
                "risks": [],
            })

        filing_date = (
            str(filing.filing_date)
            if hasattr(filing, "filing_date")
            else date.today().isoformat()
        )

        # Extract Item 1A from the document
        doc = filing.obj()
        risk_text = None

        if doc is not None:
            for approach in (
                lambda d: str(d["Item 1A"]),
                lambda d: str(d.risk_factors),
                lambda d: str(getattr(d, "items", {}).get("Item 1A", "")),
                lambda d: str(d.get("Item 1A", "")) if hasattr(d, "get") else None,
            ):
                try:
                    text = approach(doc)
                    if text and len(text.strip()) > 200:
                        risk_text = text
                        break
                except Exception:
                    continue

        if not risk_text or len(risk_text.strip()) < 100:
            return json.dumps({
                "status": "not_available",
                "reason": "Could not extract Item 1A Risk Factors from the filing",
                "filing_type": form_type,
                "filing_date": filing_date,
                "risks": [],
            })

        # Truncate — first 8 000 chars covers the material risks
        risk_text = risk_text[:8000]

        return json.dumps({
            "status": "ok",
            "filing_type": form_type,
            "filing_date": filing_date,
            "raw_risk_text": risk_text,
            "instruction": (
                "Summarize the 5-7 most material risks from raw_risk_text. "
                "For each: short title, 1-2 sentence plain-English summary (no boilerplate), "
                "and severity tag (High/Medium/Low)."
            ),
        })

    except Exception as e:
        return json.dumps({
            "status": "not_available",
            "reason": f"EDGAR lookup failed: {str(e)}",
            "risks": [],
        })
