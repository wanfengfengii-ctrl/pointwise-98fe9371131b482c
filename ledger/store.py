import sqlite3


def open_ledger(path):
    db = sqlite3.connect(path)
    try:
        db.execute('PRAGMA foreign_keys = ON')
        initialize_ledger_schema(db)
    except BaseException:
        db.close()
        raise
    return db


def initialize_ledger_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS trials (
            id TEXT PRIMARY KEY,
            ticket TEXT NOT NULL UNIQUE,
            unit TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trial_stations (
            trial_id TEXT NOT NULL REFERENCES trials(id),
            station TEXT NOT NULL,
            PRIMARY KEY (trial_id, station)
        );
        CREATE TABLE IF NOT EXISTS revisions (
            id TEXT PRIMARY KEY,
            trial_id TEXT NOT NULL,
            station TEXT NOT NULL,
            name TEXT NOT NULL,
            parent_id TEXT REFERENCES revisions(id),
            evidence TEXT NOT NULL,
            UNIQUE (trial_id, station, name),
            FOREIGN KEY (trial_id, station) REFERENCES trial_stations(trial_id, station)
        );
        CREATE TABLE IF NOT EXISTS station_artifacts (
            id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL REFERENCES revisions(id),
            payload BLOB NOT NULL
        );
    ''')


def _read_registration(db, row):
    if row is None:
        return None
    trial_id, ticket, unit = row
    stations = tuple(item[0] for item in db.execute(
        'SELECT station FROM trial_stations WHERE trial_id = ? ORDER BY station',
        (trial_id,),
    ))
    return trial_id, ticket, unit, stations


def insert_trial_registration(db, trial_id, ticket, unit, stations):
    with db:
        inserted = db.execute('''
            INSERT INTO trials (id, ticket, unit) VALUES (?, ?, ?)
            ON CONFLICT(ticket) DO NOTHING
        ''', (trial_id, ticket, unit)).rowcount
        if inserted:
            db.executemany('INSERT INTO trial_stations VALUES (?, ?)',
                           ((trial_id, station) for station in stations))
        row = db.execute('SELECT id, ticket, unit FROM trials WHERE ticket = ?', (ticket,)).fetchone()
        registration = _read_registration(db, row)
        if registration != (trial_id, ticket, unit, stations):
            raise ValueError('the ticket is already registered with different stations or unit')
    return registration


def fetch_trial_registration(db, trial_id):
    row = db.execute('SELECT id, ticket, unit FROM trials WHERE id = ?', (trial_id,)).fetchone()
    return _read_registration(db, row)


def insert_revision_batch(db, revision_id, trial_id, station, name, parent_id, evidence):
    with db:
        inserted = db.execute('''
            INSERT INTO revisions (id, trial_id, station, name, parent_id, evidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(trial_id, station, name) DO NOTHING
        ''', (revision_id, trial_id, station, name, parent_id, evidence)).rowcount
        if not inserted:
            raise ValueError('revision name already exists for this station and trial')


def fetch_revision_batch(db, revision_id):
    return db.execute('''
        SELECT revisions.id, revisions.trial_id, revisions.station, trials.unit,
               revisions.name, revisions.parent_id, revisions.evidence
        FROM revisions JOIN trials ON trials.id = revisions.trial_id
        WHERE revisions.id = ?
    ''', (revision_id,)).fetchone()
