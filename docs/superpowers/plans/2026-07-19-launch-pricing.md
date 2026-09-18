# Launch Pricing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved Basic/Pro/Max launch quotas and pilot prices consistently across backend defaults, infrastructure, Stripe test helpers, tests, and product documentation.

**Architecture:** Keep environment-overridable plan limits as the single runtime contract. Update every default source together, add regression assertions for the full plan matrix, and leave live Stripe product creation as an external action after the active OpenAI rate card is verified.

**Tech Stack:** Python 3.12, pytest, Terraform, Stripe test-mode helper.

---

### Task 1: Lock the approved runtime contract

**Files:**
- Modify: `backend/test_billing.py`
- Modify: `backend/core/plans.py`

- [ ] Assert the full approved plan matrix in `PlanLimitTests`.
- [ ] Run the focused test and verify it fails against old defaults.
- [ ] Update backend defaults to Basic 5/30/50/12k/$0.30, Pro
  50/500/150/36k/$3, and Max 150/1500/300/72k/$9.
- [ ] Run the focused test and verify it passes.

### Task 2: Align deploy-time configuration

**Files:**
- Modify: `backend/.env.example`
- Modify: `infra/modules/reading-assistant-api/variables.tf`
- Modify: `infra/envs/dev/variables.tf`
- Modify: `infra/envs/prod/variables.tf`

- [ ] Apply the same article, chat, sentence, source-token, and micro-USD values
  in all four configuration surfaces.
- [ ] Retain raw token budgets as calibration-only values.
- [ ] Run Terraform formatting and validation for dev and prod.

### Task 3: Align Stripe test setup and documentation

**Files:**
- Modify: `backend/scripts/create_stripe_prices.py`
- Modify: `docs/BILLING.md`
- Modify: `docs/MONETIZATION.md`

- [ ] Set Stripe test helper prices to Pro JPY 980 and Max JPY 2,980.
- [ ] Remove “provisional” from test product names while keeping the helper
  restricted to `sk_test_` keys.
- [ ] Document approved pilot prices, quotas, quota-only differentiation,
  assumptions, and pre-public evidence requirements.
- [ ] Do not create or modify live Stripe resources.

### Task 4: Verify

- [ ] Run `python3 -m pytest -q backend`.
- [ ] Run Terraform format checks and validation for dev and prod.
- [ ] Search for stale launch prices and plan-limit defaults.
- [ ] Run `git diff --check`.
- [ ] Report the implementation without committing unless explicitly requested.
