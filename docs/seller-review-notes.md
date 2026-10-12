# Focused source-support review: seller drafts

This is a **targeted QA note** for the committed, synthetic Qwen3-14B regression evidence. It is **not** a blinded independent usefulness assessment and does not modify the archived model outputs, scoring, or runtime provenance.

## Finding: unsupported support availability and escalation commitments

In the saved [grounded workflow support-incident trace](evidence/seller/traces/grounded_workflow-regression-008-42.json), the customer says their workflow stopped after a configuration change and requests support involvement before discussing expansion. The correct selected action is `support_handoff`.

The generated **draft** additionally says the seller's support team "is available to assist with this issue." The supplied evidence confirms the customer's request, **not the support team's present availability or response time**. Related support-incident traces include similar statements such as "ready to assist," "prepared to assist," and an offer of "immediate assistance" (for example, [case 050](evidence/seller/traces/grounded_workflow-regression-050-42.json), [case 014](evidence/seller/traces/grounded_workflow-regression-014-42.json), and [case 020](evidence/seller/traces/grounded_workflow-regression-020-42.json)). These phrases should not pass into an approved external communication without confirmation.

The benchmark's published **120/120** score measures its specified mechanical checks: action choice, valid exact-source quotation, scenario-specific detail, and enumerated prohibited commitments. This unsupported implication is an example of semantic support the rubric does **not** fully detect. A mechanically passing proposal is not automatically a send-ready response.

### Suggested reviewer-edited response

> Thank you for reporting that your workflow stopped after a configuration change. I understand that you want the incident addressed before discussing expansion. Could you share the approximate time of the change and any error messages? I will confirm the appropriate support contact internally before setting any expectation about availability or resolution timing.

**Label:** illustrative *reviewer edit*, **not** original LLM output, not an approved CRM action, and not part of the recorded benchmark. The original generated text and execution evidence remain unchanged for reproducibility.

## Focused manual inspection

I inspected representative recorded grounded-workflow traces for discovery, ambiguous requirements, and support incidents (including cases 000, 008, 014, 020, 032, 043, 050 and 055 at seed 42). In this non-blinded spot-check, the selected next actions matched the recorded source situations. The support drafts contained the unsupported staffing/availability language noted above; this is a **review finding**, not an independent quality score.

## Reviewer acceptance guidance

Before approving a task or reusing drafted text, verify both the cited customer facts **and** uncited operational statements. For support incidents, don't promise staffing, an escalation having occurred, immediate attention, or resolution timing unless an authoritative operational source or seller confirmation supports those claims. Edit the response or reject it. Customer/source documents are untrusted input; model prose is never the system of record.

This note does not claim that the issue is eliminated in fresh inference. A future prompt/rubric improvement should be **re-evaluated with new model traces and versioned provenance**, not retroactively applied to the published comparison. Independent blinded human usefulness assessment remains pending.
