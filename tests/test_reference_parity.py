from __future__ import annotations

import copy
import csv
import json
import math
import tempfile
import unittest
from pathlib import Path

from src import fixtures, parity, reference


MODEL = {
    "schema_version": "1",
    "model_id": "MDL_CREDIT_V1",
    "coefficients": {
        "intercept": -0.7,
        "delay_1": 0.2,
        "log_limit": -0.05,
        "util_1": 0.4,
        "log_pay_1": 0.03,
    },
    "feature_order": ["delay_1", "log_limit", "util_1", "log_pay_1"],
    "medians": {
        "limit_bal": 1000.0,
        "pay_status_1": 0.0,
        "bill_amt_1": 250.0,
        "pay_amt_1": 40.0,
    },
    "threshold": 0.35,
}


def raw_row(client_id: str = "c1", **changes):
    row = {
        "client_id": client_id,
        "limit_bal": "1000",
        "pay_status_1": "1",
        "bill_amt_1": "250",
        "pay_amt_1": "40",
    }
    row.update(changes)
    return row


def output_row(client_id: str = "c1", **changes):
    row = {
        "client_id": client_id,
        "probability": "0.20000000000000001",
        "classification": "0",
        "status": "VALID",
        "error_code": "",
        "limit_bal_imputed": "0",
        "pay_status_1_imputed": "0",
        "bill_amt_1_imputed": "0",
        "pay_amt_1_imputed": "0",
    }
    row.update(changes)
    return row


