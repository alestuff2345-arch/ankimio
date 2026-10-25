"""Persistent PostgreSQL in production, SQLite only for local development."""
import os
import sqlite3
import ssl
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import class_row
from psycopg_pool import ConnectionPool

DATA = Path(os.environ.get('ANKIMIO_DATA', Path(__file__).parent / 'data'))
DATA.mkdir(parents=True, exist_ok=True)

class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key,int) else super().__getitem__(key)

class PostgresConnection:
    def __init__(self, connection):
        self.connection=connection
        self.active=True
    def check_active(self):
        if not self.active: raise psycopg.InterfaceError('Database context is closed')
    def execute(self, query, parameters=None):
        self.check_active()
        if parameters is not None: query=query.replace('%','%%').replace('?','%s')
        return self.connection.execute(query,parameters)
    def executemany(self, query, parameters):
        self.check_active()
        cursor=self.connection.cursor()
        cursor.executemany(query.replace('%','%%').replace('?','%s'),parameters)
        return cursor


def using_postgres(): return bool(os.environ.get('DATABASE_URL','').strip())

def trusted_ca_file(options):
    configured=os.environ.get('DATABASE_SSLROOTCERT') or options.get('sslrootcert')
    if configured and configured!='system':
        candidates=[Path(configured).expanduser()]
    else:
        # The OpenSSL shipped inside psycopg-binary may use a different
        # default certificate location from the host. Pass the actual bundle.
        system=ssl.get_default_verify_paths().cafile
        candidates=[Path(system)] if system else []
        candidates.extend((Path('/etc/ssl/certs/ca-certificates.crt'),Path('/etc/pki/tls/certs/ca-bundle.crt')))
    for path in candidates:
        if not path.is_file():continue
        try:ssl.create_default_context(cafile=str(path))
        except (ssl.SSLError,OSError):
            raise RuntimeError('PG_TLS_CA_FILE: el archivo de certificados no es válido. Configura DATABASE_SSLROOTCERT con el certificado CA descargado desde Supabase.') from None
        return str(path)
    raise RuntimeError('PG_TLS_CA_FILE: no se encontró el archivo CA. Añade el certificado de Supabase como Secret File y configura su ruta en DATABASE_SSLROOTCERT.')

def postgres_options():
    try:
        options=conninfo_to_dict(os.environ['DATABASE_URL'])
    except (KeyError,psycopg.Error):
        raise RuntimeError('DATABASE_URL no es una conexión PostgreSQL válida. Configúrala de forma segura en Render.') from None
    host=options.get('host','')
    local=host in ('localhost','127.0.0.1','::1') or host.startswith('/')
    if not local or os.environ.get('RENDER')=='true':
        options['sslmode']='verify-full'
        options['sslrootcert']=trusted_ca_file(options)
    options['connect_timeout']='10'
    return options

_pool = None
_pool_key = None
_pool_lock = threading.Lock()

def postgres_pool():
    """A small, lazy pool per worker; never share connections across requests."""
    global _pool, _pool_key
    key = (os.getpid(), os.environ.get('DATABASE_URL'), os.environ.get('DATABASE_SSLROOTCERT'))
    with _pool_lock:
        if _pool is None or _pool_key != key:
            options = postgres_options()
            previous = _pool
            _pool = ConnectionPool(
                kwargs=dict(options, row_factory=class_row(Row), prepare_threshold=None),
                min_size=0, max_size=4, timeout=10, max_idle=60,
                max_lifetime=300, reconnect_timeout=10, open=True)
            _pool_key = key
            if previous is not None: previous.close()
        return _pool

@contextmanager
def db():
    if using_postgres():
        with postgres_pool().connection() as connection:
            with connection.transaction():
                # Set these after connecting: managed poolers may reject
                # PostgreSQL startup `options`. SET LOCAL is pooler-safe.
                connection.execute("SET LOCAL search_path TO ankimio; "
                                   "SET LOCAL statement_timeout = '15s'; "
                                   "SET LOCAL lock_timeout = '5s'")
                wrapper=PostgresConnection(connection)
                try: yield wrapper
                finally: wrapper.active=False
    else:
        if os.environ.get('RENDER')=='true' or os.environ.get('ANKIMIO_REQUIRE_DATABASE')=='1':
            raise RuntimeError('Falta DATABASE_URL. Configura PostgreSQL en Render para evitar que se pierdan los mazos. No se usará almacenamiento temporal.')
        connection=sqlite3.connect(DATA/'study.db',timeout=5)
        connection.row_factory=sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection: yield connection
        finally: connection.close()

