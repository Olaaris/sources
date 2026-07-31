"""Fit closed-form models to an extracted XP curve.

Recovering the *formula* behind a table matters more than the table itself: it
extrapolates past the level cap shipped in the data, and it makes the numbers
verifiable — a curve that reproduces every row exactly is almost certainly the
one the designers used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

from .tables import XpTable


@dataclass
class Fit:
    """One model fitted against a curve."""

    model: str
    formula: str
    params: list[float]
    r_squared: float
    max_relative_error: float
    exact_matches: int
    total_points: int

    @property
    def is_exact(self) -> bool:
        return self.exact_matches == self.total_points

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "formula": self.formula,
            "params": self.params,
            "r_squared": round(self.r_squared, 8),
            "max_relative_error": round(self.max_relative_error, 8),
            "exact_matches": self.exact_matches,
            "total_points": self.total_points,
            "exact": self.is_exact,
        }


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting."""
    n = len(matrix)
    aug = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]

    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for row in range(col + 1, n):
            factor = aug[row][col] / aug[col][col]
            for k in range(col, n + 1):
                aug[row][k] -= factor * aug[col][k]

    solution = [0.0] * n
    for row in reversed(range(n)):
        total = aug[row][n] - sum(aug[row][k] * solution[k] for k in range(row + 1, n))
        solution[row] = total / aug[row][row]
    return solution


def polyfit(xs: Sequence[float], ys: Sequence[float], degree: int) -> list[float] | None:
    """Least-squares polynomial fit, returning coefficients low order first."""
    if len(xs) <= degree:
        return None
    size = degree + 1
    # Normal equations: (X^T X) c = X^T y
    powers = [sum(x**p for x in xs) for p in range(2 * degree + 1)]
    matrix = [[powers[i + j] for j in range(size)] for i in range(size)]
    rhs = [sum(y * (x**i) for x, y in zip(xs, ys)) for i in range(size)]
    return _solve(matrix, rhs)


def _score(
    xs: Sequence[float], ys: Sequence[float], predict: Callable[[float], float]
) -> tuple[float, float, int]:
    predicted = [predict(x) for x in xs]
    mean = sum(ys) / len(ys)
    ss_tot = sum((y - mean) ** 2 for y in ys)
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, predicted))
    r_squared = 1.0 if ss_tot == 0 else 1 - ss_res / ss_tot

    max_rel = 0.0
    exact = 0
    for actual, guess in zip(ys, predicted):
        if abs(actual - guess) < 0.5 and round(guess) == round(actual):
            exact += 1
        denominator = abs(actual) if abs(actual) > 1e-9 else 1.0
        max_rel = max(max_rel, abs(actual - guess) / denominator)
    return r_squared, max_rel, exact


def _polynomial_fit(xs, ys, degree: int, name: str) -> Fit | None:
    coefficients = polyfit(xs, ys, degree)
    if coefficients is None:
        return None

    def predict(x: float) -> float:
        return sum(c * (x**i) for i, c in enumerate(coefficients))

    r_squared, max_rel, exact = _score(xs, ys, predict)
    terms = []
    for i, c in enumerate(coefficients):
        if i == 0:
            terms.append(f"{c:.6g}")
        elif i == 1:
            terms.append(f"{c:+.6g}*L")
        else:
            terms.append(f"{c:+.6g}*L^{i}")
    return Fit(name, "xp(L) = " + " ".join(terms), list(coefficients), r_squared, max_rel, exact, len(xs))


def _exponential_fit(xs, ys) -> Fit | None:
    """xp = a * r^L, fitted on a semi-log scale."""
    pairs = [(x, y) for x, y in zip(xs, ys) if y > 0]
    if len(pairs) < 3:
        return None
    log_fit = polyfit([x for x, _ in pairs], [math.log(y) for _, y in pairs], 1)
    if log_fit is None:
        return None
    intercept, slope = log_fit
    a, r = math.exp(intercept), math.exp(slope)

    def predict(x: float) -> float:
        return a * (r**x)

    r_squared, max_rel, exact = _score(xs, ys, predict)
    return Fit(
        "exponential",
        f"xp(L) = {a:.6g} * {r:.6g}^L",
        [a, r],
        r_squared,
        max_rel,
        exact,
        len(xs),
    )


def _power_fit(xs, ys) -> Fit | None:
    """xp = a * L^b, fitted on a log-log scale."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x > 0 and y > 0]
    if len(pairs) < 3:
        return None
    log_fit = polyfit(
        [math.log(x) for x, _ in pairs], [math.log(y) for _, y in pairs], 1
    )
    if log_fit is None:
        return None
    intercept, slope = log_fit
    a, b = math.exp(intercept), slope

    def predict(x: float) -> float:
        return a * (x**b) if x > 0 else 0.0

    r_squared, max_rel, exact = _score(xs, ys, predict)
    return Fit(
        "power", f"xp(L) = {a:.6g} * L^{b:.6g}", [a, b], r_squared, max_rel, exact, len(xs)
    )


def _runescape_fit(xs, ys) -> Fit | None:
    """The classic MMO staple: xp(L) = floor(sum_{n<L} floor(n + a*b^(n/c)) / d).

    Only the standard parameterisation is tested — it either reproduces the
    table exactly or it is the wrong family, so there is nothing to optimise.
    """
    a, b, c, d = 300.0, 2.0, 7.0, 4.0

    def predict(level: float) -> float:
        total = 0.0
        for n in range(1, int(level)):
            total += math.floor(n + a * (b ** (n / c)))
        return math.floor(total / d)

    if not xs or max(xs) > 200:
        return None
    r_squared, max_rel, exact = _score(xs, ys, predict)
    return Fit(
        "runescape-style",
        "xp(L) = floor( sum_{n=1}^{L-1} floor(n + 300*2^(n/7)) / 4 )",
        [a, b, c, d],
        r_squared,
        max_rel,
        exact,
        len(xs),
    )


def fit_all(table: XpTable) -> list[Fit]:
    """Fit every model against a table's cumulative curve, best first."""
    points = table.totals()
    if len(points) < 3:
        return []
    xs = [float(level) for level, _ in points]
    ys = [float(value) for _, value in points]

    fits = [
        _polynomial_fit(xs, ys, 1, "linear"),
        _polynomial_fit(xs, ys, 2, "quadratic"),
        _polynomial_fit(xs, ys, 3, "cubic"),
        _exponential_fit(xs, ys),
        _power_fit(xs, ys),
        _runescape_fit(xs, ys),
    ]
    found = [fit for fit in fits if fit is not None]
    # Exact reproduction wins outright; otherwise rank by fit quality.
    found.sort(key=lambda f: (-f.exact_matches, f.max_relative_error, -f.r_squared))
    return found


def best_fit(table: XpTable) -> Fit | None:
    fits = fit_all(table)
    return fits[0] if fits else None
