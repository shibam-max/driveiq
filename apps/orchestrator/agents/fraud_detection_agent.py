"""
FraudDetectionAgent — Rule-based pre-checks first, LLM for pattern analysis.

Design rationale: Obvious fraud (listed 30%+ below market, brand-new account
with high-value listing) doesn't need an LLM. Pre-checks eliminate ~40% of
flagging work cheaply and deterministically. LLM handles the nuanced patterns.

INVARIANT: risk_score > 0.75 NEVER auto-publishes. This is enforced here AND
in the listing service. Defense in depth.
"""
import time
import json
import structlog
from pydantic import BaseModel, Field
from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from prompts.fraud import FRAUD_ANALYSIS_PROMPT

log = structlog.get_logger()

llm = ChatOpenAI(model="gpt-4o", temperature=0)


class FraudFlag(BaseModel):
    type: str
    detail: str
    severity: str = Field(pattern="^(low|medium|high)$")


class FraudResult(BaseModel):
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: str = Field(pattern="^(LOW|MEDIUM|HIGH)$")
    flags: list[FraudFlag]
    recommended_action: str
    human_review_required: bool
    rule_triggered: bool = False   # True if caught by pre-checks, no LLM needed


PRICE_GAP_AUTO_HOLD = 0.30       # 30% below market → auto-hold, no LLM
PRICE_GAP_ELEVATED  = 0.15       # 15% below → elevated risk
NEW_SELLER_AGE_DAYS = 7
NEW_SELLER_HIGH_VALUE_THRESHOLD = 500_000  # ₹5L


async def check_fraud(
    listing_id: str,
    listed_price_inr: int,
    fair_value_inr: int,
    seller_account_age_days: int,
    seller_listing_count: int,
    description: str,
    contact_info: dict,
    run_id: str,
) -> FraudResult:
    """
    Two-stage fraud detection:
    Stage 1: Deterministic rule-based checks (fast, free, auditable)
    Stage 2: LLM pattern analysis (nuanced, handles novel fraud patterns)
    """
    start = time.monotonic()
    flags: list[FraudFlag] = []
    base_risk = 0.0

    # ── Stage 1: Rule-based pre-checks ──────────────────────────────────
    price_gap = (fair_value_inr - listed_price_inr) / fair_value_inr if fair_value_inr > 0 else 0

    # Rule 1: Price massively below market → auto-hold immediately
    if price_gap > PRICE_GAP_AUTO_HOLD:
        log.warning("fraud.rule.price_anomaly_critical",
                    run_id=run_id,
                    price_gap_pct=round(price_gap * 100, 1))
        return FraudResult(
            risk_score=0.95,
            risk_level="HIGH",
            flags=[FraudFlag(
                type="PRICE_ANOMALY_CRITICAL",
                detail=f"Listed {round(price_gap*100)}% below fair market value of ₹{fair_value_inr:,}",
                severity="high"
            )],
            recommended_action="HOLD_FOR_REVIEW",
            human_review_required=True,
            rule_triggered=True,
        )

    # Rule 2: Moderate price gap → add risk
    if price_gap > PRICE_GAP_ELEVATED:
        flags.append(FraudFlag(
            type="PRICE_ANOMALY",
            detail=f"Listed {round(price_gap*100)}% below {len([]):0} comparable listings",
            severity="medium"
        ))
        base_risk += 0.25

    # Rule 3: New seller + high-value listing
    if seller_account_age_days < NEW_SELLER_AGE_DAYS and listed_price_inr > NEW_SELLER_HIGH_VALUE_THRESHOLD:
        flags.append(FraudFlag(
            type="NEW_SELLER_HIGH_VALUE",
            detail=f"Account {seller_account_age_days} days old, listing value ₹{listed_price_inr:,}",
            severity="high"
        ))
        base_risk += 0.35

    # Rule 4: First-time seller with very high value
    if seller_listing_count == 0 and listed_price_inr > 1_000_000:  # ₹10L
        flags.append(FraudFlag(
            type="FIRST_LISTING_HIGH_VALUE",
            detail=f"No prior listings. Listing value ₹{listed_price_inr:,}",
            severity="medium"
        ))
        base_risk += 0.20

    log.info("fraud.rules.done",
             run_id=run_id,
             rule_flags=len(flags),
             base_risk=round(base_risk, 2))

    # ── Stage 2: LLM pattern analysis ───────────────────────────────────
    log.info("fraud.llm.start", run_id=run_id, model="gpt-4o")

    analysis_chain = ChatPromptTemplate.from_messages([
        ("system", FRAUD_ANALYSIS_PROMPT),
        ("human", """
Listing ID: {listing_id}
Listed price: ₹{listed_price:,}
Fair value:   ₹{fair_value:,}
Price gap:    {price_gap_pct}% below market

Description:
{description}

Contact info:
{contact_json}

Seller: {account_age} days old account, {listing_count} prior listings

Pre-check flags already raised: {existing_flags}

Analyze this listing for fraud patterns not caught by rules.
Focus on: description anomalies, contact info patterns, mismatch between car details.

Return JSON:
{{
  "additional_risk_score": <float 0.0-0.5, only what you add beyond the pre-check base>,
  "additional_flags": [
    {{"type": "<string>", "detail": "<string>", "severity": "low|medium|high"}}
  ],
  "reasoning": "<one paragraph>"
}}
""")
    ]) | llm

    llm_response = await analysis_chain.ainvoke({
        "listing_id": listing_id,
        "listed_price": listed_price_inr,
        "fair_value": fair_value_inr,
        "price_gap_pct": round(price_gap * 100, 1),
        "description": description[:1000],
        "contact_json": json.dumps(contact_info),
        "account_age": seller_account_age_days,
        "listing_count": seller_listing_count,
        "existing_flags": [f.type for f in flags],
    })

    try:
        llm_data = json.loads(llm_response.content)
        additional_risk = float(llm_data.get("additional_risk_score", 0.0))
        for flag_data in llm_data.get("additional_flags", []):
            flags.append(FraudFlag(**flag_data))
    except Exception as e:
        log.warning("fraud.llm.parse_failed", run_id=run_id, error=str(e))
        additional_risk = 0.0

    final_score = min(1.0, base_risk + additional_risk)
    risk_level = "HIGH" if final_score > 0.75 else "MEDIUM" if final_score > 0.40 else "LOW"

    # INVARIANT: enforce hard threshold — never allow HIGH risk to auto-publish
    human_required = final_score > 0.75

    duration_ms = int((time.monotonic() - start) * 1000)
    log.info("fraud.done",
             run_id=run_id,
             risk_score=round(final_score, 2),
             risk_level=risk_level,
             flags=len(flags),
             human_required=human_required,
             duration_ms=duration_ms)

    return FraudResult(
        risk_score=round(final_score, 2),
        risk_level=risk_level,
        flags=flags,
        recommended_action="HOLD_FOR_REVIEW" if human_required else "PUBLISH",
        human_review_required=human_required,
    )
