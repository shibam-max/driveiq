# CLAUDE.md — How I Work With Claude on DriveIQ

> This file configures Claude's behavior for this codebase and documents
> my personal workflow for using AI in engineering. It's submitted as part
> of my application because it reflects how I actually think.

---

## Project Context for Claude

DriveIQ is a used car intelligence platform built on:
- **Backend:** Spring Boot 3.2 (Java 17) — API gateway, auth, business logic
- **Orchestrator:** FastAPI + LangGraph (Python 3.11) — AI agent workflows
- **Frontend:** Next.js 14 (TypeScript) — real-time streaming UI
- **Data:** PostgreSQL 16 + pgvector, Redis, S3
- **Infra:** AWS EKS via Terraform, GitHub Actions CI/CD

**Domain:** Indian used car market. Prices in INR. Cities: Bengaluru, Mumbai, Delhi, Chennai, Hyderabad, Pune.

---

## Instructions for Claude in This Repo

### Code style

**Java (Spring Boot):**
- Use constructor injection, never `@Autowired` on fields
- `@Slf4j` for logging, structured JSON log format
- All controller methods return `ResponseEntity<T>` with explicit status codes
- `Optional<T>` for nullable returns — never return `null`
- Service layer methods never throw unchecked exceptions — use custom `DriveIQException`

**Python (FastAPI / LangGraph):**
- All async — `async def` everywhere, `await` on all I/O
- Pydantic v2 models for all request/response shapes
- Type hints on every function signature, no `Any` unless unavoidable
- `structlog` for logging, always include `run_id` in every log call
- Agent nodes must be pure functions of state — no side effects except publishing events

**TypeScript (Next.js):**
- `'use client'` only on components that need it — default to server components
- `zod` for runtime validation of API responses
- No `any` types — use `unknown` and narrow
- CSS variables for theming, no hardcoded colors

### What to always include in generated code
- Error handling — never a bare `try/catch` with no action
- Logging at appropriate levels (DEBUG for internals, INFO for business events, ERROR for failures)
- Unit tests for any non-trivial logic
- JSDoc / docstring for public methods

### What to never do
- Never generate secrets, API keys, or passwords — use placeholder like `${SECRET_NAME}`
- Never use `System.out.println` — always use the logger
- Never commit without checking for TODO/FIXME I might have missed
- Never skip input validation on controller endpoints

---

## My AI Workflow (how I actually use Claude day-to-day)

### For system design
I describe the problem in plain English first. Then I ask Claude to:
1. Identify the core trade-offs (not a solution yet)
2. List 2–3 approaches with pros/cons
3. Ask me clarifying questions before recommending

I don't ask Claude to "design the system" — I ask it to **help me think**.
The design is mine. Claude is a thinking partner, not a decision maker.

### For writing code
I always provide:
- The interface/contract first (what goes in, what comes out)
- The context (what service calls this, what does it call)
- The constraints (latency budget, error handling expectations)

Then I review every line. I challenge anything that looks like a shortcut.
A clean interface with a naive implementation is better than a clever implementation
of a poorly designed interface.

### For debugging
I paste the error, the stack trace, AND my hypothesis. If I have no hypothesis,
I'm not ready to ask Claude — I debug first, then ask for a second opinion.

### For code review
I use Claude to review my own PRs before pushing. Specifically:
- "What edge cases am I missing?"
- "What would fail under load?"
- "Is there a simpler way to express this?"

I don't ask "is this good?" — that's too vague. I ask specific questions.

---

## Prompt Templates I Use in This Project

### Valuation prompt (chain step 1 — extraction)
```
You are extracting structured signals from a used car condition report.

Input: Free-text condition report from a seller or inspector.
Output: JSON matching this schema exactly — no extra fields, no missing fields.

Schema:
{
  "exterior_condition": "excellent|good|fair|poor",
  "interior_condition": "excellent|good|fair|poor",
  "mechanical_issues": ["string"],
  "cosmetic_issues": ["string"],
  "tyres_condition": "new|good|worn|needs_replacement",
  "ac_working": true|false,
  "service_history_available": true|false,
  "accident_history": true|false|"unknown"
}

If a field cannot be determined from the report, use null.
Do not infer. Do not guess. Only extract what is explicitly stated or clearly implied.

Condition report:
{condition_report}
```

### Code review prompt
```
Review this {language} code for:
1. Correctness — will it do what the docstring/comments say?
2. Edge cases — what inputs would cause unexpected behavior?
3. Performance — any obvious O(n²) where O(n) would work?
4. Readability — what would confuse a new team member?

Be specific. For each issue, quote the line and explain the problem.
Don't comment on style unless it causes a real problem.

Code:
{code}
```

---

## Red Lines — Where I Don't Use AI

- **Architecture decisions** that affect the team for months — those are mine
- **Security-sensitive code** (auth filters, secrets handling) — I write and review these myself
- **Database migrations** — I write these by hand, too risky to get wrong
- **Anything I can't fully explain** — if I can't review it line by line, it doesn't ship

I use Claude as a force multiplier for the parts of software engineering that are
well-defined and repeatable. I keep human judgment — mine — on the parts that require
context, taste, and accountability.

The code in this repo reflects that. I designed the system. I made the trade-off decisions.
I wrote the tests. Claude helped me move faster on the parts that didn't need my full attention.

That's the job.
