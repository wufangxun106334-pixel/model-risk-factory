# Credit V2 legacy model note

This is simulated legacy documentation created for the model-risk factory exercise.
It intentionally mirrors a partially migrated handover note: some facts exist,
others were never written down.

- Model ID: MDL_CREDIT_V2
- Model type: Logistic regression for credit default probability
- Decision threshold: 0.30
- Classification rule: class 1 when the predicted probability is at least 0.30

The model extends the first-generation scorecard with a longer repayment
history. Features recorded in this note are: recent repayment delay, second and
third month repayment status are summarised operationally in the workbook that
was lost with the previous owner, credit limit, current utilisation, the
six-month average utilisation and the most recent payment amount.

Input constraints were never written down. The scoring workbook was rebuilt by
an engineer who has since left the team, and the validation appendix referenced
by the old approval memo is missing. No owner, no training date and no
hyperparameter sheet are available for this model.

Operational note: the production run used a monthly refresh, but the actual
refresh evidence and the population it was validated on are unavailable.
