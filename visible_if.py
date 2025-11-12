from __future__ import annotations

from typing import Any, Dict, List


def _coerce_number(x: Any):
    try:
        if isinstance(x, bool):
            return float(int(x))
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str) and x.strip() != "":
            return float(x.strip())
    except Exception:
        pass
    return None


def _op_eval(lhs: Any, op: str, rhs: Any) -> bool:
    # Equality / inequality
    if op == "eq":
        return lhs == rhs
    if op == "neq":
        return lhs != rhs

    # Contains
    if op == "contains":
        try:
            if lhs is None:
                return False
            if isinstance(lhs, (list, tuple, set)):
                return rhs in lhs
            if isinstance(lhs, dict):
                return rhs in lhs.keys()
            return str(rhs) in str(lhs)
        except Exception:
            return False

    # Membership set ops
    if op == "in":
        try:
            if rhs is None:
                return False
            if isinstance(rhs, (list, tuple, set)):
                return lhs in rhs
            if isinstance(rhs, dict):
                return lhs in rhs.keys()
            return str(lhs) in str(rhs)
        except Exception:
            return False

    if op == "nin":
        try:
            if rhs is None:
                return True
            if isinstance(rhs, (list, tuple, set)):
                return lhs not in rhs
            if isinstance(rhs, dict):
                return lhs not in rhs.keys()
            return str(lhs) not in str(rhs)
        except Exception:
            return True

    # Numeric comparisons (fallback to string compare if not numeric)
    ln = _coerce_number(lhs)
    rn = _coerce_number(rhs)
    if ln is not None and rn is not None:
        if op == "gt":
            return ln > rn
        if op == "gte":
            return ln >= rn
        if op == "lt":
            return ln < rn
        if op == "lte":
            return ln <= rn
    else:
        try:
            ls = "" if lhs is None else str(lhs)
            rs = "" if rhs is None else str(rhs)
            if op == "gt":
                return ls > rs
            if op == "gte":
                return ls >= rs
            if op == "lt":
                return ls < rs
            if op == "lte":
                return ls <= rs
        except Exception:
            return False

    return False


def _eval_clause(ctx: Dict[str, Any], clause: Dict[str, Any]) -> bool:
    fld = clause.get("field")
    op = clause.get("op", "eq")
    val = clause.get("value")
    lhs = ctx.get(fld)
    return _op_eval(lhs, op, val)


def evaluate(cond: Any, state: Dict[str, Any], category: str | None = None, make: str | None = None, model: str | None = None) -> bool:
    """
    Evaluate a visible_if object against the current state with virtual fields injected.
    Supported group objects:
      - { "all": [ ... ] }
      - { "any": [ ... ] }
    Clause format:
      { "field": "<name>", "op":"eq|neq|in|nin|gt|gte|lt|lte|contains", "value": <v> }
    """
    if not cond:
        return True

    # Build context with virtual fields
    ctx: Dict[str, Any] = dict(state or {})
    if category is not None:
        ctx["__category__"] = category
    if make is not None:
        ctx["__make__"] = make
    if model is not None:
        ctx["__model__"] = model

    # Group: all
    if isinstance(cond, dict) and "all" in cond:
        subs = cond.get("all") or []
        for sub in subs:
            if not evaluate(sub, ctx, category, make, model):
                return False
        return True

    # Group: any
    if isinstance(cond, dict) and "any" in cond:
        subs = cond.get("any") or []
        for sub in subs:
            if evaluate(sub, ctx, category, make, model):
                return True
        return False

    # Clause
    if isinstance(cond, dict) and "field" in cond:
        return _eval_clause(ctx, cond)

    # Lists are treated as implicit "all"
    if isinstance(cond, list):
        for sub in cond:
            if not evaluate(sub, ctx, category, make, model):
                return False
        return True

    # Unknown structure => visible
    return True


def is_visible(field_def: Dict[str, Any], state: Dict[str, Any], category: str | None = None, make: str | None = None, model: str | None = None) -> bool:
    return evaluate(field_def.get("visible_if"), state, category, make, model)
