"""
Agent eval suite — runs as a CI gate before every deploy.
A prompt change that regresses accuracy doesn't ship, even if unit tests pass.

Usage:
    python -m evals.run_evals
    python -m evals.run_evals --agent valuation
    python -m evals.run_evals --agent fraud

Exit code 0 = pass, 1 = fail (blocks CI deploy).
"""
import asyncio
import json
import sys
import argparse
from pathlib import Path
from dataclasses import dataclass

VALUATION_ACCURACY_THRESHOLD = 0.90   # 90% of examples must be within ±15%
FRAUD_PRECISION_THRESHOLD = 0.90      # 90% correct risk level


@dataclass
class EvalResult:
    agent: str
    total: int
    passed: int
    failed_cases: list[dict]

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0

    @property
    def ok(self) -> bool:
        thresholds = {
            "valuation": VALUATION_ACCURACY_THRESHOLD,
            "fraud": FRAUD_PRECISION_THRESHOLD,
        }
        return self.accuracy >= thresholds.get(self.agent, 0.90)


async def run_valuation_evals() -> EvalResult:
    from agents.valuation_agent import run_valuation

    golden_path = Path(__file__).parent / "valuation_golden_set.json"
    golden = json.loads(golden_path.read_text())

    passed = 0
    failed = []

    for example in golden:
        result = await run_valuation(
            run_id=f"eval-{example['id']}",
            **example["input"]
        )

        expected = example["expected_fair_value_inr"]
        actual = result.fair_value_inr
        error_pct = abs(actual - expected) / expected

        if error_pct <= 0.15:  # within ±15%
            passed += 1
        else:
            failed.append({
                "id": example["id"],
                "expected": expected,
                "actual": actual,
                "error_pct": round(error_pct * 100, 1),
                "car": f"{example['input']['year']} {example['input']['make']} {example['input']['model']}",
            })

    return EvalResult(agent="valuation", total=len(golden), passed=passed, failed_cases=failed)


async def run_fraud_evals() -> EvalResult:
    from agents.fraud_detection_agent import check_fraud

    golden_path = Path(__file__).parent / "fraud_golden_set.json"
    golden = json.loads(golden_path.read_text())

    passed = 0
    failed = []

    for example in golden:
        result = await check_fraud(
            run_id=f"eval-{example['id']}",
            **example["input"]
        )

        expected_level = example["expected_risk_level"]
        if result.risk_level == expected_level:
            passed += 1
        else:
            failed.append({
                "id": example["id"],
                "expected": expected_level,
                "actual": result.risk_level,
                "risk_score": result.risk_score,
            })

    return EvalResult(agent="fraud", total=len(golden), passed=passed, failed_cases=failed)


def print_result(result: EvalResult):
    status = "✓ PASS" if result.ok else "✗ FAIL"
    print(f"\n{result.agent.upper()} EVALS  {status}")
    print(f"  {result.passed}/{result.total} passed  ({result.accuracy*100:.1f}%)")

    if result.failed_cases:
        print(f"  Failed cases:")
        for case in result.failed_cases[:5]:  # show max 5
            print(f"    {case}")
        if len(result.failed_cases) > 5:
            print(f"    ... and {len(result.failed_cases) - 5} more")


async def main(agents: list[str]) -> int:
    results = []

    if "valuation" in agents:
        print("Running ValuationAgent evals...")
        results.append(await run_valuation_evals())

    if "fraud" in agents:
        print("Running FraudDetectionAgent evals...")
        results.append(await run_fraud_evals())

    all_passed = True
    for result in results:
        print_result(result)
        if not result.ok:
            all_passed = False

    if all_passed:
        print("\n✓ All evals passed. Deploy gate: OPEN\n")
        return 0
    else:
        print("\n✗ Evals FAILED. Deploy gate: BLOCKED\n")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=["valuation", "fraud", "all"], default="all")
    args = parser.parse_args()

    agents = ["valuation", "fraud"] if args.agent == "all" else [args.agent]
    exit_code = asyncio.run(main(agents))
    sys.exit(exit_code)
