from dataclasses import dataclass

from ledger.units import require_name


@dataclass(frozen=True)
class PublicTerminals:
    public: tuple[str, ...]
    private: tuple[str, ...]


def validate_terminal_names(names):
    if isinstance(names, (str, bytes)):
        raise ValueError('expected an ordered sequence of terminal names')
    names = tuple(require_name(name, 'terminal name') for name in names)
    if len(names) != len(set(names)):
        raise ValueError('public terminal names must be unique')
    return names


def select_public_terminals(revision, names):
    public = validate_terminal_names(names)
    points = revision.points
    unknown = set(public).difference(points)
    if unknown:
        raise ValueError(f'unknown terminal names: {sorted(unknown)!r}')
    declared = set(public)
    return PublicTerminals(public, tuple(point for point in points if point not in declared))
