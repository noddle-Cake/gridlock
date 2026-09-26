# Source filings (FL–GA border)

Public filings with planned transmission projects near the Florida–Georgia border. The
PDFs are git-ignored; download them, then upload with `ingest.sh` (only the listed pages
are extracted, and page numbers still match the original PDF for source links).

| File | Source | Pages | Content |
| --- | --- | --- | --- |
| `sertp_2026_preliminary_expansion_plan.pdf` | [SERTP 2026 Preliminary Expansion Plan Report (Non-CEII)](https://www.southeasternrtp.com/docs/general/2026/2026_SERTP_Preliminary_Expansion_Plan_Report_(Non-CEII).pdf) | 27-102 | Southern balancing area: ~288 projects (SOCO 204, GTC 67, MEAG 12, PowerSouth 4, Dalton 1). Page headers read "(CEII)"; this is the file SERTP publishes as Non-CEII. |
| `frcc_2026_load_resource_plan.pdf` | [FRCC 2026 Load & Resource Plan](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/FRCC_RLRP.pdf) | 62, 85 | Form 13 "Proposed Transmission Lines", every Florida utility. "Classification: Public". |
| `duke_energy_florida_2026_tysp.pdf` | [Duke Energy Florida 2026 TYSP](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/Duke%20Energy%20Florida.pdf) | 107-117 | Schedule 10 (201-211 repeats it; skipped). |
| `fpl_2026_tysp.pdf` | [FPL 2026 TYSP](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/Florida%20Power%20and%20Light%20Company.pdf) | 329-412, 439-440 | Schedule 10 (solar-site lines, statewide) + transmission narrative. 29 MB. |
| `city_of_tallahassee_2026_tysp.pdf` | [City of Tallahassee 2026 TYSP](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/City%20of%20Tallahassee.pdf) | 47-49 | Table 4.2 Planned Transmission Projects. |

Not ingested: JEA's 2026 TYSP (Schedule 10: "None to Report"; its transmission chapter
describes only existing facilities).

```bash
cd source_docs
PSC=https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026
curl -fLo sertp_2026_preliminary_expansion_plan.pdf "https://www.southeasternrtp.com/docs/general/2026/2026_SERTP_Preliminary_Expansion_Plan_Report_(Non-CEII).pdf"
curl -fLo frcc_2026_load_resource_plan.pdf "$PSC/FRCC_RLRP.pdf"
curl -fLo duke_energy_florida_2026_tysp.pdf "$PSC/Duke%20Energy%20Florida.pdf"
curl -fLo fpl_2026_tysp.pdf "$PSC/Florida%20Power%20and%20Light%20Company.pdf"
curl -fLo city_of_tallahassee_2026_tysp.pdf "$PSC/City%20of%20Tallahassee.pdf"
cd .. && bash source_docs/ingest.sh            # or pass another API base URL
```

**Gemini quota:** these pages are ~17 model requests. The free tier allows 5 requests per
minute (the app paces to `GEMINI_RPM`) and 20 per day per model; a failed plan can simply
be uploaded again once the quota resets.
