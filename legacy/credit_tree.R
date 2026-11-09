#!/usr/bin/env Rscript
# MDL_CREDIT_TREE - simulated legacy credit-default model (rpart decision tree).
# The original hyperparameter sheet was lost, so nothing here is documented
# beyond the code itself.

MODEL_ID <- "MDL_CREDIT_TREE"
FEATURE_ORDER <- c("delay_1", "delay_2", "delay_3", "delay_4", "delay_5", "delay_6", "limit_bal", "util_1")
RAW_FIELDS <- c("limit_bal", "pay_status_1", "pay_status_2", "pay_status_3", "pay_status_4",
                "pay_status_5", "pay_status_6", "bill_amt_1")
OUTPUT_COLUMNS <- c("client_id", "probability", "classification")
MAXDEPTH <- 3
THRESHOLD <- 0.50

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
  data
}

numeric_column <- function(values) {
  missing <- is.na(values) | trimws(values) == ""
  parsed <- suppressWarnings(as.numeric(trimws(values)))
  parsed[missing] <- NA_real_
  parsed
}

fit_and_write <- function(train_path, output_dir) {
  if (!requireNamespace("rpart", quietly = TRUE)) contract_stop("Package rpart is not available")
  train <- read_input(train_path)
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  columns <- lapply(RAW_FIELDS, function(field) numeric_column(train[[field]]))
  names(columns) <- RAW_FIELDS
  for (field in RAW_FIELDS) {
    values <- columns[[field]]
    replacement <- median(values, na.rm = TRUE)
    if (!is.finite(replacement)) contract_stop(paste("Cannot impute", field))
    values[is.na(values)] <- replacement
    columns[[field]] <- values
  }

  features <- data.frame(
    delay_1 = pmax(columns$pay_status_1, 0),
    delay_2 = pmax(columns$pay_status_2, 0),
    delay_3 = pmax(columns$pay_status_3, 0),
    delay_4 = pmax(columns$pay_status_4, 0),
    delay_5 = pmax(columns$pay_status_5, 0),
    delay_6 = pmax(columns$pay_status_6, 0),
    limit_bal = columns$limit_bal,
    util_1 = pmin(pmax(columns$bill_amt_1 / columns$limit_bal, 0), 2),
    check.names = FALSE
  )[, FEATURE_ORDER, drop = FALSE]

  label <- numeric_column(train$default_flag)
  keep <- !is.na(label) & label %in% c(0, 1) & rowSums(!is.finite(as.matrix(features))) == 0L
  if (!any(keep)) contract_stop("Training data has no usable labelled rows")

  fit <- rpart::rpart(
    default_flag ~ delay_1 + delay_2 + delay_3 + delay_4 + delay_5 + delay_6 + limit_bal + util_1,
    data = data.frame(default_flag = label[keep], features[keep, , drop = FALSE], check.names = FALSE),
    method = "class",
    control = rpart::rpart.control(maxdepth = MAXDEPTH, cp = 0.001, minsplit = 100, minbucket = 50)
  )

  probability <- as.numeric(predict(fit, newdata = features, type = "prob")[, "1"])
  model_entries <- list(
    schema_version = json_string("1"),
    model_id = json_string(MODEL_ID),
    model_family = json_string("rpart classification tree"),
    feature_order = json_array(FEATURE_ORDER),
    maxdepth = as.character(MAXDEPTH),
    threshold = json_number(THRESHOLD),
    leaves = as.character(length(fit$frame$var[fit$frame$var == "<leaf>"])),
    training_rows = as.character(sum(keep)),
    r_version = json_string(R.version.string)
  )
  writeLines(json_object(model_entries), file.path(output_dir, "model.json"), useBytes = TRUE)

  frame <- data.frame(
    client_id = train$client_id,
    probability = sprintf("%.17g", probability),
    classification = as.character(as.integer(probability >= THRESHOLD)),
    stringsAsFactors = FALSE,
    check.names = FALSE
  )[, OUTPUT_COLUMNS, drop = FALSE]
  write.csv(frame, file.path(output_dir, "train_predictions.csv"), row.names = FALSE, quote = TRUE)
  writeLines(capture.output(print(fit)), file.path(output_dir, "tree_structure.txt"), useBytes = TRUE)
  invisible(TRUE)
}

tryCatch(
  {
    arguments <- commandArgs(trailingOnly = TRUE)
    if (length(arguments) != 2L) contract_stop("Usage: Rscript legacy/credit_tree.R TRAIN_CSV OUTPUT_DIR")
    fit_and_write(arguments[1L], arguments[2L])
  },
  error = function(error) {
    cat(paste0("ERROR: ", conditionMessage(error), "\n"), file = stderr())
    quit(save = "no", status = 2L)
  }
)
