# AGENTS.md — DriveIQ AI Agent System

> This file documents how I design, prompt, and deploy AI agents in DriveIQ.
> It reflects my actual engineering philosophy: **architect first, prompt second.**

---

## My AI Engineering Philosophy

I treat AI agents like distributed microservices — each one has a **single responsibility**,
a **typed input/output contract**, **failure handling**, and **observable metrics**.

I don't prompt my way to a solution. I design the system, identify where human judgment
is irreplaceable, and use LLMs precisely where they add leverage.

**Where AI wins:**
- Synthesizing unstructured data at scale (car descriptions, inspection reports)
- Generating structured analysis from multi-source context
- Evaluating output quality without human review on every item

**Where I keep humans in the loop:**
- Final pricing decisions above ₹10L
- Fraud flags before blocking a seller account
- Any output that affects financial transactions

---

## Agent Registry

### 1. `ValuationAgent`

**Purpose:** Estimate fair market value for a used car listing.

**Why an agent (not a rule-based model)?**
Car valuation has 40+ interacting signals — mileage, city, service history, accident records,
paint condition, market demand for that variant. Rule-based systems fail at edge cases.
An LLM with structured tool calls handles rare combinations gracefully.

**Input contract:**
```json
{
  "make": "Maruti",
  "model": "Swift VXI",
  "year": 2019,
  "mileage_km": 42000,
  "city": "Bengaluru",
  "fuel_type": "Petrol",
  "transmission": "Manual",
  "condition_report": "Minor scratch on rear bumper. AC works. Original tyres.",
  "registration_state": "KA"
}
```

**Output contract:**
```json
{
  "fair_value_inr": 620000,
  "range_low": 590000,
  "range_high": 650000,
  "confidence": 0.87,
  "key_factors": ["High demand variant", "Low mileage for age", "Bengaluru premium"],
  "depreciation_flags": ["Original tyres near replacement"],
  "comparable_listings": 14
}
```

**Tools used:**
- `market_search_tool` — fetches real-time comparable listings from Cars24/CarDekho APIs
- `depreciation_table_tool` — structured lookup for model-specific depreciation curves
- `city_demand_tool` — demand index per make/model/city from internal analytics

**Prompt strategy:**
I use a two-step chain, not a single monolithic prompt:
1. **Step 1 (Extraction):** Extract structured signals from free-text condition report → JSON
2. **Step 2 (Valuation):** Feed structured signals + tool results → valuation with reasoning

Why two steps? Step 1 is cheap (gpt-4o-mini). Step 2 uses the full context and needs
richer reasoning (gpt-4o). Splitting cuts token cost by ~40% with no quality loss.

**Failure handling:**
- If `market_search_tool` returns < 3 comparables → widen search radius, lower confidence score
- If LLM output fails JSON schema validation → retry once with stricter prompt, then fallback to rule-based estimate
- Confidence < 0.6 → flag for human review queue, never return to user directly

---

### 2. `FraudDetectionAgent`

**Purpose:** Flag suspicious listings before they go live.

**Design decision — why LLM over pure ML classifier?**
Fraud patterns evolve weekly. A fine-tuned classifier needs retraining when patterns shift.
An LLM with a well-designed prompt adapts to novel patterns immediately.
I use the LLM for pattern reasoning, not as a black box — every flag has an explanation.

**Signals evaluated:**
- Price vs. fair value gap (> 25% below market = suspicious)
- Image analysis: VIN in images matches listing VIN?
- Seller history: new account + high-value listing = elevated risk
- Description anomalies: copy-pasted text, mismatched year/model mentions
- Contact info patterns: disposable phone numbers, VoIP prefixes

**Output:**
```json
{
  "risk_score": 0.82,
  "risk_level": "HIGH",
  "flags": [
    { "type": "PRICE_ANOMALY", "detail": "Listed 31% below 14 comparable listings" },
    { "type": "NEW_SELLER", "detail": "Account created 2 days ago, this is first listing" }
  ],
  "recommended_action": "HOLD_FOR_REVIEW",
  "human_review_required": true
}
```

**Hard rule:** `risk_score > 0.75` → listing held, never auto-published. Human reviews within 2 hours.

---

### 3. `NegotiationCoachAgent`

**Purpose:** Help buyers understand how much negotiation room exists and what arguments to use.

**What makes this interesting:**
The agent has access to: listing price, fair value estimate, time-on-market, seller response rate,
and city-level demand data. It synthesizes these into actionable negotiation advice.

**Prompt design principle — I use chain-of-thought explicitly:**
```
You are an expert used car negotiation advisor in India.

Think step by step:
1. Is the listed price above or below fair market value?
2. How long has this listing been active? (longer = more motivated seller)
3. What defects from the inspection report justify price reduction?
4. What is the realistic minimum the seller would accept?

Then provide: target offer price, opening offer, negotiation script, walk-away price.
```

I force the CoT because without it the model jumps to a number without reasoning,
and the reasoning IS the value — it's what builds user trust in the recommendation.

---

### 4. `MarketIntelAgent`

**Purpose:** Daily market analysis reports — which models are appreciating, which are flooding the market, demand by city.

**Architecture choice — scheduled, not real-time:**
This agent runs at 2 AM daily via a Kubernetes CronJob. Output cached in Redis for 24h.
Real-time market analysis is expensive and unnecessary — car market doesn't change hour to hour.

**Output:** Structured report pushed to internal dashboard + email digest to ops team.

---

## Prompt Engineering Principles I Follow

### 1. Schema-first prompting
Every agent that outputs structured data gets a JSON schema in the system prompt.
I never say "return JSON" — I say "return JSON that validates against this schema: {schema}".
This cuts hallucinated field names by ~90%.

### 2. Confidence calibration
Every agent output includes a `confidence` score. I prompt for it explicitly:
```
Rate your confidence in this valuation from 0.0 to 1.0.
0.0 = you have almost no comparable data.
1.0 = you have 10+ identical listings in the same city within 30 days.
Be conservative. I would rather have a low-confidence flag than a confidently wrong answer.
```

### 3. I test prompts like I test code
Every prompt change goes through an eval suite of 50 golden examples before deploying.
A prompt that improves average output by 5% but regresses 3 edge cases doesn't ship.

### 4. Model selection per task
| Task | Model | Why |
|---|---|---|
| Structured extraction | gpt-4o-mini | Fast, cheap, reliable at JSON |
| Complex reasoning | gpt-4o | Quality matters more than cost |
| Embeddings | text-embedding-3-small | Good quality, 5× cheaper than large |
| Classification | Fine-tuned gpt-4o-mini | Domain-specific, 80% cost reduction |

---

## Agent Observability

Every agent call logs:
```json
{
  "agent": "ValuationAgent",
  "run_id": "uuid",
  "model": "gpt-4o-mini",
  "prompt_tokens": 892,
  "completion_tokens": 340,
  "latency_ms": 1240,
  "confidence": 0.87,
  "tools_called": ["market_search_tool", "city_demand_tool"],
  "output_valid": true,
  "human_review_flagged": false
}
```

This powers a Grafana dashboard showing: cost per valuation, accuracy vs. human appraiser,
flag rate, and average confidence by car segment.

---

## What I Would Do Differently at Scale

- **Fine-tune ValuationAgent** on Cars24's historical sold prices — far better than prompting a general model
- **Structured outputs API** (OpenAI) instead of JSON-in-prompt — eliminates schema drift entirely
- **Agent evals as CI gate** — no prompt ships without eval suite passing (>90% on golden set)
- **Shadow mode for FraudAgent** — run new model in parallel with prod for 2 weeks before cutting over
