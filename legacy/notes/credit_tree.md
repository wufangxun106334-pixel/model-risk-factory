# Credit Tree legacy model note

This is simulated legacy documentation created for the model-risk factory exercise.
The original design document was replaced by a one-page summary during a tooling
migration, so several facts are unrecorded.

- Model ID: MDL_CREDIT_TREE
- Model type: Shallow classification tree for credit default
- Decision threshold: 0.50
- Classification rule: class 1 when the leaf probability is at least 0.50

Inputs described in this summary are credit limit, current utilisation and the
three most recent repayment-status fields. The summary does not state how the
repayment-status codes were pre-processed before the split search.

Tree depth was tuned during the pilot and the tuning record was not retained;
the summary does not record the maximum depth, the minimum split size, the
complexity parameter or any variable-importance table. The tree was described in
review as "interpretable and therefore low risk", which is an opinion rather
than a recorded control.

No owner and no training date appear in this summary. Population stability for
this model was never measured.
