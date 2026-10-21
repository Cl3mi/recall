#!/usr/bin/env bash
# Fair-use guard for the SHARED HPC box, two-GPU aware. Extends ~/crux/gpu-fairuse.sh:
#   * checks every GPU in FAIRUSE_GPUS, not just one
#   * refuses a GPU that has ANY foreign compute process on it
#   * `check` is cheap enough to call between batches of a long job
#
#   ./gpu-fairuse2.sh check              # print GO/DEFER for each GPU; exit 0 iff all requested are GO
#   ./gpu-fairuse2.sh claim 0            # print export lines pinning GPU 0
#   ./gpu-fairuse2.sh run 0 -- ./job.sh  # check GPU 0, then run the command with it pinned
#
# Exit: 0 = GO, 1 = DEFER, 3 = cannot reach the box.
set -uo pipefail

GPU_ALIAS=${GPU_ALIAS:-hpc}
FAIRUSE_GPUS=${FAIRUSE_GPUS:-0,1}
CAP_GB=${FAIRUSE_VRAM_CAP_GB:-60}
MAX_UTIL=${FAIRUSE_MAX_GPU_UTIL:-85}
MIN_RAM_GB=${FAIRUSE_MIN_FREE_RAM_GB:-32}
MAX_LOAD_PCT=${FAIRUSE_MAX_LOAD_PER_CORE_PCT:-90}
ALLOW_FOREIGN=${FAIRUSE_ALLOW_FOREIGN_PROCS:-0}
SSH_OPTS=${SSH_OPTS:--T -o BatchMode=yes -o ConnectTimeout=15}

# Validate the subcommand BEFORE the ssh round-trip. Without this, every
# invocation - including a typo - pays for a full snapshot first and exits 3 on an
# unreachable box, so tests/unit/test_fairuse_contract.py could only assert the
# usage contract while the box happened to be up. The whole point of that test is
# to pin the interface without needing the box.
case "${1:-check}" in
  check|claim|run) ;;
  *) echo "usage: $0 {check|claim IDX|run IDX -- CMD}" >&2; exit 2 ;;
esac

snap=$(ssh $SSH_OPTS "$GPU_ALIAS" bash -s <<'REMOTE'
nvidia-smi --query-gpu=index,memory.total,memory.used,memory.free,utilization.gpu \
           --format=csv,noheader,nounits | tr -d ','
echo "@@PROCS"
nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits | tr -d ','
echo "@@UUIDS"
nvidia-smi --query-gpu=index,uuid --format=csv,noheader | tr -d ','
echo "@@HOST"
free -m | awk '/^Mem:/{print $7}'
cut -d' ' -f1 /proc/loadavg
nproc
REMOTE
) || { echo "fairuse: DEFER - cannot reach GPU box ($GPU_ALIAS)" >&2; exit 3; }

gpus_block=$(printf '%s\n' "$snap" | sed -n '1,/@@PROCS/p' | grep -v '@@')
procs_block=$(printf '%s\n' "$snap" | sed -n '/@@PROCS/,/@@UUIDS/p' | grep -v '@@')
uuids_block=$(printf '%s\n' "$snap" | sed -n '/@@UUIDS/,/@@HOST/p' | grep -v '@@')
host_block=$(printf '%s\n' "$snap" | sed -n '/@@HOST/,$p' | grep -v '@@')

ram=$(printf '%s\n' "$host_block" | sed -n 1p)
load1=$(printf '%s\n' "$host_block" | sed -n 2p)
ncpu=$(printf '%s\n' "$host_block" | sed -n 3p)
[[ "$ram" =~ ^[0-9]+$ && "$ncpu" =~ ^[0-9]+$ ]] \
  || { echo "fairuse: DEFER - unexpected query output" >&2; exit 3; }

loadpct=$(awk -v l="$load1" -v n="$ncpu" 'BEGIN{printf "%d",(l/n)*100}')
host_reasons=()
(( ram >= MIN_RAM_GB*1024 ))  || host_reasons+=("host RAM avail ${ram}MiB < ${MIN_RAM_GB}GB")
(( loadpct <= MAX_LOAD_PCT )) || host_reasons+=("host CPU load ${loadpct}%/core > ${MAX_LOAD_PCT}%")

uuid_of() { printf '%s\n' "$uuids_block" | awk -v i="$1" '$1==i{print $2}'; }

gpu_status() {  # $1 = index; echoes "GO"/"DEFER <reasons>"
  local idx="$1" total used free util reasons=() uuid nproc_foreign
  read -r _ total used free util <<<"$(printf '%s\n' "$gpus_block" | awk -v i="$idx" '$1==i')"
  [[ -n "${total:-}" ]] || { echo "DEFER GPU${idx} not present"; return; }
  uuid=$(uuid_of "$idx")
  nproc_foreign=$(printf '%s\n' "$procs_block" | awk -v u="$uuid" '$1==u' | grep -c . || true)
  (( free >= CAP_GB*1024 )) || reasons+=("free ${free}MiB < ${CAP_GB}GB")
  (( util <= MAX_UTIL ))    || reasons+=("util ${util}% > ${MAX_UTIL}%")
  if (( nproc_foreign > 0 && ALLOW_FOREIGN == 0 )); then
    reasons+=("${nproc_foreign} foreign compute process(es) present")
  fi
  reasons+=("${host_reasons[@]}")
  if (( ${#reasons[@]} )); then echo "DEFER GPU${idx}: $(IFS='; '; echo "${reasons[*]}")"
  else echo "GO GPU${idx}: ${free}MiB free, util ${util}%"; fi
}

cmd=${1:-check}; shift || true
case "$cmd" in
  check)
    rc=0
    IFS=',' read -ra want <<<"$FAIRUSE_GPUS"
    for i in "${want[@]}"; do
      s=$(gpu_status "$i"); echo "fairuse: $s" >&2
      [[ "$s" == GO* ]] || rc=1
    done
    exit $rc ;;
  claim|run)
    idx=${1:?need a GPU index}; shift || true
    s=$(gpu_status "$idx"); echo "fairuse: $s" >&2
    [[ "$s" == GO* ]] || exit 1
    read -r _ total _ _ _ <<<"$(printf '%s\n' "$gpus_block" | awk -v i="$idx" '$1==i')"
    util_frac=$(awk -v c="$CAP_GB" -v t="$total" 'BEGIN{printf "%.2f",(c*1024)/t}')
    uuid=$(uuid_of "$idx")
    if [[ "$cmd" == claim ]]; then
      printf "export GPU=%q CUDA_VISIBLE_DEVICES=%q CRUX_VRAM_CAP_GB=%q VLLM_GPU_MEMORY_UTILIZATION=%q\n" \
        "nvidia.com/gpu=${uuid}" "$idx" "$CAP_GB" "$util_frac"
      exit 0
    fi
    [[ "${1:-}" == "--" ]] && shift
    exec env GPU="nvidia.com/gpu=${uuid}" CUDA_VISIBLE_DEVICES="$idx" \
         CRUX_VRAM_CAP_GB="$CAP_GB" VLLM_GPU_MEMORY_UTILIZATION="$util_frac" "$@" ;;
  *) echo "usage: $0 {check|claim IDX|run IDX -- CMD}" >&2; exit 2 ;;
esac
