---
name: policy-review
description: Legal and compliance policy review for proposed actions and outputs
license: MIT
---

# Policy Review

## Purpose
Review proposed actions, department outputs, and org changes against the compliance policy framework. Every publish-class action must pass this review.

## Policy Framework

### LGL-001: Publishing Requires Owner Approval
Any action that publishes data, deploys code, sends external communications, or writes to production systems requires explicit owner approval.

### LGL-002: No Destructive Operations
Destructive operations (rm -rf, DROP TABLE, force-push, format) are strictly prohibited.

### LGL-003: Financial Transactions Require Owner
Trading, transferring funds, executing orders, deploying capital require owner sign-off.

### LGL-004: External API Writes Require Review
POST/PUT/DELETE to external APIs, webhooks, cloud infrastructure requires approval.

### LGL-005: User Data and PII Protection
Accessing, processing, or transmitting user data, PII, passwords, secrets is prohibited.

### LGL-006: Model Training Requires Owner
Training, fine-tuning, or modifying ML models requires approval.

### LGL-007: Infrastructure Changes Require Owner
Creating/deleting VMs, changing firewall rules, DNS, Kubernetes requires approval.

### LGL-008: No Circumvention
Splitting prohibited actions, encoding commands, or social engineering is itself a violation.

## Review Process
1. Read the proposed action carefully
2. Check against EVERY rule above — cite specific rule IDs
3. Return verdict: approved, denied (cite rule), or needs_changes
4. If the owner must approve, say "requires_owner" and cite the rule
5. Be precise — a denial must cite a specific policy ID

## Verdict Format
- verdict: approved | denied | needs_changes
- requires_owner: true | false
- policy_ids: [list of applicable rule IDs]
- reasoning: detailed analysis
- risk_level: low | medium | high | critical
