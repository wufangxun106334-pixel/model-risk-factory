#!/usr/bin/env Rscript
# MDL_CREDIT_V2 - simulated legacy credit-default model (logistic regression).
# Deliberately older and less disciplined than credit_v1.R: it fits on more
# repayment-history fields and never documented its input constraints.

MODEL_ID <- "MDL_CREDIT_V2"
FEATURE_ORDER <- c("delay_1", "delay_2", "delay_3", "log_limit", "util_1", "util_mean_6", "log_pay_1")
RAW_FIELDS <- c("limit_bal", "pay_status_1", "pay_status_2", "pay_status_3",
                "bill_amt_1", "bill_amt_2", "bill_amt_3", "bill_amt_4", "bill_amt_5", "bill_amt_6",
                "pay_amt_1")
OUTPUT_COLUMNS <- c("client_id", "probability", "classification")
THRESHOLD <- 0.30

json_string <- function(value) {
  chars <- strsplit(enc2utf8(as.character(value)), "", fixed = TRUE)[[1L]]
  escaped <- vapply(chars, function(char) {
    code <- utf8ToInt(char)
    if (char == "\\") return("\\\\")
    if (char == "\"") return("\\\"")
    if (char == "\n") return("\\n")
    if (char == "\r") return("\\r")
    if (char == "\t") return("\\t")
    if (code < 32L) return(sprintf("\\u%04x", code))
    char
  }, character(1L), USE.NAMES = FALSE)
  paste0("\"", paste0(escaped, collapse = ""), "\"")
}

json_number <- function(value) {
  if (length(value) != 1L || !is.finite(value)) stop("Cannot serialize a non-finite JSON number")
  sprintf("%.17g", value)
}

json_array <- function(values) paste0("[", paste0(vapply(values, json_string, character(1L)), collapse = ","), "]")

json_object <- function(entries) {
  keys <- vapply(names(entries), json_string, character(1L))
  paste0("{", paste0(keys, ":", unlist(entries, use.names = FALSE), collapse = ","), "}")
}

contract_stop <- function(message) stop(message, call. = FALSE)

read_input <- function(path) {
  if (!file.exists(path) || file.info(path)$isdir) contract_stop(paste("Input file does not exist:", path))
  data <- tryCatch(
    read.csv(path, colClasses = "character", na.strings = character(),
             check.names = FALSE, stringsAsFactors = FALSE, blank.lines.skip = FALSE),
    error = function(error) contract_stop(conditionMessage(error))
  )
  required <- c("client_id", RAW_FIELDS, "default_flag")
  missing_columns <- setdiff(required, names(data))
  if (length(missing_columns) > 0L) {
    contract_stop(paste("Missing required columns:", paste(missing_columns, collapse = ",")))
  }
  if (nrow(data) == 0L) contract_stop("Input file has no data rows")
  if (anyDuplicated(data$client_id)) contract_stop("client_id values must be unique")
  data
}

numeric_column <- function(values) {
  missing <- is.na(values) | trimws(values) == ""
  parsed <- suppressWarnings(as.numeric(trimws(values)))
  parsed[missing] <- NA_real_
  parsed
}

fit_and_write <- function(train_path, output_dir) {
  train <- read_input(train_path)
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  columns <- lapply(RAW_FIELDS, function(field) numeric_column(train[[field]]))
  names(columns) <- RAW_FIELDS
  # V2 never recorded its input contract, so invalid values silently become NA
  # and are imputed with the training median. That is exactly the gap the
  # inventory must flag rather than invent a validation rule for.
  medians <- vapply(RAW_FIELDS, function(field) median(columns[[field]], na.rm = TRUE), numeric(1L))
  for (field in RAW_FIELDS) {
    values <- columns[[field]]
    values[is.na(values)] <- medians[[field]]
    columns[[field]] <- values
  }

  utilisation <- vapply(1:6, function(index) {
    pmin(pmax(columns[[paste0("bill_amt_", index)]] / columns$limit_bal, 0), 2)
  }, numeric(nrow(train)))

  features <- data.frame(
    delay_1 = pmax(columns$pay_status_1, 0),
    delay_2 = pmax(columns$pay_status_2, 0),
    delay_3 = pmax(columns$pay_status_3, 0),
    log_limit = log1p(pmax(columns$limit_bal, 0)),
    util_1 = utilisation[, 1L],
    util_mean_6 = rowMeans(utilisation),
    log_pay_1 = log1p(pmax(columns$pay_amt_1, 0)),
    check.names = FALSE
  )[, FEATURE_ORDER, drop = FALSE]

  label <- numeric_column(train$default_flag)
  keep <- !is.na(label) & label %in% c(0, 1) & rowSums(!is.finite(as.matrix(features))) == 0L
  if (!any(keep)) contract_stop("Training data has no usable labelled rows")

  fit <- glm(default_flag ~ delay_1 + delay_2 + delay_3 + log_limit + util_1 + util_mean_6 + log_pay_1,
             data = data.frame(default_flag = label[keep], features[keep, , drop = FALSE], check.names = FALSE),
             family = binomial)
  coefficients <- coef(fit)
  if (any(!is.finite(coefficients))) contract_stop("Model fitting produced non-finite coefficients")

  coefficient_entries <- list(intercept = json_number(unname(coefficients["(Intercept)"])))
  for (feature in FEATURE_ORDER) coefficient_entries[[feature]] <- json_number(unname(coefficients[feature]))
  median_entries <- lapply(as.list(medians), json_number)
  model_entries <- list(
    schema_version = json_string("1"),
    model_id = json_string(MODEL_ID),
    model_family = json_string("glm binomial logit"),
    coefficients = json_object(coefficient_entries),
    feature_order = json_array(FEATURE_ORDER),
    medians = json_object(median_entries),
    threshold = json_number(THRESHOLD),
    training_rows = as.character(sum(keep)),
    r_version = json_string(R.version.string)
  )
  writeLines(json_object(model_entries), file.path(output_dir, "model.json"), useBytes = TRUE)

  eta <- as.numeric(coefficients["(Intercept)"] + as.matrix(features) %*% coefficients[FEATURE_ORDER])
  probability <- 1 / (1 + exp(-eta))
  frame <- data.frame(
    client_id = train$client_id,
    probability = sprintf("%.17g", probability),
    classification = as.character(as.integer(probability >= THRESHOLD)),
    stringsAsFactors = FALSE,
    check.names = FALSE
  )[, OUTPUT_COLUMNS, drop = FALSE]
  write.csv(frame, file.path(output_dir, "train_predictions.csv"), row.names = FALSE, quote = TRUE)
  invisible(TRUE)
}

tryCatch(
  {
    arguments <- commandArgs(trailingOnly = TRUE)
    if (length(arguments) != 2L) contract_stop("Usage: Rscript legacy/credit_v2.R TRAIN_CSV OUTPUT_DIR")
    fit_and_write(arguments[1L], arguments[2L])
  },
  error = function(error) {
    cat(paste0("ERROR: ", conditionMessage(error), "\n"), file = stderr())
    quit(save = "no", status = 2L)
  }
)
