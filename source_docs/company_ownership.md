# Company ownership in collision matching

Collision flags compare different corporate families. The reference pair is
Dominion Energy South Carolina (Dominion Energy) and Georgia Power (Southern
Company): they do not share a parent. Sister companies under one parent are
excluded, even when they are separate LLCs or regulated operating companies.

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
  Unmapped named companies use their canonical name. This is a curated ownership
  registry, not exhaustive ownership verification for all EIA project LLCs; add
  documented relationships here and to the registry when new ones are identified.

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
