from dataclasses import dataclass

from station.publish import StationArtifact, decode_station_artifact


@dataclass(frozen=True)
class AcceptedStationPair:
    first: StationArtifact
    second: StationArtifact

    @property
    def artifacts(self):
        return self.first, self.second

    @property
    def artifact_ids(self):
        return self.first.artifact_id, self.second.artifact_id


def accept_station_pair(first_payload, second_payload):
    first = decode_station_artifact(first_payload)
    second = decode_station_artifact(second_payload)
    if first.trial_id != second.trial_id or first.unit != second.unit:
        raise ValueError('station artifacts must belong to the same trial and unit')
    if first.station == second.station:
        raise ValueError('a comparison requires two different stations')
    return AcceptedStationPair(first, second)
