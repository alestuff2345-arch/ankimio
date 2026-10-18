"""Copy a surviving local database into an EMPTY PostgreSQL database.

Usage: DATABASE_URL=<set securely in environment> python migrate_sqlite.py data/study.db
Does not modify or delete the SQLite source. Credentials are never printed.
"""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from storage import db, initialize_storage, using_postgres

def migrate(source_path):
    if not using_postgres():raise RuntimeError('Configura DATABASE_URL antes de migrar.')
    path=Path(source_path).resolve()
    if not path.is_file():raise RuntimeError('No existe el archivo SQLite indicado.')
    initialize_storage()
    counts={}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as source,db() as target:
        source.execute('BEGIN')
        target.execute('SELECT pg_advisory_xact_lock(18001742)')
        for table in ('decks','cards','media','card_progress','review_events'):
            if target.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:
                raise RuntimeError('La base de destino no está vacía. La migración se canceló sin sobrescribir datos.')
        existing={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'decks','cards'}<=existing:raise RuntimeError('El archivo no es una base de Ankimio.')
        tables=[('decks','id,name'),('media','id,mime,content'),('cards','id,deck,front,back')]
        for table,columns in (('card_progress','card_id,state'),('review_events','id,card_id,rating,previous_state,undone')):
            if table in existing:tables.append((table,columns))
        for table,columns in tables:
            counts[table]=0
            if table not in existing:continue
            cursor=source.execute(f'SELECT {columns} FROM {table}')
            placeholders=','.join('?' for _ in columns.split(','))
            while batch:=cursor.fetchmany(250):
                target.executemany(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})',batch)
                counts[table]+=len(batch)
    return counts

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');args=parser.parse_args()
    try:
        counts=migrate(args.source)
        print('Migración completada:',counts)
    except Exception as error:
        # Driver errors can contain endpoint details; do not echo them.
        message=str(error) if isinstance(error,RuntimeError) else 'No se pudo migrar. Revisa la conexión y los permisos de PostgreSQL.'
        parser.exit(1,message+'\n')
