# UCI data use for Challenge 04: basis in the official rules

Recorded 2026-11-12 by team member A (fangxunwu, 25208508). Closes hand-off item H-01 (`docs/v3/08_handoff.md`).

## What the official programme document says

Source: [EXL_UCD_Data_AI_Hackathon_2026.pdf](EXL_UCD_Data_AI_Hackathon_2026.pdf) (official programme proposal, October 2026).

Challenge 04 page (p. 9), "STARTER DATA & TOOLS" and footnote, verbatim:

> Public credit-risk datasets (for example on Kaggle) and EXL sample model code (to be confirmed). Azure ML and MLflow preferred.
>
> Proposed challenge, subject to EXL confirmation. Client context is illustrative; students work with public or synthetic data only.

FAQ, verbatim:

> Q Will we get real client data?
> No. Challenges reflect real client problems but use public or synthetic data only. Never upload personal data.

## The dataset we use

| Item | Value |
| --- | --- |
| Dataset | UCI Machine Learning Repository, *Default of Credit Card Clients* (ID 350) |
| Landing page | https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients |
| Licence | CC BY 4.0 (redistribution and adaptation allowed with attribution) |
| Citation | Yeh, I-C. & Lien, C-H. (2009). *Expert Systems with Applications*, 36(2). |
| Raw ZIP SHA-256 | `56c885f84457f6680f8438f02bfcdac9579323d8a94465ee5f26e32baa727602` (also in `config/holdout_ledger.json`) |
| Personal data | No direct identifiers; contains sex, age, education and marriage, used only for fairness auditing and never as model inputs |

## Team decision

- The rules require **public or synthetic data** and name **public credit-risk datasets (for example on Kaggle)** as starter data. They do not name a single mandatory dataset. The UCI dataset is a public credit-risk dataset under CC BY 4.0, so using it complies with the official rules.
- This record is based on the published rules. **It is not a separate e-mail from the organisers.** If the organisers give contrary guidance, it overrides this record and the formal result must be re-labelled.
- Consequence: `config/data_config.json` sets `uci_competition_use_approved=true`. Every formal run still needs the operator's explicit `--approve-uci-use` and the hash check above.
- The raw file stays out of Git. The download step verifies the SHA-256, and the README carries the attribution.
