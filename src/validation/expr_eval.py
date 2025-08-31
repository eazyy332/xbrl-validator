from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
import re as _re


@dataclass
class Token:
    kind: str
    value: Any


class ExprSyntaxError(Exception):
    pass


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_"


def _is_ident_part(ch: str) -> bool:
    return ch.isalnum() or ch in ("_", ".")


def tokenize(s: str) -> List[Token]:
    s = s.strip()
    i = 0
    out: List[Token] = []
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "()[]":
            out.append(Token(ch, ch))
            i += 1
            continue
        if ch in (",",):
            out.append(Token(",", ","))
            i += 1
            continue
        # Operators and punctuation
        if s.startswith("<=", i) or s.startswith(">=", i) or s.startswith("==", i) or s.startswith("!=", i):
            out.append(Token("op", s[i:i+2]))
            i += 2
            continue
        if ch in ("<", ">"):
            out.append(Token("op", ch))
            i += 1
            continue
        # Strings
        if ch in ('"', "'"):
            q = ch
            i += 1
            start = i
            buf = []
            while i < len(s):
                if s[i] == "\\" and i + 1 < len(s):
                    buf.append(s[i+1])
                    i += 2
                    continue
                if s[i] == q:
                    break
                buf.append(s[i])
                i += 1
            if i >= len(s) or s[i] != q:
                raise ExprSyntaxError("Unterminated string literal")
            i += 1
            out.append(Token("str", "".join(buf)))
            continue
        # Numbers
        if ch.isdigit() or (ch == "." and i + 1 < len(s) and s[i+1].isdigit()):
            start = i
            i += 1
            while i < len(s) and (s[i].isdigit() or s[i] == "."):
                i += 1
            out.append(Token("num", float(s[start:i])))
            continue
        # Identifiers / keywords
        if _is_ident_start(ch):
            start = i
            i += 1
            while i < len(s) and _is_ident_part(s[i]):
                i += 1
            ident = s[start:i]
            low = ident.lower()
            if low in ("and", "or", "not", "in", "like", "true", "false", "null"):
                out.append(Token("kw", low))
            else:
                out.append(Token("id", ident))
            continue
        raise ExprSyntaxError(f"Unexpected character: {ch}")
    return out


class Parser:
    def __init__(self, tokens: List[Token]):
        self.toks = tokens
        self.i = 0

    def _peek(self) -> Optional[Token]:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _eat(self, kind: Optional[str] = None, value: Optional[str] = None) -> Token:
        t = self._peek()
        if t is None:
            raise ExprSyntaxError("Unexpected end of input")
        if kind is not None and t.kind != kind:
            raise ExprSyntaxError(f"Expected {kind}, got {t.kind}")
        if value is not None and t.value != value:
            raise ExprSyntaxError(f"Expected token {value}")
        self.i += 1
        return t

    # Grammar (Pratt/recursive descent):
    # expr := or_expr
    # or_expr := and_expr ( 'or' and_expr )*
    # and_expr := not_expr ( 'and' not_expr )*
    # not_expr := 'not' not_expr | cmp
    # cmp := add ( (==|!=|<|<=|>|>=|in) add )?
    # add := term ( '+' term | '-' term )*  [optional extension]
    # term := factor ( '*' factor | '/' factor )* [optional extension]
    # factor := primary
    # primary := NUMBER | STRING | IDENT func_call? | '(' expr ')'
    def parse(self) -> Any:
        return self._parse_or()

    def _parse_or(self) -> Any:
        node = self._parse_and()
        while True:
            t = self._peek()
            if t and t.kind == "kw" and t.value == "or":
                self._eat("kw", "or")
                rhs = self._parse_and()
                node = ("or", node, rhs)
            else:
                break
        return node

    def _parse_and(self) -> Any:
        node = self._parse_not()
        while True:
            t = self._peek()
            if t and t.kind == "kw" and t.value == "and":
                self._eat("kw", "and")
                rhs = self._parse_not()
                node = ("and", node, rhs)
            else:
                break
        return node

    def _parse_not(self) -> Any:
        t = self._peek()
        if t and t.kind == "kw" and t.value == "not":
            self._eat("kw", "not")
            expr = self._parse_not()
            return ("not", expr)
        return self._parse_cmp()

    def _parse_cmp(self) -> Any:
        left = self._parse_primary()
        t = self._peek()
        if t and (t.kind == "op" or (t.kind == "kw" and t.value in ("in", "like"))):
            op = self._eat(t.kind).value
            right = self._parse_primary()
            return (op, left, right)
        return left

    def _parse_primary(self) -> Any:
        t = self._peek()
        if t is None:
            raise ExprSyntaxError("Unexpected end of input")
        if t.kind == "num":
            self._eat("num")
            return ("num", t.value)
        if t.kind == "str":
            self._eat("str")
            return ("str", t.value)
        if t.kind == "kw" and t.value in ("true", "false", "null"):
            val = True if t.value == "true" else False if t.value == "false" else None
            self._eat("kw")
            return ("lit", val)
        if t.kind == "id":
            ident = self._eat("id").value
            # function call?
            if self._peek() and self._peek().kind == "(":
                self._eat("(")
                args: List[Any] = []
                if self._peek() and self._peek().kind != ")":
                    args.append(self.parse())
                    while self._peek() and self._peek().kind == ",":
                        self._eat(",")
                        args.append(self.parse())
                self._eat(")")
                return ("call", ident, args)
            return ("var", ident)
        if t.kind == "(":
            self._eat("(")
            expr = self.parse()
            self._eat(")")
            return expr
        if t.kind == "[":
            # list literal
            self._eat("[")
            items: List[Any] = []
            if self._peek() and self._peek().kind != "]":
                items.append(self.parse())
                while self._peek() and self._peek().kind == ",":
                    self._eat(",")
                    items.append(self.parse())
            self._eat("]")
            return ("list", items)
        raise ExprSyntaxError(f"Unexpected token {t.kind}")


