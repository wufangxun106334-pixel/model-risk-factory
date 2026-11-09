#!/usr/bin/env Rscript

MODEL_ID <- "MDL_CREDIT_V1"
FEATURE_ORDER <- c("delay_1", "log_limit", "util_1", "log_pay_1")
RAW_FIELDS <- c("limit_bal", "pay_status_1", "bill_amt_1", "pay_amt_1")
INPUT_COLUMNS <- c("client_id", RAW_FIELDS)
OUTPUT_COLUMNS <- c(
  "client_id", "probability", "classification", "status", "error_code",
  "limit_bal_imputed", "pay_status_1_imputed", "bill_amt_1_imputed",
  "pay_amt_1_imputed"
)
THRESHOLD <- 0.35

json_string <- function(value) {
  chars <- strsplit(enc2utf8(as.character(value)), "", fixed = TRUE)[[1L]]
  escaped <- vapply(chars, function(char) {
    code <- utf8ToInt(char)
    if (char == "\\") return("\\\\")
    if (char == "\"") return("\\\"")
    if (char == "\b") return("\\b")
    if (char == "\f") return("\\f")
    if (char == "\n") return("\\n")
    if (char == "\r") return("\\r")
    if (char == "\t") return("\\t")
    if (code < 32L) return(sprintf("\\u%04x", code))
    char
  }, character(1L), USE.NAMES = FALSE)
  paste0("\"", paste0(escaped, collapse = ""), "\"")
}

json_number <- function(value) {
  if (length(value) != 1L || !is.finite(value)) {
    stop("Cannot serialize a non-finite JSON number")
  }
  sprintf("%.17g", value)
}

json_array <- function(values) {
  paste0("[", paste0(vapply(values, json_string, character(1L)), collapse = ","), "]")
}

json_object <- function(entries) {
  keys <- vapply(names(entries), json_string, character(1L))
  paste0("{", paste0(keys, ":", unlist(entries, use.names = FALSE), collapse = ","), "}")
}

contract_stop <- function(message) {
  stop(message, call. = FALSE)
}

read_input <- function(path, require_label = FALSE) {
  if (!file.exists(path) || file.info(path)$isdir) {
    contract_stop(paste("Input file does not exist:", path))
  }
  data <- tryCatch(
    read.csv(
      path,
      colClasses = "character",
      na.strings = character(),
      check.names = FALSE,
      stringsAsFactors = FALSE,
      blank.lines.skip = FALSE
    ),
    error = function(error) contract_stop(conditionMessage(error))
  )
  required <- INPUT_COLUMNS
  if (require_label) required <- c(required, "default_flag")
  missing_columns <- setdiff(required, names(data))
  if (length(missing_columns) > 0L) {
    contract_stop(paste("Missing required columns:", paste(missing_columns, collapse = ",")))
  }
  if (anyDuplicated(names(data))) {
    contract_stop("Duplicate CSV column names are not allowed")
  }
  if (nrow(data) == 0L) {
    contract_stop(paste("Input file has no data rows:", path))
  }
  ids <- data$client_id
  if (any(is.na(ids) | trimws(ids) == "")) {
    contract_stop("client_id must be non-empty")
  }
  if (anyDuplicated(ids)) {
    contract_stop("client_id values must be unique")
  }
  data
}

parse_numeric <- function(values) {
  missing <- is.na(values) | trimws(values) == ""
  parsed <- rep(NA_real_, length(values))
  parsed[!missing] <- suppressWarnings(as.numeric(trimws(values[!missing])))
  list(missing = missing, value = parsed)
}