def database_connection_hint(error):
    """Return only fixed messages; never echo a DSN or driver credentials."""
    detail=str(error).lower();state=getattr(error,'sqlstate',None)
    if 'tenant or user not found' in detail:
        return 'PG_USER: el pooler no reconoce el usuario. Copia el usuario completo de Connect → Session pooler, incluida la referencia del proyecto.'
    if state=='28P01' or 'password authentication failed' in detail:
        return 'PG_AUTH: la contraseña de la base no fue aceptada. Sustituye [YOUR-PASSWORD] y codifica los caracteres especiales de la contraseña en la URI.'
    if 'could not translate host' in detail or 'failed to resolve' in detail or 'name or service not known' in detail:
        return 'PG_DNS: no se encontró el servidor. Vuelve a copiar el hostname de Session pooler, sin espacios ni marcadores pendientes.'
    if 'does not match host' in detail or 'hostname mismatch' in detail:
        return 'PG_TLS_HOST: el certificado no corresponde al servidor. Copia el hostname exacto del Session pooler en Connect, sin sustituirlo por una IP.'
    if 'certificate verify failed' in detail or 'self-signed certificate' in detail or 'unable to get local issuer' in detail:
        return 'PG_TLS_TRUST: no se pudo verificar la cadena de confianza. Descarga el certificado CA desde la configuración de Supabase y configura su ruta en DATABASE_SSLROOTCERT como Secret File de Render.'
    if 'root certificate file' in detail or 'system root certificate' in detail:
        return 'PG_TLS_CA_FILE: el controlador no encontró su archivo CA. Configura DATABASE_SSLROOTCERT con la ruta al certificado de confianza de Supabase.'
    if 'certificate' in detail or 'ssl' in detail or 'tls' in detail:
        return 'PG_TLS: falló la conexión TLS o la verificación del certificado. Usa el Session pooler oficial y su certificado de confianza; no desactives la verificación.'
    if 'timeout' in detail or 'timed out' in detail or 'network is unreachable' in detail or 'connection refused' in detail:
        return 'PG_NETWORK: no se pudo alcanzar PostgreSQL. Comprueba que el proyecto esté activo y usa Session pooler compatible con IPv4, hostname terminado en pooler.supabase.com, puerto 5432.'
    if state=='42501' or 'permission denied' in detail:
        return 'PG_PERMISSIONS: el usuario no tiene permisos para crear o usar el esquema ankimio. Revisa los permisos de la conexión PostgreSQL.'
    if 'unsupported startup parameter' in detail:
        return 'PG_POOLER: el pooler rechazó un parámetro de conexión. Usa la URI de Session pooler sin opciones de inicio adicionales.'
    return 'PG_CONNECTION: PostgreSQL rechazó la conexión o la inicialización. Revisa la URI de Session pooler, el estado del proyecto y los permisos del usuario.'

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
        connection.execute('CREATE TABLE IF NOT EXISTS card_progress('
                           'card_id TEXT PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,state TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS review_events('
                           'id TEXT PRIMARY KEY,card_id TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,'
                           'rating TEXT NOT NULL,previous_state TEXT NOT NULL,undone INTEGER NOT NULL DEFAULT 0)')
        connection.execute('CREATE INDEX IF NOT EXISTS review_events_card_index ON review_events(card_id)')
        connection.execute('CREATE TABLE IF NOT EXISTS libraries(id TEXT PRIMARY KEY,name TEXT NOT NULL)')
        connection.execute('INSERT INTO libraries (id,name) VALUES (?,?) ON CONFLICT (id) DO NOTHING',('main','Mis mazos'))
        connection.execute('CREATE TABLE IF NOT EXISTS deck_libraries('
                           'deck_id TEXT PRIMARY KEY REFERENCES decks(id) ON DELETE CASCADE,'
                           'library_id TEXT NOT NULL REFERENCES libraries(id))')
        connection.execute('CREATE INDEX IF NOT EXISTS deck_libraries_library_index ON deck_libraries(library_id)')
        assign_unmapped_decks(connection)

def assign_unmapped_decks(connection):
    connection.execute('INSERT INTO deck_libraries (deck_id,library_id) '
                       'SELECT id,? FROM decks WHERE NOT EXISTS '
                       '(SELECT 1 FROM deck_libraries WHERE deck_id=decks.id)',('main',))