def evaluate(ast: Any, env: Dict[str, Any], funcs: Dict[str, Callable[..., Any]]) -> Any:
    k = ast[0] if isinstance(ast, tuple) else None
    if k == "num":
        return ast[1]
    if k == "str":
        return ast[1]
    if k == "var":
        name = ast[1]
        return env.get(name)
    if k == "lit":
        return ast[1]
    if k == "call":
        name = ast[1]
        args = [evaluate(a, env, funcs) for a in ast[2]]
        fn = funcs.get(name)
        if fn is None:
            raise ExprSyntaxError(f"Unknown function {name}")
        return fn(*args)
    if k == "list":
        return [evaluate(a, env, funcs) for a in ast[1]]
    if k in ("and", "or"):
        left = bool(evaluate(ast[1], env, funcs))
        if k == "and":
            return left and bool(evaluate(ast[2], env, funcs))
        return left or bool(evaluate(ast[2], env, funcs))
    if k == "not":
        return not bool(evaluate(ast[1], env, funcs))
    if k in ("==", "!=", "<", "<=", ">", ">=", "in", "like"):
        l = evaluate(ast[1], env, funcs)
        r = evaluate(ast[2], env, funcs)
        try:
            if k == "==":
                return l == r
            if k == "!=":
                return l != r
            if k == "<":
                return l < r
            if k == "<=":
                return l <= r
            if k == ">":
                return l > r
            if k == ">=":
                return l >= r
            if k == "in":
                if isinstance(r, (list, tuple, set)):
                    return l in r
                return False
            if k == "like":
                # SQL LIKE: translate % -> .*, _ -> . ; escape other regex metas
                try:
                    pat = str(r)
                    rex = []
                    for ch in pat:
                        if ch == "%":
                            rex.append(".*")
                        elif ch == "_":
                            rex.append(".")
                        elif ch in ".^$*+?{}[]|()\\":
                            rex.append("\\" + ch)
                        else:
                            rex.append(ch)
                    pattern = "".join(rex)
                    return _re.fullmatch(pattern, str(l)) is not None
                except Exception:
                    return False
        except Exception:
            return False
    # literals or unknown
    return ast


def compile_expr(expr: str) -> Any:
    toks = tokenize(expr)
    p = Parser(toks)
    ast = p.parse()
    return ast


