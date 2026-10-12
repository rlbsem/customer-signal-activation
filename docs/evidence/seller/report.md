# Executed seller workflow evaluation

| Approach | Proposal checks passed | Critical quality failures | Median / p95 inference | Tokens |
|---|---:|---:|---:|---:|
| grounded_workflow | 120/120 | 0 | 3.76s / 4.76s | 141,404 |
| simple_llm | 81/120 | 16 | 4.61s / 5.69s | 104,262 |
| template | 60/120 | 20 | 0.00s / 0.00s | 0 |

The suite has 60 distinct synthetic cases. Repeated runs are not independent customer samples. Cases cover discovery, ambiguity, support, suppression, contradictory requirements and hostile note instructions.

The rubric tests action choice, exact quotation and required information. It does not prove general semantic support or seller usefulness. Human usefulness review is pending. No conversion or revenue uplift is claimed.

All case families are known to the implementer. The delivered run is a regression comparison after source-bound citation decoding was added in response to defects in the first evaluation. The earlier failed evaluation is preserved. This is not an independently curated or blinded external benchmark.

[Evaluation and acceptance results](evaluation.json) · [Cases and fixed rubric](suite.json)
