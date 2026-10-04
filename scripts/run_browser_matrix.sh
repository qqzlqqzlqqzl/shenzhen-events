#!/usr/bin/env bash
# All 20 suites are required. Continue after failures, then fail the aggregate.
set -uo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$ROOT"
python="${RADAR_TEST_PYTHON:-$ROOT/.venv/bin/python}"
out="$ROOT/artifacts/ci"
limit="${RADAR_BROWSER_SUITE_TIMEOUT:-180}"
if [[ ! "$limit" =~ ^[1-9][0-9]*$ ]]; then
  printf 'Invalid positive suite timeout: %s\n' "$limit" >&2
  exit 64
fi
mkdir -p -- "$out"
summary="$out/browser-matrix.tsv"
if [[ -e "$summary" ]]; then
  printf 'Refusing to overwrite prior browser matrix: %s\n' "$summary" >&2
  exit 73
fi
suites=(
  taxonomy_browser multiday_browser calendar_browser review_district_browser
  review_filter_context_browser review_personal_browser review_feedback_state_browser
  review_planning_browser review_decisions_browser review_session_boundary_browser
  review_recovery_browser feedback_browser review_browser coverage_browser
  refresh_races_browser storage_resilience_browser owner_navigation_browser
  readability_browser mobile_overlays_browser eefocus_safety_browser
)
printf 'suite\tstatus\texit_code\n' > "$summary"
result=0
for suite in "${suites[@]}"; do
  logfile="$out/$suite.log"
  if [[ -e "$logfile" ]]; then
    printf 'Refusing to overwrite prior suite log: %s\n' "$logfile" >&2
    printf '%s\tblocked-existing-log\t73\n' "$suite" >> "$summary"
    result=1
    continue
  fi
  if [[ ! -f "tests/$suite.py" ]]; then
    printf 'Required browser suite is missing: tests/%s.py\n' "$suite" | tee "$logfile"
    printf '%s\tfailed-missing-suite\t66\n' "$suite" >> "$summary"
    result=1
    continue
  fi
  timeout --signal=TERM --kill-after=5s "${limit}s" "$python" "tests/$suite.py" 2>&1 | tee "$logfile"
  codes=("${PIPESTATUS[@]}")
  rc="${codes[0]}"
  if [[ "$rc" -eq 0 && "${codes[1]}" -eq 0 ]]; then
    printf '%s\tpassed\t0\n' "$suite" >> "$summary"
  else
    [[ "$rc" -ne 0 ]] || rc="${codes[1]}"
    printf '%s\tfailed\t%s\n' "$suite" "$rc" >> "$summary"
    result=1
  fi
done
exit "$result"
