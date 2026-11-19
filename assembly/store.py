import sqlite3

from records.finalize import initialize_archive


def open_review_store(path):
    db = sqlite3.connect(path)
    try:
        db.execute('PRAGMA foreign_keys = ON')
        initialize_review_schema(db)
    except BaseException:
        db.close()
        raise
    return db


def initialize_review_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS accepted_artifacts (
            id TEXT PRIMARY KEY,
            payload BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS comparison_requests (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            first_artifact_id TEXT NOT NULL REFERENCES accepted_artifacts(id),
            second_artifact_id TEXT NOT NULL REFERENCES accepted_artifacts(id),
            conditions TEXT NOT NULL,
            UNIQUE (id, first_artifact_id, second_artifact_id)
        );
    ''')
    initialize_archive(db)


def save_comparison_bundle(db, name, first, second, conditions):
    with db:
        for artifact_id, payload in (first, second):
            db.execute('''
                INSERT INTO accepted_artifacts (id, payload) VALUES (?, ?)
                ON CONFLICT(id) DO NOTHING
            ''', (artifact_id, payload))
            persisted = db.execute('SELECT payload FROM accepted_artifacts WHERE id = ?',
                                   (artifact_id,)).fetchone()[0]
            if persisted != payload:
                raise ValueError('an accepted artifact ID already identifies different bytes')
        request = db.execute('''
            INSERT INTO comparison_requests (name, first_artifact_id, second_artifact_id, conditions)
            VALUES (?, ?, ?, ?)
        ''', (name, first[0], second[0], conditions))
    return request.lastrowid


def load_comparison_bundle(db, request_id):
    return db.execute('''
        SELECT task.name, task.conditions, first.id, first.payload, second.id, second.payload
        FROM comparison_requests AS task
        JOIN accepted_artifacts AS first ON first.id = task.first_artifact_id
        JOIN accepted_artifacts AS second ON second.id = task.second_artifact_id
        WHERE task.id = ?
    ''', (request_id,)).fetchone()
