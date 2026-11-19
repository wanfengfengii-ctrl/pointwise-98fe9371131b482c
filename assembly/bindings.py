from dataclasses import dataclass

from assembly.intake import AcceptedStationPair


TerminalRef = tuple[str, str]


@dataclass(frozen=True)
class TerminalBindings:
    coordinates: tuple[TerminalRef, ...]
    pairs: tuple[tuple[str, str], ...]
    links: tuple[tuple[int, int], ...]


def resolve_terminal(bindings, reference):
    if not isinstance(reference, (tuple, list)) or len(reference) != 2:
        raise ValueError('terminal references must contain a station and terminal name')
    endpoint = tuple(reference)
    try:
        return bindings.coordinates.index(endpoint)
    except ValueError as error:
        raise ValueError(f'undeclared comparison terminal: {endpoint!r}') from error


def bind_terminals(pair: AcceptedStationPair, correspondences):
    coordinates = tuple((artifact.station, name) for artifact in pair.artifacts
                        for name in artifact.terminals)
    directory = TerminalBindings(coordinates, (), ())
    pairs = []
    links = []
    for item in correspondences:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError('each binding must contain a first and second station terminal')
        first, second = item
        links.append((resolve_terminal(directory, (pair.first.station, first)),
                      resolve_terminal(directory, (pair.second.station, second))))
        pairs.append((first, second))
    return TerminalBindings(coordinates, tuple(pairs), tuple(links))
