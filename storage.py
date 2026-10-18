"""Persistent PostgreSQL in production, SQLite only for local development."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import class_row

DATA = Path(os.environ.get('ANKIMIO_DATA', Path(__file__).parent / 'data'))
DATA.mkdir(parents=True, exist_ok=True)

class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key,int) else super().__getitem__(key)

class PostgresConnection:
    def __init__(self, connection): self.connection=connection
    def execute(self, query, parameters=None):
        if parameters is not None: query=query.replace('%','%%').replace('?','%s')
        return self.connection.execute(query,parameters)
    def executemany(self, query, parameters):
        cursor=self.connection.cursor()
        cursor.executemany(query.replace('%','%%').replace('?','%s'),parameters)
        return cursor


def using_postgres(): return bool(os.environ.get('DATABASE_URL','').strip())

def postgres_options():
    try:
        options=conninfo_to_dict(os.environ['DATABASE_URL'])
    except (KeyError,psycopg.Error):
        raise RuntimeError('DATABASE_URL no es una conexión PostgreSQL válida. Configúrala de forma segura en Render.') from None
    host=options.get('host','')
    local=host in ('localhost','127.0.0.1','::1') or host.startswith('/')
    if not local or os.environ.get('RENDER')=='true':
        options['sslmode']='verify-full'
        options.setdefault('sslrootcert','system')
    options['connect_timeout']='10'
    options['options']='-c search_path=ankimio -c statement_timeout=15000 -c lock_timeout=5000'
    return options

@contextmanager
def db():
    if using_postgres():
        connection=psycopg.connect(**postgres_options(),row_factory=class_row(Row),prepare_threshold=None)
        try:
            with connection.transaction(): yield PostgresConnection(connection)
        finally: connection.close()
    else:
        if os.environ.get('RENDER')=='true' or os.environ.get('ANKIMIO_REQUIRE_DATABASE')=='1':
            raise RuntimeError('Falta DATABASE_URL. Configura PostgreSQL en Render para evitar que se pierdan los mazos. No se usará almacenamiento temporal.')
        connection=sqlite3.connect(DATA/'study.db',timeout=5)
        connection.row_factory=sqlite3.Row
        try:
            with connection: yield connection
        finally: connection.close()

def initialize_storage():
    with db() as connection:
        if using_postgres():
            connection.execute('SELECT pg_advisory_xact_lock(18001742)')
            connection.execute('CREATE SCHEMA IF NOT EXISTS ankimio')
        binary='BYTEA' if using_postgres() else 'BLOB'
        connection.execute(f'CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY,mime TEXT,content {binary})')
        connection.execute('CREATE TABLE IF NOT EXISTS decks(id TEXT PRIMARY KEY,name TEXT)')
        connection.execute('CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY,deck TEXT,front TEXT,back TEXT)')
        connection.execute('CREATE INDEX IF NOT EXISTS cards_deck_index ON cards(deck)')
