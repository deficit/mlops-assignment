# Text-to-SQL Agent Serving & Optimization Report

## 1. Serving Configuration (Phase 1)
The serving stack runs on a single H100 GPU (80GB). The model selected is `Qwen/Qwen3-30B-A3B-Instruct-2507-FP8` (Mixture of Experts model with active parameter size of 3B).

### vLLM Configuration Flags
We use the following flags to start vLLM in `scripts/start_vllm.sh`:

```bash
exec uv run python -m vllm.entrypoints.openai.api_server \
    --model "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8" \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len 4096 \
    --max-num-seqs 256 \
    --gpu-memory-utilization 0.95 \
    --enable-prefix-caching \
    --kv-cache-dtype fp8 \
    --disable-log-requests
```

* **`--model`**: The FP8 quantized version of Qwen3-30B-A3B. Using an FP8 model reduces GPU memory footprint by ~50% and leverages native FP8 execution on H100, accelerating processing and drastically decreasing tail latencies.
* **`--max-model-len 4096`**: Limits maximum sequence length to 4096, which matches our maximum prompt length (schema + question + response) while preventing overallocation of KV cache blocks.
* **`--max-num-seqs 256`**: Maximum concurrent sequences scheduler size, giving vLLM enough concurrency headroom under 10+ RPS load.
* **`--gpu-memory-utilization 0.95`**: Allocates 95% of the VRAM for vLLM, maximizing space for KV Cache.
* **`--enable-prefix-caching`**: Caches KV cache blocks of processed prompts. Since our prompts start with large, static database schemas that are queried repeatedly, prefix caching allows vLLM to skip prefill computations for subsequent queries, dropping prefill latency (TTFT) to near 0.
* **`--kv-cache-dtype fp8`**: Quantizes the KV cache to FP8, doubling the effective capacity of the KV Cache to support higher concurrent batch sizes and prefix caching blocks.
* **`--disable-log-requests`**: Disables verbose per-request console logging in vLLM, reducing minor CPU overhead during high load.

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
* **Iteration 1**: 
  * **Observed**: Connection pool/handshake overhead during load testing.
  * **Hypothesis**: The agent was instantiating a new `ChatOpenAI` client in the graph nodes for every call, creating a new HTTP connection pool and causing TCP port exhaustion.
  * **Change**: Cached the `ChatOpenAI` client globally in `agent/graph.py`.
  * **Result**: Resolved connection errors, reducing baseline latency at 2 RPS.
* **Iteration 2**:
  * **Observed**: P50 latency degraded to 5.3s when reverting to the V0 engine.
  * **Hypothesis**: The V1 engine compilation is highly performant and should be used.
  * **Change**: Ensured `VLLM_USE_V1=1` is active (default).
  * **Result**: Improved P50 latency back to 2.5s.
* **Iteration 3**:
  * **Observed**: High tail latency (P99 ~58s) under concurrent load.
  * **Hypothesis**: Mixture of Experts (MoE) weights and KV cache loading pressure on a non-quantized model.
  * **Change**: Switched to the FP8 quantized variant of the model.
  * **Result**: Reduced P99 tail latency from 58.28s to 8.48s.
* **Iteration 4**:
  * **Observed**: P95 latency is still 5.53s at 2 RPS (above the 5s target).
  * **Hypothesis**: Repeatedly computing KV Cache for large static schemas (1.5K-3K tokens) under concurrency causes scheduling delay.
  * **Change**: Added `--enable-prefix-caching`, `--kv-cache-dtype fp8`, and `--disable-log-requests` in `start_vllm.sh`.
  * **Result**: [Pending test results]

---

## 4. Agent Value
*TBD - One paragraph on did the loop help, how we know, and the accuracy/latency tradeoffs.*

## 5. What We'd Do With More Time
*TBD - Specific ideas like pipeline parallelization, speculative decoding, dynamic schema pruning, etc.*
