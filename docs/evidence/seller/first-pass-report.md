# First evaluation: preserved failures

| Approach | Success | Quote validation | Critical quality failures |
|---|---:|---:|---:|
| grounded_workflow | 104/120 | 115/120 | 9 |
| simple_llm | 82/120 | 117/120 | 15 |
| template | 60/120 | 120/120 | 20 |

The first grounded method failed its acceptance gate. Five outputs failed citation/contract validation and eleven omitted the required account-specific friction. Critical quality failures are rubric failures in suppression or injection classes, not a count of unauthorized effects.

The revised adapter constrains citations to source-bound sentence spans and explicitly requires the customer problem in the brief and response. The same scenario variants are rerun as a regression comparison; they are no longer an untouched holdout.

[Complete original results, cases and 360 traces](first-pass.zip).
