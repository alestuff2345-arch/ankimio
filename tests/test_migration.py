import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from test_config import configure_test_database
configure_test_database()
from storage import db
from migrate_sqlite import migrate

@unittest.skipUnless(os.environ.get('ANKIMIO_TEST_DATABASE_URL'),'Requires a dedicated PostgreSQL test database')
class Migration(unittest.TestCase):
    def setUp(self):
        with db() as c:
            for table in ('cards','media','decks'):c.execute(f'DELETE FROM {table}')

    def source(self,path,duplicate=False):
        c=sqlite3.connect(path)
        try:
            c.executescript('CREATE TABLE decks(id TEXT,name TEXT); CREATE TABLE cards(id TEXT,deck TEXT,front TEXT,back TEXT); CREATE TABLE media(id TEXT,mime TEXT,content BLOB);')
            c.execute('INSERT INTO decks VALUES (?,?)',('deck-one','Conservar'))
            c.execute('INSERT INTO cards VALUES (?,?,?,?)',('card-one','deck-one','Pregunta editada','Respuesta'))
            if duplicate:c.execute('INSERT INTO cards SELECT * FROM cards')
            c.execute('INSERT INTO media VALUES (?,?,?)',('image-one','image/png',b'\x89PNG\x00fixture'))
            c.commit()
        finally:c.close()

    def test_copy_preserves_ids_edits_images_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'study.db';self.source(path);before=path.read_bytes()
            self.assertEqual(migrate(path),{'decks':1,'media':1,'cards':1})
            self.assertEqual(path.read_bytes(),before)
        with db() as c:
            self.assertEqual(c.execute('SELECT front FROM cards WHERE id=?',('card-one',)).fetchone()['front'],'Pregunta editada')
            self.assertEqual(c.execute('SELECT content FROM media').fetchone()['content'],b'\x89PNG\x00fixture')

    def test_nonempty_destination_is_not_overwritten(self):
        with db() as c:c.execute('INSERT INTO decks VALUES (?,?)',('existing','No sobrescribir'))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'study.db';self.source(path)
            with self.assertRaisesRegex(RuntimeError,'no está vacía'):migrate(path)
        with db() as c:self.assertEqual(c.execute('SELECT id FROM decks').fetchone()['id'],'existing')

    def test_copy_preserves_optional_review_progress_and_undo(self):
        import json
        from datetime import date
        from review import empty_progress,next_progress,undo_review
        event='a'*32
        previous=empty_progress()
        state=next_progress(previous,'good',date(2026,1,1),event)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'study.db';self.source(path)
            with sqlite3.connect(path) as source:
                source.execute('CREATE TABLE card_progress(card_id TEXT,state TEXT)')
                source.execute('CREATE TABLE review_events(id TEXT,card_id TEXT,rating TEXT,previous_state TEXT,undone INTEGER)')
                source.execute('INSERT INTO card_progress VALUES (?,?)',('card-one',json.dumps(state)))
                source.execute('INSERT INTO review_events VALUES (?,?,?,?,0)',(event,'card-one','good',json.dumps(previous)))
            counts=migrate(path)
            self.assertEqual(counts['card_progress'],1)
            self.assertEqual(counts['review_events'],1)
        with db() as c:
            self.assertEqual(json.loads(c.execute('SELECT state FROM card_progress').fetchone()['state']),state)
        restored=undo_review('deck-one','card-one',event,{})['progress']
        self.assertEqual(restored['status'],'new')
        self.assertIsNone(restored['revision'])

    def test_copy_error_rolls_back_all_destination_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'study.db';self.source(path,duplicate=True)
            with self.assertRaises(Exception):migrate(path)
        with db() as c:
            for table in ('cards','media','decks'):self.assertEqual(c.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)
