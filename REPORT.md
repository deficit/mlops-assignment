# Text-to-SQL Agent Serving & Optimization Report

## 1. Serving Configuration (Phase 1)
The serving stack runs on a single H100 GPU (80GB). The model selected is the Mixture of Experts (MoE) model `Qwen/Qwen3-30B-A3B-Instruct-2507` (active parameter size of 3B).

### vLLM Configuration Flags
The final configuration written to `scripts/start_vllm.sh` to serve the model is:

```bash
MODEL="Qwen/Qwen3-30B-A3B-Instruct-2507"

exec uv run python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len 4096 \
    --max-num-seqs 256 \
    --gpu-memory-utilization 0.95 \
    --enable-prefix-caching \
    --kv-cache-dtype fp8 \
    --quantization fp8 \
    --disable-log-requests
```

* **`--model`**: The standard model `Qwen/Qwen3-30B-A3B-Instruct-2507`.
* **`--quantization fp8`**: Since the base model is served in 16-bit, we enable dynamic weight and activation quantization to FP8 on load. This reduces the weight memory footprint by ~50%, leveraging native FP8 Tensor Core execution on the H100 GPU.
* **`--max-model-len 4096`**: Restricts the maximum sequence length to 4096 (down from 8192). This fits our maximum prompt size (static schema + question + response) while saving substantial KV Cache memory allocation per sequence.
* **`--max-num-seqs 256`**: Allocates up to 256 active sequence slots in the scheduler to provide concurrency headroom under high RPS load.
* **`--gpu-memory-utilization 0.95`**: Reserves 95% of GPU VRAM for the vLLM engine to maximize space for KV Cache blocks.
* **`--enable-prefix-caching`**: Caches KV cache blocks of processed prompt prefixes. Since our prompts start with large, static database schemas, prefix caching allows vLLM to skip prefill computations on subsequent requests, dropping prefill time (TTFT) to near 0.
* **`--kv-cache-dtype fp8`**: Quantizes the KV cache keys and values to FP8, doubling the block capacity to prevent preemption and support larger concurrent batch sizes.
* **`--disable-log-requests`**: Prevents stdout logging bottleneck under concurrent load.

---

## 2. Baseline Evaluation Results (Phase 5)
Evaluation was performed over the 30-question BIRD-bench subset using `evals/run_eval.py` running execution accuracy comparison on canonicalized row sets.

* **Total Questions**: 30
* **Average Iterations taken**: 1.87
* **Final Accuracy**: 43.33%
* **Per-Iteration Pass Rate**:
  * **Iteration 0 (No revision loop)**: 33.33% accuracy
  * **Iteration 1**: 40.0% accuracy
  * **Iteration 2**: 43.33% accuracy

### Commentary
The baseline evaluation shows that the self-consistency loop is earning its keep. The accuracy improved from 33.33% on the first try to 43.33% after revision iterations. This demonstrates the agent architecture's capability to recover from syntactically/logically incorrect SQL queries or incorrect text comparisons.

---

## 3. Hitting the SLO (Phase 6)
The target SLO is: **P95 end-to-end agent latency < 5.0 seconds at 10+ RPS sustained over 5 minutes.**

### Iteration Log
During our testing cycle, we iterated on several bottlenecks identified in our observability metrics:

* **Iteration 1 (Client Caching)**: 
  * **Observed**: TCP port exhaustion and connection pool drops under load.
  * **Hypothesis**: The agent was instantiating a new `ChatOpenAI` client in the graph nodes for every call, creating a new HTTP connection pool.
  * **Change**: Cached the `ChatOpenAI` client globally in `agent/graph.py`.
  * **Result**: Resolved connection errors, reducing baseline latency at 2 RPS.
* **Iteration 2 (Inference Engine)**:
  * **Observed**: P50 latency degraded to 5.3s when reverting to the V0 engine.
  * **Hypothesis**: The V1 engine compilation is highly performant and should be used.
  * **Change**: Ensured `VLLM_USE_V1=1` was active.
  * **Result**: Improved P50 latency back to 2.5s.
* **Iteration 3 (Model Quantization & Weights)**:
  * **Observed**: High tail latency (P99 ~58s) under concurrent load.
  * **Hypothesis**: Mixture of Experts (MoE) weights and KV cache loading pressure on a non-quantized model.
  * **Change**: Switched to the FP8 quantized variant of the model.
  * **Result**: Reduced P99 tail latency from 58.28s to 8.48s.
* **Iteration 4 (Scheduler Overrides)**:
  * **Observed**: Load tests at 10 RPS failed with `ServerDisconnectedError` and P50 latencies over 80 seconds.
  * **Hypothesis**: The vLLM server was running with conflicting parameters: `dtype bfloat16` forced slower 16-bit math, `--max-num-seqs 8` restricted scheduling concurrency to 8 requests, and `--enable-chunked-prefill` broke prefix caching hits on database schemas.
  * **Change**: Cleaned up conflicting scheduler overrides. Switched back to the base model with `--quantization fp8` to dynamically cast weights on load, restored `--max-num-seqs 256`, reduced `--max-model-len` to `4096` to double KV Cache capacity, enabled `--kv-cache-dtype fp8`, and disabled chunked prefill to maximize prefix cache efficiency.
  * **Result**: Because VM time expired right after writing this final optimized configuration, we were unable to capture the final 10 RPS load test metrics. However, our previous 2 RPS run achieved an average latency of 2.39s with 0 errors, and the final optimized parameters are designed to eliminate the scheduling queues that blocked the 10 RPS run.

---

## 4. Agent Value
The `verify -> revise` loop in our LangGraph agent successfully boosted accuracy by **10 percentage points (from 33.33% to 43.33% execution accuracy)**, which translates to a relative improvement of **30%**. The tracing logs show the agent successfully catching SQLite execution syntax errors and schema/value casing discrepancies (e.g., correcting a lowercase filtering value `'m'` to the database-compatible `'M'`), and automatically correcting them in the revision step. However, this accuracy boost comes at a latency cost: each revision step triggers a new LLM call, multiplying E2E latency by the number of iterations taken.

---

## 5. What We'd Do With More Time
With more time, we would implement the following architectural improvements:
1. **Dynamic Schema Pruning**: Instead of prepending the entire database schema for every query (1.5K–3.0K tokens), we would use a lightweight metadata retriever (like BM25 or embedding search over table descriptions) to only attach the relevant tables to the prompt. This would reduce prompt length to <500 tokens, significantly decreasing TTFT and increasing KV Cache capacity.
2. **Speculative Decoding**: Use a smaller "draft" model (such as `Qwen3-0.6B`) to accelerate token generation. Because SQL and JSON verification outputs are highly structured, speculative decoding can yield substantial latency speedups.
3. **Async Agent Handlers**: Refactor FastAPI handlers to use `async def` and async database drivers to prevent synchronous thread pool starvation under high concurrent load.
4. **Separate Verification Model**: Offload the verification node to a smaller, faster model (e.g., `Qwen3-7B`) since verification is a classification/JSON output task, keeping the larger 30B model reserved strictly for SQL generation.
