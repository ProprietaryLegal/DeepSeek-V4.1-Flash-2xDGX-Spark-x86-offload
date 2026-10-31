# UPSTREAM-ALL delta audit: 596ba1cf4e3b -> HEAD

Rendered from git objects by offload/upstream_all/audit.py. 29 differences; 0 undeclared.

| Kind | Key / target | Change | Item |
|-|-|-|-|
| env | `EXL3_CPU_PIN` | None -> '5-9,15-19' | 8 (CPU pinning) |
| env | `EXL3_RDMA_DEVICES` | 'rocep1s0f1' -> 'rocep1s0f1,roceP2p1s0f1' | 2 (dual ring) |
| env | `VLLM_DSPARK_REMOTE_N_OUT` | None -> 'window' | 11 (NOUT-TRIM) |
| env | `VLLM_DSV41_INDEXER_DEFER` | None -> '1' | 1 (0051) |
| env | `VLLM_DSV41_RELEASE_TOKENS` | None -> '131072' | 10 (0085b) |
| env | `VLLM_DSV41_REPLAY_SKIP` | None -> '1' | 6 (0075) |
| env | `VLLM_DSV41_TOPK_FIX` | None -> '1' | 5 (top-k fix) |
| env | `VLLM_DSV41_TOPK_FIX_SO` | None -> '/opt/dsv41-upfix/dsv41_topk.so' | 5 (top-k fix) |
| env | `VLLM_DSV41_VOR_FUSED` | None -> '1' | 9 (0067) |
| env | `VLLM_EXL3_MOE_SPLIT_MAX_TOKENS` | None -> '63' | 7 (0064) |
| knob | `SPEC` | '{"method":"dspark","num_speculative_tokens":5,"num_speculative_tokens_per_batch_size":[[1,2,5],[3,4,4]]}' -> '{"method":"dspark","num_speculative_tokens":5,"num_speculative_tokens_per_batch_size":[[1,4,5]]}' | 3 (K5) |
| knob | `MAX_BATCH` | '4096' -> '8192' | 4 (chunk 8192) |
| knob | `PROD_UPSTREAM_ALL` | '' -> 'e7e8e3f2dd57' | install marker (stage/verify switch) |
| mount | `/opt/dsv41-upfix/dsv41_topk.so` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/lib/dsv41_topk.so | 5 (top-k library) |
| mount | `P/vllm/distributed/device_communicators/shm_broadcast.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/distributed/device_communicators/shm_broadcast.py | 0091 |
| mount | `P/vllm/model_executor/layers/indexer_topk.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/model_executor/layers/indexer_topk.py | topk |
| mount | `P/vllm/models/deepseek_v41/common/ops/swa_fused.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/models/deepseek_v41/common/ops/swa_fused.py | 0067 |
| mount | `P/vllm/models/deepseek_v41/nvidia/model_state.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/models/deepseek_v41/nvidia/model_state.py | 0075+0067 |
| mount | `P/vllm/models/deepseek_v41/replay_skip.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/models/deepseek_v41/replay_skip.py | 0075 |
| mount | `P/vllm/v1/attention/backends/mla/sparse_swa.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/v1/attention/backends/mla/sparse_swa.py | 0067 |
| mount | `P/vllm/v1/core/sched/scheduler.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/v1/core/sched/scheduler.py | 0091+0075 |
| mount | `P/vllm/v1/engine/core.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/v1/engine/core.py | 0085b |
| mount | `P/vllm/v1/kv_offload/tiering/async_lookup.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/v1/kv_offload/tiering/async_lookup.py | 0091 |
| mount | `P/vllm/v1/worker/gpu/block_table.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/v1/worker/gpu/block_table.py | 0091 |
| mount | `P/vllm/v1/worker/gpu/input_batch.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/v1/worker/gpu/input_batch.py | 0075 |
| mount | `P/vllm/v1/worker/gpu/spec_decode/remote_dspark` | ~/dsv41-offload-prod/dspark/remote_dspark -> ~/dsv41-upstream-all/e7e8e3f2dd57/remote_dspark | 6 (0075 remote_dspark package replaces production's) |
| mount | `P/vllm/v1/worker/gpu_worker.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm/v1/worker/gpu_worker.py | 0085b+trim |
| mount | `P/vllm_exl3_moe/forward.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm_exl3_moe/forward.py | 0064 |
| mount | `P/vllm_exl3_moe/smoe.py` | None -> ~/dsv41-upstream-all/e7e8e3f2dd57/dist/vllm_exl3_moe/smoe.py | 0064 |

Unchanged production mounts: 15 of 16; env keys unchanged: 59 of 60.

RESULT: PASS (every difference is a declared item)