prepare_raw <- function(data, medians = NULL) {
  parsed <- lapply(RAW_FIELDS, function(field) parse_numeric(data[[field]]))
  names(parsed) <- RAW_FIELDS

  valid <- lapply(RAW_FIELDS, function(field) {
    value <- parsed[[field]]$value
    present_valid <- !is.na(value) & is.finite(value)
    if (field == "limit_bal") present_valid <- present_valid & value > 0
    if (field == "pay_status_1") {
      present_valid <- present_valid & value >= -2 & value <= 9 & value == floor(value)
    }
    if (field == "pay_amt_1") present_valid <- present_valid & value >= 0
    parsed[[field]]$missing | present_valid
  })
  names(valid) <- RAW_FIELDS

  if (is.null(medians)) {
    medians <- lapply(RAW_FIELDS, function(field) {
      keep <- !parsed[[field]]$missing & valid[[field]]
      if (!any(keep)) {
        contract_stop(paste("Training data cannot provide median for", field))
      }
      median(parsed[[field]]$value[keep])
    })
    names(medians) <- RAW_FIELDS
  }

  imputed <- lapply(RAW_FIELDS, function(field) {
    value <- parsed[[field]]$value
    value[parsed[[field]]$missing] <- medians[[field]]
    value
  })
  names(imputed) <- RAW_FIELDS

  flags <- lapply(RAW_FIELDS, function(field) as.integer(parsed[[field]]$missing))
  names(flags) <- paste0(RAW_FIELDS, "_imputed")

  error_code <- rep("", nrow(data))
  for (field in RAW_FIELDS) {
    assign <- error_code == "" & !valid[[field]]
    error_code[assign] <- paste0("INVALID_", toupper(field))
  }

  list(values = imputed, flags = flags, error_code = error_code, medians = medians)
}

derive_features <- function(values) {
  data.frame(
    delay_1 = pmax(values$pay_status_1, 0),
    log_limit = log1p(values$limit_bal),
    util_1 = pmin(pmax(values$bill_amt_1 / values$limit_bal, 0), 2),
    log_pay_1 = log1p(values$pay_amt_1)
  )[, FEATURE_ORDER, drop = FALSE]
}

logistic <- function(eta) {
  probability <- rep(NA_real_, length(eta))
  available <- !is.na(eta)
  positive <- available & eta >= 0
  negative <- available & eta < 0
  probability[positive] <- 1 / (1 + exp(-eta[positive]))
  exponential <- exp(eta[negative])
  probability[negative] <- exponential / (1 + exponential)
  probability
}

prediction_frame <- function(data, prepared, probabilities = NULL, rejected = NULL) {
  if (is.null(rejected)) rejected <- prepared$error_code != ""
  probability_text <- rep("", nrow(data))
  classification <- rep("", nrow(data))
  status <- rep("REJECTED", nrow(data))
  status[!rejected] <- "VALID"
  if (!is.null(probabilities)) {
    probability_text[!rejected] <- sprintf("%.17g", probabilities[!rejected])
    classification[!rejected] <- as.character(as.integer(probabilities[!rejected] >= THRESHOLD))
  }
  frame <- data.frame(
    client_id = data$client_id,
    probability = probability_text,
    classification = classification,
    status = status,
    error_code = prepared$error_code,
    stringsAsFactors = FALSE,
    check.names = FALSE
  )
  for (field in RAW_FIELDS) {
    frame[[paste0(field, "_imputed")]] <- as.integer(prepared$flags[[paste0(field, "_imputed")]])
  }
  frame[, OUTPUT_COLUMNS, drop = FALSE]
}

write_predictions <- function(frame, path) {
  write.csv(frame, path, row.names = FALSE, quote = TRUE, na = "")
}

sha256_file <- function(path) {
  normalized <- normalizePath(path, mustWork = TRUE)
  if (nzchar(Sys.which("shasum"))) {
    output <- system2(Sys.which("shasum"), c("-a", "256", shQuote(normalized)), stdout = TRUE, stderr = TRUE)
  } else if (nzchar(Sys.which("sha256sum"))) {
    output <- system2(Sys.which("sha256sum"), shQuote(normalized), stdout = TRUE, stderr = TRUE)
  } else {
    contract_stop("Neither shasum nor sha256sum is available for artifact hashes")
  }
  status <- attr(output, "status")
  if (!is.null(status) && status != 0L) {
    contract_stop(paste("Unable to hash", path))
  }
  tolower(strsplit(trimws(output[1L]), "[[:space:]]+")[[1L]][1L])
}

