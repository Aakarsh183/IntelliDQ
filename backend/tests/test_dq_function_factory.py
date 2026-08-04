"""Pure-function tests for dq_function_factory: no Spark, no network, no env vars."""

from dq_function_factory import build_function_name, slugify


def test_slugify_normalises_spaces_and_case():
    assert slugify("Account Number Not Empty") == "account_number_not_empty"


def test_slugify_collapses_runs_of_special_characters():
    assert slugify("Perf. Date <= Period-End!") == "perf_date_period_end"


def test_slugify_falls_back_on_empty_input():
    assert slugify("") == "dq_rule"
    assert slugify(None) == "dq_rule"


def test_build_function_name_prefixes_dq():
    assert build_function_name("Null Check") == "dq_null_check"
