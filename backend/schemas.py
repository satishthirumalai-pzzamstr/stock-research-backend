from typing import Optional
from pydantic import BaseModel


class FinancialSnapshot(BaseModel):
    ticker: str
    company_name: str
    sector: str
    industry: str
    price: Optional[float] = None
    market_cap: Optional[float] = None
    pe_trailing: Optional[float] = None
    pe_forward: Optional[float] = None
    ev_ebitda: Optional[float] = None
    revenue_ttm: Optional[float] = None
    revenue_history: list[Optional[float]] = []
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    ebitda: Optional[float] = None
    net_income: Optional[float] = None
    free_cash_flow: Optional[float] = None
    week_52_low: Optional[float] = None
    week_52_high: Optional[float] = None
    analyst_target_price: Optional[float] = None
    as_of: str


class ComparableCompany(BaseModel):
    ticker: str
    company_name: str
    pe_trailing: Optional[float] = None
    pe_forward: Optional[float] = None
    ev_ebitda: Optional[float] = None
    revenue_ttm: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    justification: str


class RiskFactor(BaseModel):
    title: str
    summary: str
    severity: str  # High / Medium / Low


class RiskSummary(BaseModel):
    status: str  # "ok" | "not_available"
    filing_type: Optional[str] = None
    filing_date: Optional[str] = None
    risks: list[RiskFactor] = []
    reason: Optional[str] = None


class AnalystVerdict(BaseModel):
    signal: str  # BUY / HOLD / SELL
    confidence: str  # High / Medium / Low
    rationale: str
    comps_analysis: dict
    risk_summary: str
