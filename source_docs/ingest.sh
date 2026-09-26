#!/usr/bin/env bash
# Upload the FL–GA border filings to a running GridLock with only the planned-transmission
# pages. Usage: bash source_docs/ingest.sh [api base, default http://localhost:8080/api]
# Download the PDFs first (see README.md in this folder).
set -euo pipefail
API="${1:-http://localhost:8080/api}"
DIR="$(cd "$(dirname "$0")" && pwd)"
PSC="https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026"

ingest() {  # file  utility  pages  source_url
  printf '%-44s pages %-16s -> ' "$1" "$3"
  curl -sS -f "$API/ingest" -F "file=@$DIR/$1" -F "utility=$2" -F "pages=$3" -F "source_url=$4"
  echo
}

# Georgia side: SERTP 2026 preliminary 10-year plan, Southern balancing area only
# (pages 27-102); per-project owners come from the SOCO:/GTC:/MEAG: prefixes.
ingest sertp_2026_preliminary_expansion_plan.pdf "SERTP Southern BAA" "27-102" \
  "https://www.southeasternrtp.com/docs/general/2026/2026_SERTP_Preliminary_Expansion_Plan_Report_(Non-CEII).pdf"
# Florida side: FRCC Form 13 "Proposed Transmission Lines" (all Florida utilities).
ingest frcc_2026_load_resource_plan.pdf "FRCC Load and Resource Plan" "62,85" "$PSC/FRCC_RLRP.pdf"
# Ten-Year Site Plans: Schedule 10 (proposed transmission lines) + transmission sections.
ingest duke_energy_florida_2026_tysp.pdf "Duke Energy Florida" "107-117" \
  "$PSC/Duke%20Energy%20Florida.pdf"
ingest fpl_2026_tysp.pdf "Florida Power & Light" "329-412,439-440" \
  "$PSC/Florida%20Power%20and%20Light%20Company.pdf"
ingest city_of_tallahassee_2026_tysp.pdf "City of Tallahassee" "47-49" \
  "$PSC/City%20of%20Tallahassee.pdf"
# JEA's 2026 TYSP reports no proposed transmission lines (Schedule 10: "None to Report").
