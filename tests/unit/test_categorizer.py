"""Unit Tests and Accuracy Benchmark for Transaction Categorizer."""

import pytest

from app.services.categorizer import (
    FakeCategorizer,
    RuleBasedCategorizer,
)


@pytest.mark.asyncio
async def test_categorizer_basic_categories() -> None:
    """Verify rule-based categorizer correctly classifies canonical categories."""
    categorizer = RuleBasedCategorizer()

    assert await categorizer.categorize("Starbucks Coffee Seattle") == "Food & Dining"
    assert await categorizer.categorize("Uber trip to airport") == "Transportation"
    assert await categorizer.categorize("City water and power utility bill") == "Utilities"
    assert await categorizer.categorize("Netflix monthly subscription") == "Entertainment"
    assert await categorizer.categorize("Bi-weekly payroll direct deposit") == "Payroll"
    assert await categorizer.categorize("Amazon online store purchase") == "Shopping"
    assert await categorizer.categorize("Walgreens pharmacy prescription") == "Health & Medical"
    assert await categorizer.categorize("Venmo split with friend") == "Transfer"
    assert await categorizer.categorize("") == "Uncategorized"
    assert await categorizer.categorize("   ") == "Uncategorized"
    assert await categorizer.categorize(None) == "Uncategorized"
    assert await categorizer.categorize("XKJQ12837ZZQ") == "Uncategorized"


@pytest.mark.asyncio
async def test_fake_categorizer_behavior() -> None:
    """Verify fake categorizer canned output and failure simulation."""
    fake = FakeCategorizer(canned_category="Entertainment")
    assert await fake.categorize("Any memo") == "Entertainment"
    assert fake.call_count == 1

    failing_fake = FakeCategorizer(should_fail=True)
    with pytest.raises(RuntimeError) as exc_info:
        await failing_fake.categorize("Failing memo")
    assert "Fake LLM forced failure" in str(exc_info.value)


