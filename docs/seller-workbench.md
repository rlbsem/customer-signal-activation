# Seller workbench: evidence to reviewed action

The application helps a seller understand an account inquiry, prepare a relevant response and create a reviewed CRM task. Model inference is an optional, bounded component of the existing Customer Signal & Activation system. The original financial oracle, acquisition fixture and seven dbt models keep their original meaning.

## Run the application

Use the repository's Python 3.12 environment and pinned dependencies described in the [README](../README.md).

```text
python scripts/fetch_seller_model.py
```

This downloads the official Qwen3-14B Q4_K_M weights at a pinned revision and verifies their SHA-256. The 9.0 GB weights and inference runtime are not included in the repository. A GPU with sufficient free memory is recommended. Download a compatible llama.cpp runtime from its [official releases](https://github.com/ggml-org/llama.cpp/releases). The executed evidence uses version b10809 and the Windows Vulkan backend.

```text
llama-server -m work/models/Qwen3-14B-Q4_K_M.gguf --alias qwen3-14b --jinja --reasoning off --ctx-size 8192 --parallel 1 --n-gpu-layers 99 --host 127.0.0.1 --port 8093 --api-key YOUR_LOCAL_MODEL_TOKEN
python scripts/seller.py --workspace work/seller-demo
```

After starting the local workbench server, open `http://127.0.0.1:8530` in a browser on the **same computer** and enter the operator token printed by the launcher. This address is not a publicly hosted demo. The server holds provider and destination credentials; they do not appear in HTML, JavaScript or recorded model inputs. The workbench starts a separate authenticated synthetic CRM receiver with its own database. The fixed scenario clock is March 31, 2026 and is displayed in the interface.

Generate a private local model token and set `SELLER_MODEL_KEY` to the same value before launching the application or evaluation. Use `$env:SELLER_MODEL_KEY = 'your-generated-token'` in PowerShell or `export SELLER_MODEL_KEY='your-generated-token'` in a POSIX shell. Keep the actual value out of repository files and screenshots. The model-server key prevents unrelated browser pages from calling local inference directly.

`--model-url` and `--model` configure a compatible chat-completions provider. `SELLER_MODEL_KEY` supplies its credential. Structured JSON-schema output and a non-thinking response are required. Compatibility with arbitrary providers is not claimed. Set an explicit provider spending limit before paid execution; token counts alone do not establish cash cost.

`--no-model` starts the interface without inference. Existing saved workspace runs remain inspectable. A new empty workspace in this mode has no generated results. Failure to reach a configured provider is recorded as a failed generation, never replaced with a simulated model answer.

The Evaluation evidence tab also loads the committed benchmark and lets reviewers compare actual saved outputs from each approach, inspect their original source documents and see every scorer check. This works with `--no-model`, without downloading weights or obtaining credentials. These records are labelled as recorded execution.

## Review flow and boundaries

1. Choose an account and inspect inquiry documents, approved product information and authoritative state.
2. Generate a live brief. Repeated requests for the identical evidence, prompt and model configuration return the saved run and are labelled as cached.
3. Inspect exact source quotations and the model's interpretation, response, questions and unknowns.
4. Use **Prepare governed review**, inspect the controlled response and any separately registered operational authority, then approve its exact content. Free-form model prose remains advisory. See the [execution contract and operator procedure](seller-authority.md).
5. Deliver the approved CRM task. The receiver persists an idempotent receipt. If acknowledgement is lost, the next attempt looks up that receipt before sending anything again.

The model does not send email or alter consent, identity, account ownership, lifecycle state or financial facts. A withdrawn canonical permission, changed source evidence or expired proposal blocks approval/delivery. Rejection is terminal for that run. Approved content is immutable; a conflicting second approval is refused. Existing remote effects are retained when later evidence changes.

Documents enter through an authenticated operator endpoint (`POST /api/documents`). This proves scoped document admission, not live web research, speech transcription, vendor enrichment or a Salesforce/HubSpot connector. Source IDs are immutable; a changed document needs a new source ID. Sources older than 30 scenario days are excluded from inference, with an explicit reason. All admitted account document changes invalidate existing proposals conservatively.

The grounded adapter offers only source-bound exact sentence spans for citations through structured decoding. The model selects the evidence; the adapter does not invent or repair a model's answer. Post-inference validation checks the complete contract and every source/quote pair. The simple LLM baseline uses the same model, sampling parameters, snapshots and output fields, with unconstrained citation text. This compares the complete grounded method with a basic prompt, rather than isolating prompt wording alone. Exact quotation does not prove that unrestricted generated prose is semantically supported. Seller review remains required. There is no calibrated purchase probability or measured pipeline uplift.

## Execution and evaluation

```text
python scripts/evaluate_seller.py --development --cases 6 --repeats 1 --output work/seller-development
python scripts/evaluate_seller.py --cases 60 --repeats 2
python scripts/verify.py
python scripts/package.py
```

The benchmark compares a deterministic template, a simple LLM prompt and the grounded workflow on identical snapshots. Expectations and rubric labels never enter model input. Each trace includes input, raw output, provider provenance, seed, token usage, latency and scorer checks. Evaluation resumes only when stored configuration hashes match. Use a new output directory after changing the model, prompt, rubric or cases.

The mechanical acceptance rule is at least 90% task success with zero failures in suppression and injection classes, plus a reported comparison against both baselines. These are acceptance criteria for a finite synthetic suite, not an enterprise service-level guarantee. The delivered comparison reruns the scenario variants after fixing citation defects found in the first evaluation; it is a regression evaluation, not an untouched holdout. All case families are known to the implementer. The first evaluation and its failures remain available as an archive. Human review of response usefulness is reported separately and cannot be inferred from a keyword check.

Software tests use explicitly handwritten responders. Those outputs never count as inference evidence. Live inference is optional in CI: paid credentials and downloaded model weights are not required to verify authority, review, delivery, browser and regression behaviour.

Three additional dbt models live in a separate `seller_dbt` project: generation facts, approved-action facts and an operating mart. Run `python scripts/export_seller_evidence.py --workspace work/seller-demo --warehouse work/seller-warehouse` after exercising the application. The warehouse directory must be new. Source and mart conservation tests guard against approval-audit fanout. Approval elapsed time includes waiting time and is not measured human labour. These operational metrics do not alter the original commercial cash lineage.

## Operational scope

The local application binds to loopback. Cookie sessions are HTTP-only and SameSite strict; mutations reject a mismatched browser Origin. All account and run API reads require operator access. HTML rendering treats model/source text as text, with a restrictive content security policy. The application is designed for one trusted local operator; it is not a multitenant Internet deployment.

Generation is serialized, context is capped at 32 KB, output at 1,400 tokens and workspace generation records at 200. The provider timeout is 120 seconds. Remote execution is a single serialized lane, holding the source transaction while validating and dispatching; this prevents concurrent source changes during a local dispatch, with the throughput tradeoff recorded explicitly.

Run on demand. No AWS resources, paid vendor subscription, scheduler or continually attended public endpoint is required. Actual hardware and electricity costs are not priced by this project.
