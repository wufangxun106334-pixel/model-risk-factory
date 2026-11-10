# Responsible AI note

Model Risk Factory · Challenge 04 · EXL × UCD Data & AI Hackathon 2026

## Data used

The prototype documents three team-built R models and migrates one credit-default scorecard. It uses the UCI Default of Credit Card Clients dataset (Taiwan, 2005, CC BY 4.0) and separate synthetic workflow data and boundary fixtures. The final UCI campaign reserves 1,199 independent Holdout rows. Competition permission for this specific dataset is tracked separately from its public licence.

## Privacy

Only allowlisted code, simulated notes, schemas and aggregate diagnostics are sent to the LLM. Raw data, row identifiers, labels, Holdout inputs and answers, and fixed tests stay local. API credentials stay in the local environment. A whitelist limits exported evidence to reviewed metadata and aggregate results. The public dataset has no direct identifiers and still contains demographic attributes.

## Bias

Age and sex are excluded from the model and used for group audits. We report TPR and FPR by age band and sex, compare with training-defined reference groups and flag small groups. A group below 30 labelled rows is marked LOW_SAMPLE. A rate with fewer than five records in its relevant class is unassessable. These rates are audit signals and cannot establish that the model is fair or legally compliant.

## Limitations

The Holdout is a same-period random sample. Weighted resampling measures sensitivity to changes in sample composition. The dataset lacks a cross-time back-test, and the small final Holdout limits subgroup conclusions. The sample does not represent a UK bank portfolio. Synthetic runs establish that the workflow operates. The project is a competition prototype and makes no claim of production suitability, independent validation or regulatory approval.

## Safeguards

Gate A reviews source-backed inventories. Gate B binds approval to the exact candidate before execution in a non-root, network-disabled Docker container with read-only inputs and resource limits. Gate C binds approval to the report, metrics, provenance and Agent interpretation. The Agent selects a review focus and returns structured facts that must match computed metrics. Trusted code renders the report language and numeric tables. A consumption ledger protects the Holdout. Review records identify the actual reviewer and distinguish delegated review. The historical synthetic demo replays earlier scripted approvals. The current drill pauses for review at each gate.

**Repository references** · Data and gates in the README and project SOP. Controls in `src/inventory.py`, `src/runner.py`, `src/report.py` and `src/evidence.py`.
