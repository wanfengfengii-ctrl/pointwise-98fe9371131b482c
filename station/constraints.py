from dataclasses import dataclass
from fractions import Fraction


Vector = tuple[Fraction, ...]
Equation = tuple[Vector, Fraction]


def dot(left, right):
    return sum((a * b for a, b in zip(left, right, strict=True)), Fraction(0))


def identity_vector(size, position):
    return tuple(Fraction(index == position) for index in range(size))


@dataclass(frozen=True)
class AffineSpace:
    origin: Vector
    directions: tuple[Vector, ...]

    def point(self, parameters):
        parameters = tuple(parameters)
        if len(parameters) != len(self.directions):
            raise ValueError('wrong number of affine parameters')
        return tuple(base + dot(parameters, tuple(direction[index] for direction in self.directions))
                     for index, base in enumerate(self.origin))


def reduce_equations(size, equations):
    matrix = []
    for coefficients, target in equations:
        if len(coefficients) != size:
            raise ValueError('wrong equation dimension')
        matrix.append(tuple(Fraction(value) for value in (*coefficients, target)))

    pivots = []
    for column in range(size):
        rank = len(pivots)
        found = next((index for index in range(rank, len(matrix)) if matrix[index][column]), None)
        if found is None:
            continue
        matrix[rank], matrix[found] = matrix[found], matrix[rank]
        pivot = matrix[rank][column]
        matrix[rank] = tuple(value / pivot for value in matrix[rank])
        for index, row in enumerate(matrix):
            if index != rank and row[column]:
                matrix[index] = tuple(value - row[column] * factor
                                      for value, factor in zip(row, matrix[rank], strict=True))
        pivots.append(column)

    rank = len(pivots)
    if any(row[-1] for row in matrix[rank:]):
        return None
    return tuple(matrix[:rank]), tuple(pivots)


def solve_affine_system(size, equations):
    reduced = reduce_equations(size, equations)
    if reduced is None:
        return None
    rows, pivots = reduced
    pivot_rows = dict(zip(pivots, rows, strict=True))
    origin = tuple(pivot_rows[index][-1] if index in pivot_rows else Fraction(0)
                   for index in range(size))
    directions = []
    for free in range(size):
        if free in pivot_rows:
            continue
        directions.append(tuple(-pivot_rows[index][free] if index in pivot_rows
                                else Fraction(index == free) for index in range(size)))
    return AffineSpace(origin, tuple(directions))
