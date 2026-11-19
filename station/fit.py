from dataclasses import dataclass
from fractions import Fraction

from ledger.revisions import load_revision
from station.constraints import AffineSpace, Vector, dot, solve_affine_system


@dataclass(frozen=True)
class StationFit:
    revision_id: str
    feasible: bool
    residual: Fraction | None


@dataclass(frozen=True)
class Quadratic:
    # In homogeneous coordinates u = (x, 1), the value is u.T @ gram @ u.
    gram: tuple[Vector, ...]

    @property
    def dimension(self):
        return len(self.gram) - 1

    def evaluate(self, point):
        homogeneous = (*point, Fraction(1))
        return dot(homogeneous, tuple(dot(row, homogeneous) for row in self.gram))

    def transform(self, columns):
        images = tuple(tuple(dot(row, column) for row in self.gram) for column in columns)
        return Quadratic(tuple(tuple(dot(column, image) for image in images) for column in columns))

    def plus(self, other):
        return Quadratic(tuple(tuple(a + b for a, b in zip(left, right, strict=True))
                               for left, right in zip(self.gram, other.gram, strict=True)))

    def is_positive_semidefinite(self):
        remainder = [list(row) for row in self.gram]
        size = len(remainder)
        if any(len(row) != size for row in remainder):
            return False
        if any(remainder[i][j] != remainder[j][i] for i in range(size) for j in range(i)):
            return False
        for k in range(size):
            pivot = remainder[k][k]
            if pivot < 0:
                return False
            if pivot == 0:
                if any(remainder[i][k] for i in range(k + 1, size)):
                    return False
                continue
            for i in range(k + 1, size):
                for j in range(k + 1, size):
                    remainder[i][j] -= remainder[i][k] * remainder[k][j] / pivot
        return True


def row_coordinates(row, points):
    terms = dict(row.terms)
    return tuple(terms.get(point, Fraction(0)) for point in points)


def exact_equations(revision, points):
    return tuple((row_coordinates(row, points), row.target) for row in revision.exact_rows)


def observation_cost(revision, points):
    return observation_cost_from_rows(revision.observations, points)


def observation_cost_from_rows(rows, points):
    width = len(points) + 1
    gram = [[Fraction(0) for _ in range(width)] for _ in range(width)]
    for row in rows:
        coefficients = (*row_coordinates(row, points), -row.target)
        for i, left in enumerate(coefficients):
            for j, right in enumerate(coefficients):
                gram[i][j] += row.weight * left * right
    return Quadratic(tuple(tuple(row) for row in gram))


def zero_quadratic(dimension):
    return Quadratic(tuple(tuple(Fraction(0) for _ in range(dimension + 1))
                           for _ in range(dimension + 1)))


def minimum_on_space(cost, space):
    columns = tuple((*direction, Fraction(0)) for direction in space.directions)
    restricted = cost.transform((*columns, (*space.origin, Fraction(1))))
    size = restricted.dimension
    stationary = solve_affine_system(size, tuple((row[:-1], -row[-1])
                                                 for row in restricted.gram[:-1]))
    if stationary is None:
        raise ArithmeticError('a squared-residual objective has inconsistent normal equations')
    origin = space.point(stationary.origin)
    lifted = []
    for direction in stationary.directions:
        parameters = tuple(a + b for a, b in zip(stationary.origin, direction, strict=True))
        lifted.append(tuple(a - b for a, b in zip(space.point(parameters), origin, strict=True)))
    return AffineSpace(origin, tuple(lifted))


def fit_revision(revision):
    points = revision.points
    space = solve_affine_system(len(points), exact_equations(revision, points))
    if space is None:
        return StationFit(revision.revision_id, False, None)
    cost = observation_cost(revision, points)
    optimum = minimum_on_space(cost, space)
    return StationFit(revision.revision_id, True, cost.evaluate(optimum.origin))


def station_check(db, revision_id):
    return fit_revision(load_revision(db, revision_id))