run <- function(args) {
  if (length(args) < 2L || length(args) > 4L) {
    contract_stop("Usage: Rscript legacy/credit_v1.R TRAIN_CSV OUTPUT_DIR [DEV_CSV] [HOLDOUT_CSV]")
  }
  train_path <- args[1L]
  output_dir <- args[2L]
  optional_paths <- args[-c(1L, 2L)]
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
  if (!dir.exists(output_dir)) contract_stop(paste("Cannot create output directory:", output_dir))

  train <- read_input(train_path, require_label = TRUE)
  train_prepared <- prepare_raw(train)
  label <- parse_numeric(train$default_flag)
  label_valid <- !label$missing & !is.na(label$value) & is.finite(label$value) &
    label$value %in% c(0, 1)
  rejected <- train_prepared$error_code != "" | !label_valid
  train_prepared$error_code[!label_valid & train_prepared$error_code == ""] <- "INVALID_DEFAULT_FLAG"
  if (all(rejected)) contract_stop("Training data has no valid labelled rows")

  features <- derive_features(train_prepared$values)
  training_data <- data.frame(default_flag = label$value, features, check.names = FALSE)
  training_data <- training_data[!rejected, , drop = FALSE]
  fit <- glm(
    default_flag ~ delay_1 + log_limit + util_1 + log_pay_1,
    data = training_data,
    family = binomial
  )
  coefficients <- coef(fit)
  if (any(!is.finite(coefficients))) contract_stop("Model fitting produced non-finite coefficients")

  coefficient_entries <- list(intercept = json_number(unname(coefficients["(Intercept)"])))
  for (feature in FEATURE_ORDER) {
    coefficient_entries[[feature]] <- json_number(unname(coefficients[feature]))
  }
  median_entries <- lapply(train_prepared$medians, json_number)
  model_entries <- list(
    schema_version = json_string("1"),
    model_id = json_string(MODEL_ID),
    coefficients = json_object(coefficient_entries),
    feature_order = json_array(FEATURE_ORDER),
    medians = json_object(median_entries),
    threshold = json_number(THRESHOLD),
    training_rows = as.character(nrow(training_data)),
    r_version = json_string(R.version.string)
  )
  model_path <- file.path(output_dir, "model.json")
  writeLines(json_object(model_entries), model_path, useBytes = TRUE)

  train_eta <- as.numeric(coefficients["(Intercept)"] + as.matrix(features) %*% coefficients[FEATURE_ORDER])
  train_probabilities <- logistic(train_eta)
  train_frame <- prediction_frame(train, train_prepared, train_probabilities, rejected)
  train_path_out <- file.path(output_dir, "train_predictions.csv")
  write_predictions(train_frame, train_path_out)
  artifact_paths <- c(model = model_path, train_predictions = train_path_out)

  if (length(optional_paths) >= 1L) {
    dev <- read_input(optional_paths[1L])
    dev_prepared <- prepare_raw(dev, train_prepared$medians)
    dev_features <- derive_features(dev_prepared$values)
    eta <- as.numeric(coefficients["(Intercept)"] + as.matrix(dev_features) %*% coefficients[FEATURE_ORDER])
    dev_path_out <- file.path(output_dir, "dev_predictions.csv")
    write_predictions(prediction_frame(dev, dev_prepared, logistic(eta)), dev_path_out)
    artifact_paths <- c(artifact_paths, dev_predictions = dev_path_out)
  }
  if (length(optional_paths) == 2L) {
    holdout <- read_input(optional_paths[2L])
    holdout_prepared <- prepare_raw(holdout, train_prepared$medians)
    holdout_features <- derive_features(holdout_prepared$values)
    eta <- as.numeric(coefficients["(Intercept)"] + as.matrix(holdout_features) %*% coefficients[FEATURE_ORDER])
    holdout_path_out <- file.path(output_dir, "holdout_predictions.csv")
    write_predictions(prediction_frame(holdout, holdout_prepared, logistic(eta)), holdout_path_out)
    artifact_paths <- c(artifact_paths, holdout_predictions = holdout_path_out)
  }

  session_path <- file.path(output_dir, "sessionInfo.txt")
  writeLines(capture.output(sessionInfo()), session_path, useBytes = TRUE)
  artifact_paths <- c(artifact_paths, sessionInfo = session_path)

  artifact_entries <- lapply(seq_along(artifact_paths), function(index) {
    json_object(list(sha256 = json_string(sha256_file(artifact_paths[[index]]))))
  })
  names(artifact_entries) <- basename(artifact_paths)
  manifest <- list(
    schema_version = json_string("1"),
    model_id = json_string(MODEL_ID),
    artifacts = json_object(artifact_entries)
  )
  writeLines(json_object(manifest), file.path(output_dir, "baseline_manifest.json"), useBytes = TRUE)
}

tryCatch(
  run(commandArgs(trailingOnly = TRUE)),
  error = function(error) {
    cat(paste0("ERROR: ", conditionMessage(error), "\n"), file = stderr())
    quit(save = "no", status = 2L)
  }
)
