"""Creates the approved pilot Untangle products/prices in Stripe test mode,
reusing them if they already exist. Prints the env lines to put into .env.

Usage:
    .venv/bin/python scripts/create_stripe_prices.py [sk_test_...]

Without an argument, the Stripe CLI's stored test key is used
(`stripe config --list`), which requires a non-expired `stripe login`.
"""

from __future__ import annotations

import subprocess
import sys

# Approved pilot amounts. This script still refuses live Stripe keys.
PLANS = {
    "pro": ("Untangle Pro", 1480),
    "max": ("Untangle Max", 3980),
}


def _cli_test_key() -> str:
    output = subprocess.run(
        ["stripe", "config", "--list"], capture_output=True, text=True, check=True
    ).stdout
    for line in output.splitlines():
        if "test_mode_api_key" in line:
            return line.split("'")[1]
    raise SystemExit("No test key in stripe CLI config. Run: stripe login")


def ensure_price(plan: str, name: str, amount: int) -> str:
    import stripe

    products = [p for p in stripe.Product.list(limit=100).data if p.active and p.name == name]
    product = products[0] if products else stripe.Product.create(name=name, metadata={"plan": plan})

    prices = stripe.Price.list(product=product.id, active=True, limit=10).data
    price = next((p for p in prices if p.recurring and p.unit_amount == amount), None)
    if not price:
        price = stripe.Price.create(
            product=product.id,
            unit_amount=amount,
            currency="jpy",
            recurring={"interval": "month"},
            metadata={"plan": plan},
        )
    return price.id


def main() -> None:
    import stripe

    stripe.api_key = sys.argv[1] if len(sys.argv) > 1 else _cli_test_key()
    if not stripe.api_key.startswith("sk_test_"):
        raise SystemExit("Refusing to run against a non-test key.")

    for plan, (name, amount) in PLANS.items():
        price_id = ensure_price(plan, name, amount)
        print(f"STRIPE_PRICE_ID_{plan.upper()}={price_id}")


if __name__ == "__main__":
    main()
