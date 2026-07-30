# Auto-generated DQ check functions.

# BEGIN GENERATED: not_null_account_number_not_empty
def not_null_account_number_not_empty(df, fields, parameters, id_column):
    if df is None:
        raise ValueError("Input DataFrame is None")
    if not fields:
        raise ValueError("No fields supplied for the generated check")

    missing = [field for field in fields if field not in df.columns]
    if missing:
        raise ValueError(f"Columns not present in dataframe: {missing}")

    from pyspark.sql.functions import col, trim

    allow_blank = bool(parameters.get("allow_blank", False))
    condition = None
    for field in fields:
        field_condition = col(field).isNotNull()
        if not allow_blank:
            field_condition = field_condition & (trim(col(field).cast("string")) != "")
        condition = field_condition if condition is None else (condition & field_condition)

    passed_df = df.filter(condition)
    failed_df = df.filter(~condition)

    passed_count = passed_df.count()
    failed_count = failed_df.count()
    total_count = passed_count + failed_count
    pass_rate = (passed_count / total_count) if total_count else 0

    result_id_column = id_column if id_column in df.columns else (df.columns[0] if df.columns else None)
    failed_ids = []
    if result_id_column:
        failed_ids = [
            row[result_id_column]
            for row in failed_df.select(result_id_column).limit(100).collect()
            if row[result_id_column] is not None
        ]

    result = {
        "rule": parameters.get("rule_name", "Account Number Not Empty"),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "pass_rate": round(pass_rate, 4),
        "failed_ids": failed_ids,
        "check_type": parameters.get("check_type"),
    }
    return passed_df, failed_df, result

# END GENERATED: not_null_account_number_not_empty

# BEGIN GENERATED: comparison_non_negative_closing_balance
def comparison_non_negative_closing_balance(df, fields, parameters, id_column):
    if df is None:
        raise ValueError("Input DataFrame is None")
    if not fields:
        raise ValueError("No fields supplied for the generated check")

    missing = [field for field in fields if field not in df.columns]
    if missing:
        raise ValueError(f"Columns not present in dataframe: {missing}")

    from pyspark.sql.functions import col, lit

    left_field = fields[0]
    operator = parameters.get("operator", "==")
    right_expr = None

    compare_to_field = parameters.get("compare_to_field")
    if compare_to_field:
        if compare_to_field not in df.columns:
            raise ValueError(f"Comparison field not present in dataframe: {compare_to_field}")
        right_expr = col(compare_to_field)
    elif parameters.get("compare_to_value") is not None:
        right_expr = lit(parameters.get("compare_to_value"))
    else:
        raise ValueError("Comparison target missing")

    left_expr = col(left_field)
    if operator == ">":
        condition = left_expr > right_expr
    elif operator == ">=":
        condition = left_expr >= right_expr
    elif operator == "<":
        condition = left_expr < right_expr
    elif operator == "<=":
        condition = left_expr <= right_expr
    elif operator == "!=":
        condition = left_expr != right_expr
    else:
        condition = left_expr == right_expr

    passed_df = df.filter(condition)
    failed_df = df.filter(~condition)

    passed_count = passed_df.count()
    failed_count = failed_df.count()
    total_count = passed_count + failed_count
    pass_rate = (passed_count / total_count) if total_count else 0

    result_id_column = id_column if id_column in df.columns else (df.columns[0] if df.columns else None)
    failed_ids = []
    if result_id_column:
        failed_ids = [
            row[result_id_column]
            for row in failed_df.select(result_id_column).limit(100).collect()
            if row[result_id_column] is not None
        ]

    result = {
        "rule": parameters.get("rule_name", "Non-Negative Closing Balance"),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "pass_rate": round(pass_rate, 4),
        "failed_ids": failed_ids,
        "check_type": parameters.get("check_type"),
    }
    return passed_df, failed_df, result

# END GENERATED: comparison_non_negative_closing_balance
