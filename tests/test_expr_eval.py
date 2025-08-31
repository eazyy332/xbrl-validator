from src.validation.expr_eval import compile_expr, evaluate, default_helpers


def test_basic_booleans_and_in():
    ast = compile_expr("true and (1 in [1,2,3])")
    assert evaluate(ast, {}, default_helpers()) is True


def test_string_helpers():
    ast = compile_expr("startswith('COREP', 'CO') and contains_ic('AbC', 'bc') and equals_ic('A', 'a')")
    assert evaluate(ast, {}, default_helpers()) is True


def test_date_helpers():
    env = {}
    helpers = default_helpers()
    ast = compile_expr("before(to_date('2024-01-01'), to_date('2024-12-31')) and after(to_date('2024-12-31'), to_date('2024-01-01')) and between(to_date('2024-06-01'), to_date('2024-01-01'), to_date('2024-12-31'))")
    assert evaluate(ast, env, helpers) is True


def test_like_and_is_functions():
    ast = compile_expr("'COREP_FRTB' like 'COREP_%' and isnumber('123') and not isblank('x')")
    assert evaluate(ast, {}, default_helpers()) is True


