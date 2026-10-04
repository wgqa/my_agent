# Engineering Planner no-retrieval alignment

Retained: the Engineering-only, contract-complete Planner prompt. The old Gate 3 v1 default and identity remain available. QueryPlan/parser/fallback, Router/Guard, Decision prompt, tools and 5/4/2 are unchanged. No directory restructuring or long-term Task/Evidence/Execution v2 implementation is included.

The baseline is the pre-slice **working tree**, including the prior retained document-domain and evidence-excerpt changes; HEAD alone does not reconstruct it. `initial_manifest.json` captures the original three production files and 18 protected files. `baseline/` and `retained/` contain exact byte snapshots. `manifest.json` freezes both prompt identities, the eight cases, helpers and Requests source pin before the paid run.

`comparison_server.py` uses current production assembly, selecting only the baseline or candidate Planner prompt, with passive observers. `run_comparison.py` makes exactly 16 interleaved requests: eight cases, one request per arm, alternating order, no paid retries. The raw run has 53 actual provider calls, including Planner and one unsuccessful baseline Decision repair. Runtime databases/configs stay in the isolated local run directory; only raw observations/results/server logs and run manifest are archived here.

Four direct tasks went from 0/4 to 4/4 correctly completed. Document/source evidence acquisition and missing-document refusal still operate. `manual_review.json` preserves the candidate R02 semantic regression and C01 incomplete grounding; `completed` is not a correctness metric. Same-assistant development review, no holdout or independent acceptance. See [validation report](../../docs/validation/2026-10-03-planner-no-retrieval-alignment.md).

Provider-free verification:

```bash
python -m evaluation.no_retrieval_alignment_20261003.analyze
```

The script checks immutable inputs, the 18 protected files and 56 prior archive files, exact paired coverage, prompt/tool identities, budgets, direct-result values, negative refusal and the 37-module CI/runbook alignment. `outcome.json` is the summary at the retained implementation. `final_integrity.json` binds the final archive and test module bytes. `raw/knowledge_context_reconstruction.json` is an offline reconstruction from the candidate C01 plan and verified corpus, not an extra model run.

An optional paid rerun, using a clean checkout at Requests `b25c87d7cb8d6a18a37fa12442b5f883f9e41741` and original corpus `870e5864df67`:

```bash
python -m evaluation.no_retrieval_alignment_20261003.run_comparison \
  --project-root /path/to/requests \
  --corpus-root /path/to/verified/corpus \
  --output-dir /path/to/new/output \
  --live
```

Without `--live`, it only validates inputs. Outputs must not already exist. Future development may intentionally invalidate production-file hashes; preserve this archive instead of updating its manifest to match later code.