def rejected_row(client_id: str = "r1", **changes):
    row = output_row(
        client_id,
        probability="",
        classification="",
        status="REJECTED",
        error_code="INVALID_LIMIT_BAL",
    )
    row.update(changes)
    return row


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames or reference.OUTPUT_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class ReferenceTests(unittest.TestCase):
    def test_probability_classification_and_feature_order(self):
        result = reference.predict_rows(copy.deepcopy(MODEL), [raw_row()])[0]
        eta = (
            -0.7
            + 0.2 * 1.0
            - 0.05 * math.log1p(1000.0)
            + 0.4 * 0.25
            + 0.03 * math.log1p(40.0)
        )
        expected = 1.0 / (1.0 + math.exp(-eta))
        self.assertEqual(result["probability"], format(expected, ".17g"))
        self.assertEqual(result["classification"], "1" if expected >= 0.35 else "0")
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(list(result), reference.OUTPUT_COLUMNS)

    def test_threshold_equality_is_class_one(self):
        model = copy.deepcopy(MODEL)
        model["coefficients"] = {
            "intercept": math.log(0.35 / 0.65),
            "delay_1": 0.0,
            "log_limit": 0.0,
            "util_1": 0.0,
            "log_pay_1": 0.0,
        }
        result = reference.predict_rows(model, [raw_row()])[0]
        self.assertAlmostEqual(float(result["probability"]), 0.35, places=15)
        self.assertEqual(result["classification"], "1")

    def test_missing_values_use_medians_and_set_each_flag(self):
        row = raw_row(limit_bal="", pay_status_1="", bill_amt_1="", pay_amt_1="")
        result = reference.predict_rows(copy.deepcopy(MODEL), [row])[0]
        expected_eta = (
            -0.7
            - 0.05 * math.log1p(1000.0)
            + 0.4 * 0.25
            + 0.03 * math.log1p(40.0)
        )
        self.assertEqual(
            result["probability"], format(1 / (1 + math.exp(-expected_eta)), ".17g")
        )
        for field in reference.RAW_FIELDS:
            self.assertEqual(result[f"{field}_imputed"], "1")

    def test_fractional_training_median_for_pay_status_is_allowed(self):
        model = copy.deepcopy(MODEL)
        model["medians"]["pay_status_1"] = -0.5
        result = reference.predict_rows(model, [raw_row(pay_status_1="")])[0]
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["pay_status_1_imputed"], "1")

    def test_invalid_values_are_rejected_and_negative_bill_is_legal(self):
        rows = [
            raw_row("negative-bill", bill_amt_1="-100"),
            raw_row("bad-limit", limit_bal="0"),
            raw_row("bad-status-range", pay_status_1="10"),
            raw_row("bad-status-fraction", pay_status_1="1.5"),
            raw_row("bad-pay", pay_amt_1="-0.01"),
            raw_row("bad-bill-text", bill_amt_1="not-a-number"),
            raw_row("bad-limit-text", limit_bal="many"),
        ]
        results = reference.predict_rows(copy.deepcopy(MODEL), rows)
        self.assertEqual(results[0]["status"], "VALID")
        self.assertEqual(results[0]["error_code"], "")
        expected_codes = [
            "INVALID_LIMIT_BAL",
            "INVALID_PAY_STATUS_1",
            "INVALID_PAY_STATUS_1",
            "INVALID_PAY_AMT_1",
            "INVALID_BILL_AMT_1",
            "INVALID_LIMIT_BAL",
        ]
        for result, code in zip(results[1:], expected_codes, strict=True):
            self.assertEqual(result["status"], "REJECTED")
            self.assertEqual(result["error_code"], code)
            self.assertEqual(result["probability"], "")
            self.assertEqual(result["classification"], "")
            self.assertTrue(all(result[f"{field}_imputed"] == "0" for field in reference.RAW_FIELDS))

    def test_nan_and_infinity_are_invalid_not_missing(self):
        rows = [
            raw_row("nan", limit_bal="NaN"),
            raw_row("infinity", pay_amt_1="Infinity"),
            raw_row("nan-number", limit_bal=float("nan")),
        ]
        results = reference.predict_rows(copy.deepcopy(MODEL), rows)
        self.assertEqual([row["error_code"] for row in results], [
            "INVALID_LIMIT_BAL",
            "INVALID_PAY_AMT_1",
            "INVALID_LIMIT_BAL",
        ])
        self.assertTrue(all(row["limit_bal_imputed"] == "0" for row in results))

    def test_rejected_row_still_imputes_other_missing_fields(self):
        row = raw_row(limit_bal="-1", bill_amt_1="")
        result = reference.predict_rows(copy.deepcopy(MODEL), [row])[0]
        self.assertEqual(result["error_code"], "INVALID_LIMIT_BAL")
        self.assertEqual(result["bill_amt_1_imputed"], "1")

    def test_in_memory_structure_errors(self):
        with self.assertRaises(reference.InputContractError):
            reference.predict_rows(copy.deepcopy(MODEL), [])
        with self.assertRaises(reference.InputContractError):
            reference.predict_rows(copy.deepcopy(MODEL), [raw_row("same"), raw_row("same")])
        missing = raw_row()
        del missing["bill_amt_1"]
        with self.assertRaises(reference.InputContractError):
            reference.predict_rows(copy.deepcopy(MODEL), [missing])
        model = copy.deepcopy(MODEL)
        del model["medians"]["limit_bal"]
        with self.assertRaises(reference.InputContractError):
            reference.predict_rows(model, [raw_row()])

    def test_predict_file_accepts_reordered_input_columns_and_writes_exact_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = root / "model.json"
            input_path = root / "input.csv"
            output_path = root / "predictions.csv"
            model_path.write_text(json.dumps(MODEL), encoding="utf-8")
            reordered = ["pay_amt_1", "client_id", "bill_amt_1", "limit_bal", "pay_status_1"]
            write_csv(input_path, [raw_row()], reordered)
            returned = reference.predict_file(model_path, input_path, output_path)
            self.assertEqual(reference.main([str(model_path), str(input_path), str(output_path)]), 0)
            with output_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, reference.OUTPUT_COLUMNS)
                written = list(reader)
            self.assertEqual(written, returned)

    def test_predict_file_rejects_missing_column_empty_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = root / "model.json"
            model_path.write_text(json.dumps(MODEL), encoding="utf-8")
            cases = {
                "missing": ([raw_row()], ["client_id", "limit_bal", "pay_status_1", "pay_amt_1"]),
                "empty": ([], reference.INPUT_COLUMNS),
                "duplicate": ([raw_row("same"), raw_row("same")], reference.INPUT_COLUMNS),
            }
            for name, (rows, columns) in cases.items():
                with self.subTest(name=name):
                    input_path = root / f"{name}.csv"
                    write_csv(input_path, rows, columns)
                    with self.assertRaises(reference.InputContractError):
                        reference.predict_file(model_path, input_path, root / f"{name}-out.csv")


