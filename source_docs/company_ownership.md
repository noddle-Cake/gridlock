# Company ownership in collision matching

Collision flags compare different corporate families. The reference pair is
Dominion Energy South Carolina (Dominion Energy) and Georgia Power (Southern
Company): they do not share a parent. Sister companies under one parent are
excluded, even when they are separate LLCs or regulated operating companies.
Passing the ownership check still requires meeting the distance and timing rules.
The archived 2024–2028 reference dates fail current timing rules. The refreshed
2026–2030 DESC filing produces eight future matches with Georgia Power as of
September 27, 2026. See [the audit](current_collision_audit.md).

`backend/app/services/owners.py` applies this policy when pairs are read, including
existing data, exports, project details, brief requests, and rematching after edits.
Project company names remain as filed. No data reload is necessary.

- Names are canonicalized before comparison, including case, corporate suffixes,
  and known abbreviations such as FPL, FRP, DESC, and DEF.
- FRP solar project LLCs (including the snapshot's FRP Forest Trail Solar and FRP
  Miller Solar), Florida Renewable Partners, FPL, and NextEra Energy Resources
  belong to the NextEra family for matching.
- Southern Company and its Georgia Power, Alabama Power, Mississippi Power, and
  Southern Power subsidiaries belong to one family.
- Duke Energy's listed operating subsidiaries belong to one family.
- Dominion SC and SCANA belong to Dominion Energy. Announced mergers are not
  treated as completed ownership changes.
- Joint owners are compared individually: DEF/SEC cannot match either DEF or SEC,
  or another joint owner combination sharing either company.
- Missing/unknown company names cannot establish a different-company match.
  Every company in the Sperry region (SC, GA, FL) has an explicit decision in
  `backend/app/data/company_ownership.csv`. Rows marked `review` are withheld, including
  joint owners if any member is withheld. Extraction review does not override this.
- Companies not in the registry (most of EIA-860M's nationwide project companies) may
  match, and the project carries `ownership_review_required`, shown as **ownership
  unverified** on the pair. Pairs whose names read as one developer's projects are not
  flagged: equal once phase, technology and numbering words are dropped ("Atlas Solar IV" /
  "Atlas BESS IV", "Lazy U Solar 1" / "Lazy U ESS 2"), one name leading the other
  ("Bridgewater Solar" / "Bridgewater Solar 2"), or the same distinctive first word
  ("Evergy Kansas Central" / "Evergy Missouri West"). Address-named LLCs of a larger
  owner can still slip through until the registry covers them.
- energyRe project companies, Silicon Ranch Bacon/Cordova/Georgetown companies, and
  Ingka Kingstree companies are grouped by their documented owners. The CSV carries
  evidence links. Buyers, balancing authorities, and common fund managers alone
  do not establish common ownership.
- Cooperative membership alone does not establish a common controlling parent.
  Georgia Transmission and Oglethorpe remain separate from Southern Company.
- The review table displays `ownership unverified`; to resolve it, add a sourced
  corporate family to the registry and redeploy. New uploads are subject to the same rule.

Ownership references (checked September 26, 2026):

- [Dominion Energy operating segments](https://www.dominionenergy.com/en/About/Our-Company/Operating-Segments)
- [Georgia Power company filings](https://www.georgiapower.com/about/company/filings.html)
- [Southern Company 2026 second-quarter filing](https://www.sec.gov/Archives/edgar/data/3153/000009212226000054/so-20260630.htm)
- [FRP company description at the Florida Municipal Electric Association](https://www.flpublicpower.com/sponsors/florida-renewable-partners-llc)
  explicitly describes FPL and NextEra Energy Resources as sister companies.
- [NextEra financial policy](https://www.investor.nexteraenergy.com/fixed-income-investors/financial-policy)
- [USDA FRP Tupelo Solar environmental assessment](https://www.rd.usda.gov/media/file/download/usda-rd-ea-florida-renewable-partners-frp-tupelo-solar-03012024.pdf)
- [Duke Energy 2025 annual filing](https://www.sec.gov/Archives/edgar/data/17797/000132616026000014/duk-20251231.htm)
- [Dominion Energy 2026 second-quarter filing](https://www.sec.gov/Archives/edgar/data/91882/000119312526327497/ck0000091882-20260630.htm)