@pytest.mark.asyncio
async def test_100_sample_transaction_memos_evaluation() -> None:
    """Deliverable: Accuracy evaluation on a dataset of 100 sample transaction memos.

    Asserts >= 90% categorization accuracy across realistic financial payment memos.
    """
    categorizer = RuleBasedCategorizer()

    # 100 realistic transaction memos mapped to expected ground-truth categories
    dataset: list[tuple[str, str]] = [
        # Food & Dining (15)
        ("Starbucks Store #1402 Seattle WA", "Food & Dining"),
        ("McDonald's Fast Food Lunch", "Food & Dining"),
        ("Chipotle Mexican Grill", "Food & Dining"),
        ("Domino's Pizza delivery order", "Food & Dining"),
        ("Whole Foods Market Organic Groceries", "Food & Dining"),
        ("Trader Joe's groceries", "Food & Dining"),
        ("Blue Bottle Coffee Espresso", "Food & Dining"),
        ("DoorDash food delivery", "Food & Dining"),
        ("Uber Eats dinner takeout", "Food & Dining"),
        ("Panera Bread bakery & soup", "Food & Dining"),
        ("Shake Shack burger and fries", "Food & Dining"),
        ("Subway sandwich shop", "Food & Dining"),
        ("Local Italian restaurant dinner", "Food & Dining"),
        ("Corner cafe cappuccino", "Food & Dining"),
        ("Sweetgreen salad bowl", "Food & Dining"),
        # Transportation (15)
        ("Uber ride from downtown", "Transportation"),
        ("Lyft ride to office", "Transportation"),
        ("Yellow Cab NYC taxi service", "Transportation"),
        ("Shell Oil Gas Station fuel", "Transportation"),
        ("Chevron gas fill up", "Transportation"),
        ("MTA subway transit card refill", "Transportation"),
        ("Bart metro transit fare", "Transportation"),
        ("Delta Airline roundtrip flight", "Transportation"),
        ("United Airlines baggage fee", "Transportation"),
        ("Amtrak train passenger ticket", "Transportation"),
        ("Airport daily parking lot B", "Transportation"),
        ("City center parking garage", "Transportation"),
        ("Highway express toll payment", "Transportation"),
        ("Mobil gas station diesel", "Transportation"),
        ("ExxonMobil fuel pump", "Transportation"),
        # Utilities (12)
        ("Consolidated Edison electric power", "Utilities"),
        ("City water and sewer district", "Utilities"),
        ("Comcast Xfinity broadband internet", "Utilities"),
        ("AT&T monthly phone bill", "Utilities"),
        ("Verizon wireless mobile service", "Utilities"),
        ("Pacific Gas & Electric utility bill", "Utilities"),
        ("Spectrum home wifi service", "Utilities"),
        ("Municipal water services", "Utilities"),
        ("National Grid gas heating utility", "Utilities"),
        ("T-Mobile cell phone bill", "Utilities"),
        ("City electric utility payment", "Utilities"),
        ("Waste management trash service", "Utilities"),
        # Entertainment (13)
        ("Netflix 4K streaming plan", "Entertainment"),
        ("Spotify Premium music subscription", "Entertainment"),
        ("Hulu monthly streaming service", "Entertainment"),
        ("Disney Plus annual subscription", "Entertainment"),
        ("AMC Theatres movie tickets", "Entertainment"),
        ("Regal Cinema IMAX movie", "Entertainment"),
        ("Steam video game purchase", "Entertainment"),
        ("PlayStation Network digital game", "Entertainment"),
        ("Xbox Live game pass ultimate", "Entertainment"),
        ("Ticketmaster live concert ticket", "Entertainment"),
        ("Live Nation stadium concert", "Entertainment"),
        ("Nintendo eShop game download", "Entertainment"),
        ("Broadway theatre ticket show", "Entertainment"),
        # Payroll (12)
        ("Acme Corp payroll direct deposit", "Payroll"),
        ("Monthly employer salary payment", "Payroll"),
        ("Bi-weekly wage compensation", "Payroll"),
        ("Quarterly performance bonus", "Payroll"),
        ("Contractor hourly wages payout", "Payroll"),
        ("Corporate payroll deposit", "Payroll"),
        ("Graduate research stipend", "Payroll"),
        ("Staff salary direct deposit", "Payroll"),
        ("Annual incentive bonus compensation", "Payroll"),
        ("Consulting fee salary payment", "Payroll"),
        ("Employee payroll transfer", "Payroll"),
        ("Overtime wage deposit", "Payroll"),
        # Shopping (13)
        ("Amazon.com prime order retail", "Shopping"),
        ("Walmart supercenter shopping", "Shopping"),
        ("Target retail store purchase", "Shopping"),
        ("Best Buy electronics store", "Shopping"),
        ("Apple Store iPhone accessory", "Shopping"),
        ("IKEA home furniture store", "Shopping"),
        ("eBay marketplace online purchase", "Shopping"),
        ("Zara clothing store purchase", "Shopping"),
        ("Nike shoes retail outlet", "Shopping"),
        ("Home Depot hardware supplies", "Shopping"),
        ("Costco wholesale club shopping", "Shopping"),
        ("Sephora cosmetics and beauty", "Shopping"),
        ("Nordstrom shopping mall purchase", "Shopping"),
        # Health & Medical (10)
        ("CVS Pharmacy prescription medicine", "Health & Medical"),
        ("Walgreens pharmacy health supplies", "Health & Medical"),
        ("Downtown Dental clinic cleaning", "Health & Medical"),
        ("Family doctor annual checkup", "Health & Medical"),
        ("City general hospital clinic", "Health & Medical"),
        ("Prescription refill copay", "Health & Medical"),
        ("Mental health therapy session", "Health & Medical"),
        ("Optometry eye clinic exam", "Health & Medical"),
        ("Physical therapy medical rehab", "Health & Medical"),
        ("Rite Aid pharmacy vitamins", "Health & Medical"),
        # Transfer (10)
        ("Venmo split dinner with roomie", "Transfer"),
        ("Zelle transfer to brother", "Transfer"),
        ("Monthly apartment rent payment", "Transfer"),
        ("Reimbursement for groceries split", "Transfer"),
        ("Cash App p2p transfer", "Transfer"),
        ("Settle weekend trip expenses", "Transfer"),
        ("Repay loan from friend", "Transfer"),
        ("Wire transfer to landlord", "Transfer"),
        ("Rent split payment", "Transfer"),
        ("Friend repayment transfer", "Transfer"),
    ]

    assert len(dataset) == 100, f"Expected exactly 100 evaluation items, got {len(dataset)}"

    correct = 0
    failures = []

    for memo, expected in dataset:
        actual = await categorizer.categorize(memo)
        if actual == expected:
            correct += 1
        else:
            failures.append((memo, expected, actual))

    accuracy = (correct / len(dataset)) * 100.0
    print(f"\nCategorizer Benchmark: {correct}/100 correct ({accuracy:.1f}% accuracy)")

    assert accuracy >= 95.0, (
        f"Categorization benchmark failed: accuracy {accuracy}% is below 95% threshold. "
        f"Failures: {failures[:5]}"
    )