# Built-in safe helper set that callers may extend
def default_helpers() -> Dict[str, Callable[..., Any]]:
    import datetime as _dt
    from calendar import monthrange as _monthrange
    import math as _math
    def regex_match(s: Any, pattern: Any) -> bool:
        try:
            return _re.search(str(pattern), str(s)) is not None
        except Exception:
            return False
    def equals_ic(a: Any, b: Any) -> bool:
        try:
            return str(a).lower() == str(b).lower()
        except Exception:
            return False
    def contains_ic(s: Any, sub: Any) -> bool:
        try:
            return str(sub).lower() in str(s).lower()
        except Exception:
            return False
    def any_in(items: Any, hay: Any) -> bool:
        try:
            it = list(items) if not isinstance(items, list) else items
            hy = list(hay) if not isinstance(hay, list) else hay
            return any(x in hy for x in it)
        except Exception:
            return False
    def all_in(items: Any, hay: Any) -> bool:
        try:
            it = list(items) if not isinstance(items, list) else items
            hy = list(hay) if not isinstance(hay, list) else hay
            return all(x in hy for x in it)
        except Exception:
            return False
    # Local helpers for dates with clearer structure (avoid long lambdas)
    def _to_date(s: Any) -> Any:
        try:
            return _dt.datetime.fromisoformat(str(s)).date()
        except Exception:
            return None
    def _add_months(d: Any, n: Any) -> Any:
        try:
            if d is None:
                return None
            d = d if isinstance(d, _dt.date) else _to_date(d)
            if d is None:
                return None
            n = int(n) if n is not None else 0
            year = d.year + (d.month - 1 + n) // 12
            month = ((d.month - 1 + n) % 12) + 1
            day = min(d.day, _monthrange(year, month)[1])
            return _dt.date(year, month, day)
        except Exception:
            return None
    def _eomonth(d: Any) -> Any:
        try:
            d = d if isinstance(d, _dt.date) else _to_date(d)
            if d is None:
                return None
            return _dt.date(d.year, d.month, _monthrange(d.year, d.month)[1])
        except Exception:
            return None

    return {
        # Control flow
        "if": lambda cond, a, b: (a if bool(cond) else b),
        "iif": lambda cond, a, b: (a if bool(cond) else b),
        "and_fn": lambda *args: all(bool(x) for x in args),
        "or_fn": lambda *args: any(bool(x) for x in args),
        # Regex/string helpers
        "regex": regex_match,
        "equals_ic": equals_ic,
        "contains_ic": contains_ic,
        "any_in": any_in,
        "all_in": all_in,
        "lower": lambda s: str(s).lower() if s is not None else "",
        "upper": lambda s: str(s).upper() if s is not None else "",
        "trim": lambda s: str(s).strip() if s is not None else "",
        "startswith": lambda s, p: str(s).startswith(str(p)) if s is not None else False,
        "endswith": lambda s, p: str(s).endswith(str(p)) if s is not None else False,
        "contains": lambda s, sub: (str(sub) in str(s)) if s is not None else False,
        # Date helpers
        "to_date": _to_date,
        "add_months": _add_months,
        "eomonth": _eomonth,
        "before": lambda d1, d2: (d1 is not None and d2 is not None and d1 < d2),
        "after": lambda d1, d2: (d1 is not None and d2 is not None and d1 > d2),
        "between": lambda d, s, e: (d is not None and s is not None and e is not None and s <= d <= e),
        "year": lambda d: (getattr(d, "year", None) if d is not None else None),
        "month": lambda d: (getattr(d, "month", None) if d is not None else None),
        "day": lambda d: (getattr(d, "day", None) if d is not None else None),
        "len": lambda x: (len(x) if x is not None else 0),
        "left": lambda s, n: str(s)[: int(n) if n is not None else 0],
        "right": lambda s, n: str(s)[-int(n) if n is not None else 0 :],
        "mid": lambda s, start, count: str(s)[int(start) - 1 : int(start) - 1 + int(count)],
        "isblank": lambda x: (x is None or (str(x).strip() == "")),
        "isnumber": lambda x: (isinstance(x, (int, float)) or (isinstance(x, str) and _re.fullmatch(r"[-+]?\d+(\.\d+)?", x) is not None)),
        "like": lambda s, pat: (lambda _s, _p: _re.fullmatch("".join((".*" if c=="%" else "." if c=="_" else ("\\"+c if c in ".^$*+?{}[]|()\\" else c) for c in str(_p))), str(_s)) is not None)(s, pat),
        # Numeric helpers
        "abs": lambda x: (abs(float(x)) if x is not None else 0.0),
        "round": lambda x, n=0: (round(float(x), int(n)) if x is not None else 0.0),
        "floor": lambda x: (_math.floor(float(x)) if x is not None else 0),
        "ceil": lambda x: (_math.ceil(float(x)) if x is not None else 0),
        "min": lambda *args: (min(args) if args else None),
        "max": lambda *args: (max(args) if args else None),
        "sum": lambda xs: (sum(xs) if xs is not None else 0),
        "int": lambda x: (int(float(x)) if x is not None else 0),
        "float": lambda x: (float(x) if x is not None else 0.0),
        # Null-coalescing
        "coalesce": lambda *args: next((a for a in args if a not in (None, "")), None),
    }


