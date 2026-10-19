# Bloomberg IRS validation fixtures

- `source/` stores the complete Bloomberg JSON files copied byte-for-byte from the supplied archive. `source_manifest.json` records the source archive member and SHA-256 digest for each file.
- `cases/` stores trade inputs for each validation case, separated from valuation outputs. TC1 is the domain-facing canonical case and applies the confirmed 530,000 → 265,000 scale and the accrual/payment schedule established from its detailed cashflow data; its unmodified Bloomberg source remains in `source/TC1.json`.
- `references/` stores Bloomberg valuation and risk output sections, including detailed leg and net cashflows where supplied. TC1 retains its existing primary pricing metrics and includes the source's additional oracle sections.
- `market_data/<reference-date>/<currency>/market_data.json` stores dated Market Rate and Discount Factor observations separately from trade cases and Bloomberg references.
- TC1–TC10 source files are present. No missing trade terms, market observations, or Bloomberg values are inferred.
- Projection-rate methodology is intentionally outside this fixture contract. The fixtures preserve observations; they do not prescribe a transformation into a QuantLib projection term structure.