class ParityTests(unittest.TestCase):
    def compare(self, root: Path, baseline_rows: list[dict], candidate_rows: list[dict], **kwargs):
        baseline_path = root / "baseline.csv"
        candidate_path = root / "candidate.csv"
        summary_path = root / "summary.json"
        diff_path = root / "diff.csv"
        write_csv(baseline_path, baseline_rows)
        write_csv(candidate_path, candidate_rows)
        summary = parity.compare_files(
            baseline_path, candidate_path, summary_path, diff_path, **kwargs
        )
        self.assertEqual(summary, json.loads(summary_path.read_text(encoding="utf-8")))
        return summary, read_csv(diff_path)

    def test_reordered_rows_pass_and_ids_are_aligned(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline = [output_row("a"), rejected_row("b")]
            summary, differences = self.compare(Path(directory), baseline, list(reversed(baseline)))
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["n"], 2)
            self.assertFalse(summary["id_order_match"])
            self.assertTrue(summary["id_sets_match"])
            self.assertEqual(differences, [])

    def test_reordered_output_columns_fail_strict_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_path = root / "baseline.csv"
            candidate_path = root / "candidate.csv"
            reordered = [reference.OUTPUT_COLUMNS[0], *reversed(reference.OUTPUT_COLUMNS[1:])]
            write_csv(baseline_path, [output_row()])
            write_csv(candidate_path, [output_row()], reordered)
            summary = parity.compare_files(
                baseline_path, candidate_path, root / "summary.json", root / "diff.csv"
            )
            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("CANDIDATE_SCHEMA_MISMATCH", summary["reasons"])

    def test_missing_column_fails_with_diff_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_path = root / "baseline.csv"
            candidate_path = root / "candidate.csv"
            columns = [name for name in reference.OUTPUT_COLUMNS if name != "error_code"]
            write_csv(baseline_path, [output_row()])
            write_csv(candidate_path, [output_row()], columns)
            summary = parity.compare_files(
                baseline_path, candidate_path, root / "summary.json", root / "diff.csv"
            )
            differences = read_csv(root / "diff.csv")
            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("CANDIDATE_SCHEMA_MISMATCH", summary["reasons"])
            self.assertTrue(any(row["field"] == "schema" for row in differences))

    def test_duplicate_ids_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            duplicate = [output_row("same"), output_row("same"), rejected_row("other")]
            summary, differences = self.compare(
                Path(directory), [output_row("a"), rejected_row("b")], duplicate
            )
            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("CANDIDATE_DUPLICATE_ID", summary["reasons"])
            self.assertFalse(summary["candidate_id_unique"])
            self.assertTrue(any(row["reason"] == "CANDIDATE_DUPLICATE_ID" for row in differences))

    def test_nan_probability_fails_and_is_not_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = [output_row("a", probability="NaN"), rejected_row("b")]
            summary, differences = self.compare(
                Path(directory), [output_row("a"), rejected_row("b")], candidate
            )
            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("CANDIDATE_INVALID_PROBABILITY", summary["reasons"])
            self.assertTrue(any(row["field"] == "probability" for row in differences))
            self.assertIsNone(summary["max_abs_diff"])

    def test_fewer_and_more_rows_fail_with_row_differences(self):
        baseline = [output_row("a"), output_row("b", probability="0.8", classification="1")]
        cases = {
            "fewer": baseline[:1],
            "more": [*baseline, rejected_row("extra")],
        }
        for name, candidate in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                summary, differences = self.compare(Path(directory), baseline, candidate)
                self.assertEqual(summary["status"], "FAIL")
                self.assertIn("ROW_COUNT_MISMATCH", summary["reasons"])
                self.assertIn("ID_SET_MISMATCH", summary["reasons"])
                self.assertTrue(any(row["field"] == "__row__" for row in differences))

    def test_trusted_input_ids_match_both_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "trusted.csv"
            write_csv(input_path, [raw_row("b"), raw_row("a")], reference.INPUT_COLUMNS)
            outputs = [output_row("a"), output_row("b", probability="0.8", classification="1")]
            summary, differences = self.compare(root, outputs, outputs, input_path=input_path)
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["input_row_count"], 2)
            self.assertTrue(summary["input_id_unique"])
            self.assertTrue(summary["input_baseline_ids_match"])
            self.assertTrue(summary["input_candidate_ids_match"])
            self.assertTrue(summary["input_ids_match"])
            self.assertEqual(differences, [])

    def test_trusted_input_with_fewer_rows_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "trusted.csv"
            write_csv(input_path, [raw_row("a")], reference.INPUT_COLUMNS)
            outputs = [output_row("a"), output_row("b", probability="0.8", classification="1")]
            summary, differences = self.compare(root, outputs, outputs, input_path=input_path)
            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["input_row_count"], 1)
            self.assertFalse(summary["input_ids_match"])
            self.assertIn("INPUT_BASELINE_ROW_COUNT_MISMATCH", summary["reasons"])
            self.assertIn("INPUT_CANDIDATE_ROW_COUNT_MISMATCH", summary["reasons"])
            self.assertTrue(any(row["reason"] == "BASELINE_ID_MISSING_FROM_INPUT" for row in differences))
            self.assertTrue(any(row["reason"] == "CANDIDATE_ID_MISSING_FROM_INPUT" for row in differences))

    def test_outputs_jointly_missing_trusted_input_row_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "trusted.csv"
            write_csv(input_path, [raw_row("a"), raw_row("b")], reference.INPUT_COLUMNS)
            jointly_incomplete = [output_row("a")]
            summary, differences = self.compare(
                root, jointly_incomplete, jointly_incomplete, input_path=input_path
            )
            self.assertEqual(summary["status"], "FAIL")
            self.assertTrue(summary["id_sets_match"])
            self.assertFalse(summary["input_baseline_ids_match"])
            self.assertFalse(summary["input_candidate_ids_match"])
            self.assertFalse(summary["input_ids_match"])
            self.assertIn("INPUT_ID_SET_MISMATCH", summary["reasons"])
            self.assertTrue(any(row["reason"] == "INPUT_ID_MISSING_FROM_BASELINE" for row in differences))
            self.assertTrue(any(row["reason"] == "INPUT_ID_MISSING_FROM_CANDIDATE" for row in differences))

    def test_trusted_input_duplicate_and_empty_ids_fail(self):
        cases = {
            "duplicate": ([raw_row("a"), raw_row("a")], [output_row("a")], "INPUT_DUPLICATE_ID"),
            "empty": ([raw_row("a"), raw_row("")], [output_row("a")], "INPUT_EMPTY_CLIENT_ID"),
        }
        for name, (input_rows, output_rows, reason) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                input_path = root / "trusted.csv"
                write_csv(input_path, input_rows, reference.INPUT_COLUMNS)
                summary, _ = self.compare(root, output_rows, output_rows, input_path=input_path)
                self.assertEqual(summary["status"], "FAIL")
                self.assertFalse(summary["input_id_unique"] if name == "duplicate" else summary["input_ids_nonempty"])
                self.assertIn(reason, summary["reasons"])

    def test_probability_tolerances_and_classification_mismatch(self):
        baseline = [output_row("a"), rejected_row("r")]
        with tempfile.TemporaryDirectory() as directory:
            within = [output_row("a", probability="0.20000000005"), rejected_row("r")]
            summary, _ = self.compare(Path(directory), baseline, within)
            self.assertEqual(summary["status"], "PASS")
            self.assertLessEqual(summary["max_abs_diff"], 1e-8)
        with tempfile.TemporaryDirectory() as directory:
            outside = [output_row("a", probability="0.20000002"), rejected_row("r")]
            summary, differences = self.compare(Path(directory), baseline, outside)
            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("MAX_ABS_DIFF_EXCEEDED", summary["reasons"])
            self.assertTrue(any(row["reason"] == "PROBABILITY_DIFF_EXCEEDS_MAX" for row in differences))
        with tempfile.TemporaryDirectory() as directory:
            wrong_class = [output_row("a", classification="1"), rejected_row("r")]
            summary, _ = self.compare(Path(directory), baseline, wrong_class)
            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["classification_mismatch_count"], 1)
            self.assertIn("CANDIDATE_THRESHOLD_CLASSIFICATION_ERROR", summary["reasons"])

    def test_mean_absolute_difference_limit_is_enforced(self):
        baseline = [output_row("a"), output_row("b", probability="0.4")]
        candidate = [
            output_row("a", probability="0.200000001"),
            output_row("b", probability="0.400000001"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            summary, _ = self.compare(Path(directory), baseline, candidate, mean_abs_diff=1e-12)
            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("MEAN_ABS_DIFF_EXCEEDED", summary["reasons"])

    def test_behaviour_flags_status_and_error_code_must_match(self):
        baseline = [output_row("a"), rejected_row("r")]
        candidate = [
            output_row("a", bill_amt_1_imputed="1"),
            rejected_row("r", error_code="INVALID_PAY_AMT_1"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            summary, differences = self.compare(Path(directory), baseline, candidate)
            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["behaviour_mismatch_count"], 2)
            self.assertTrue(any(row["field"] == "bill_amt_1_imputed" for row in differences))
            self.assertTrue(any(row["field"] == "error_code" for row in differences))

    def test_rejected_only_files_do_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            summary, _ = self.compare(Path(directory), [rejected_row()], [rejected_row()])
            self.assertEqual(summary["status"], "FAIL")
            self.assertIn("NO_VALID_RECORD_PAIRS", summary["reasons"])

    def test_isolated_single_coefficient_change_is_detected(self):
        rows = [raw_row("a"), raw_row("b", limit_bal="2000", bill_amt_1="3000")]
        baseline_rows = reference.predict_rows(copy.deepcopy(MODEL), rows)
        changed_model = copy.deepcopy(MODEL)
        changed_model["coefficients"]["log_limit"] += 0.001
        candidate_rows = reference.predict_rows(changed_model, rows)
        with tempfile.TemporaryDirectory() as directory:
            summary, differences = self.compare(Path(directory), baseline_rows, candidate_rows)
            self.assertEqual(summary["status"], "FAIL")
            self.assertGreater(summary["max_abs_diff"], 1e-8)
            self.assertIn("MAX_ABS_DIFF_EXCEEDED", summary["reasons"])
            self.assertTrue(any(row["field"] == "probability" for row in differences))

    def test_cli_exit_codes_and_execution_error_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_path = root / "baseline.csv"
            candidate_path = root / "candidate.csv"
            summary_path = root / "summary.json"
            diff_path = root / "diff.csv"
            rows = [output_row("a"), rejected_row("r")]
            write_csv(baseline_path, rows)
            write_csv(candidate_path, rows)
            arguments = [str(baseline_path), str(candidate_path), str(summary_path), str(diff_path)]
            self.assertEqual(parity.main(arguments), 0)
            write_csv(candidate_path, [output_row("a", probability="NaN"), rejected_row("r")])
            self.assertEqual(parity.main(arguments), 1)
            missing_arguments = [str(root / "missing.csv"), str(candidate_path), str(summary_path), str(diff_path)]
            self.assertEqual(parity.main(missing_arguments), 2)
            self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8"))["status"], "FAIL")
            self.assertTrue(diff_path.exists())


if __name__ == "__main__":
    unittest.main()
