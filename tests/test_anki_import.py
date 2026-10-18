"""Integration fixtures exported by Anki itself, not handcrafted ZIPs."""
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from anki.collection import Collection, ExportAnkiPackageOptions
from test_config import configure_test_database
configure_test_database()
from app import app

class AnkiPackageImport(unittest.TestCase):
    def package(self, legacy=False, apkg=False):
        with tempfile.TemporaryDirectory() as tmp:
            col=Collection(str(Path(tmp)/'collection.anki2'))
            try:
                deck=col.decks.id('Importación real::Geografía')
                note=col.new_note(col.models.by_name('Basic'))
                note['Front']='Capital de Perú'; note['Back']='Lima'
                col.add_note(note,deck)
                reverse=col.new_note(col.models.by_name('Basic (and reversed card)'))
                reverse['Front']='Hola';reverse['Back']='Hello';col.add_note(reverse,deck)
                cloze=col.new_note(col.models.by_name('Cloze'))
                cloze['Text']='{{c1::Lima}} está en {{c2::Perú}}.'
                col.add_note(cloze,deck)
                path=Path(tmp)/'example.colpkg'
                if apkg:
                    col.export_anki_package(out_path=str(path),options=ExportAnkiPackageOptions(with_scheduling=True,with_media=False,legacy=legacy),limit=None)
                else:
                    col.export_collection_package(str(path),include_media=False,legacy=legacy)
                return path.read_bytes()
            finally: col.close()

    def assert_import(self, raw, filename):
        client=app.test_client()
        before={d['id'] for d in client.get('/api/decks').json}
        r=client.post('/api/import',data={'file':(io.BytesIO(raw),filename)})
        self.assertEqual(r.status_code,200,r.json)
        self.assertEqual(r.json['count'],5)
        decks=client.get('/api/decks').json
        imported=[d for d in decks if d['name']=='Importación real::Geografía' and d['id'] not in before]
        self.assertTrue(imported)
        cards=client.get('/api/decks/'+imported[-1]['id']+'/cards').json
        self.assertEqual(len(cards),5)
        return cards

    def test_modern_compressed_colpkg(self):
        raw=self.package()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertIn('collection.anki21b',z.namelist())
        cards=self.assert_import(raw,'modern.colpkg')
        self.assertTrue(any(c['front'].endswith('Capital de Perú') and c['back'].strip()=='Lima' for c in cards))
        self.assertTrue(any(c['front'].endswith('Hello') and c['back'].strip()=='Hola' for c in cards))
        clozes=[c for c in cards if 'cloze' in c['front']]
        self.assertEqual(len(clozes),2)
        self.assertTrue(any('Perú' in c['front'] for c in clozes))
        self.assertTrue(any('Lima' in c['front'] for c in clozes))

    def test_official_legacy_colpkg(self):
        self.assert_import(self.package(legacy=True),'legacy.colpkg')

    def test_modern_apkg(self):
        self.assert_import(self.package(apkg=True),'modern.apkg')

    def test_uncompressed_anki21(self):
        import zstandard
        with zipfile.ZipFile(io.BytesIO(self.package())) as z:
            with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(z.read('collection.anki21b'))) as reader:
                raw=reader.read()
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:z.writestr('collection.anki21',raw)
        self.assert_import(buffer.getvalue(),'uncompressed.colpkg')

    def test_non_sqlite_collection_is_rejected(self):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:z.writestr('collection.anki21b',b'not a database')
        client=app.test_client();before=len(client.get('/api/decks').json)
        buffer.seek(0)
        r=client.post('/api/import',data={'file':(buffer,'broken.colpkg')})
        self.assertEqual(r.status_code,400)
        self.assertEqual(len(client.get('/api/decks').json),before)
