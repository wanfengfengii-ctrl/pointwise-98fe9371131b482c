import hashlib
import json
from dataclasses import dataclass

from ledger.store import fetch_trial_registration, insert_trial_registration
from ledger.units import require_name, validate_trial_unit


@dataclass(frozen=True)
class TrialRegistration:
    trial_id: str
    ticket: str
    unit: str
    stations: tuple[str, str]


def initialize_trial(db, ticket, unit, stations):
    ticket = require_name(ticket, 'ticket')
    unit = validate_trial_unit(unit)
    if isinstance(stations, (str, bytes)):
        raise ValueError('expected a sequence of two station names')
    stations = tuple(sorted(require_name(station, 'station') for station in stations))
    if len(stations) != 2 or len(set(stations)) != 2:
        raise ValueError('a trial requires two distinct stations')
    identity = json.dumps([ticket, unit, stations], separators=(',', ':')).encode('ascii')
    trial_id = hashlib.sha256(identity).hexdigest()
    return TrialRegistration(*insert_trial_registration(db, trial_id, ticket, unit, stations))


def require_trial_station(db, trial_id, station):
    registration = fetch_trial_registration(db, require_name(trial_id, 'trial ID'))
    if registration is None:
        raise KeyError(trial_id)
    trial = TrialRegistration(*registration)
    if require_name(station, 'station') not in trial.stations:
        raise ValueError('station is not registered for this trial')
    return trial
