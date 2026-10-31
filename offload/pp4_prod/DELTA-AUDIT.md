# PP4 composition audit: b90ba5aaec30 -> HEAD

Rendered from git objects by offload/pp4_prod/audit.py --layer pp4 (stage 22897accecef). 13 differences; 0 undeclared.

| Kind | Key / target | Change | Item |
|-|-|-|-|
| env | `VLLM_DSPARK_DEPTH_FILE` | None -> '' | PP4 switch |
| env | `VLLM_DSPARK_DEPTH_POLICY` | None -> 'fixed:5' | PP4 switch |
| env | `VLLM_DSPARK_LOOKUP` | None -> '' | PP4 switch |
| env | `VLLM_DSPARK_REMOTE_N_OUT` | 'window' -> None | PP4 removes (NOUT-TRIM off at a fixed window) |
| env | `VLLM_DSPARK_REMOTE_WANT_MARGIN` | None -> '0' | PP4 switch |
| env | `VLLM_DSPARK_SAMPLED_TOP32` | None -> '1' | PP4 switch |
| env | `VLLM_DSV41_ADAPTIVE_K` | '1' -> '0' | PP4 switch |
| knob | `SPEC` | '{"method":"dspark","num_speculative_tokens":5,"num_speculative_tokens_per_batch_size":[[1,4,5]]}' -> '{"method":"dspark","num_speculative_tokens":5}' | PP4 fixed verify window 5 |
| knob | `PROD_PP4` | '' -> '22897accecef' | PP4 install marker (stage/verify switch) |
| mount | `P/vllm/v1/worker/gpu/dsv41_pp4_round_trace.py` | None -> ~/dsv41-pp4/22897accecef/dist/vllm/v1/worker/gpu/dsv41_pp4_round_trace.py | PP4 file (new mount) |
| mount | `P/vllm/v1/worker/gpu/model_runner.py` | ~/dsv41-kvpack/559c5867ba42/vllm/v1/worker/gpu/model_runner.py -> ~/dsv41-pp4/22897accecef/dist/vllm/v1/worker/gpu/model_runner.py | PP4 file (source moves to the PP4 stage) |
| mount | `P/vllm/v1/worker/gpu/spec_decode/rejection_sampler_utils.py` | None -> ~/dsv41-pp4/22897accecef/dist/vllm/v1/worker/gpu/spec_decode/rejection_sampler_utils.py | PP4 file (new mount) |
| mount | `P/vllm/v1/worker/gpu/spec_decode/remote_dspark` | ~/dsv41-upstream-all/e7e8e3f2dd57/remote_dspark -> ~/dsv41-pp4/22897accecef/remote_dspark | PP4 file (source moves to the PP4 stage) |

Unchanged production mounts: 29 of 31; env keys unchanged: 67 of 69; head mounts 33, env keys 73.

RESULT: PASS (env delta = the PP4 switches, mounts delta = the PP4 files)
