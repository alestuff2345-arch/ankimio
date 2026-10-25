import base64
import io
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from test_config import configure_test_database
configure_test_database()
from app import app
from storage import db, initialize_storage

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9v0AAAAASUVORK5CYII=')


def package():
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'collection.anki2'
        with sqlite3.connect(path) as c:
            c.executescript('CREATE TABLE col(decks TEXT,models TEXT); CREATE TABLE notes(id INTEGER,mid INTEGER,flds TEXT); CREATE TABLE cards(did INTEGER,ord INTEGER,nid INTEGER);')
            model={'1':{'flds':[{'name':'Front'},{'name':'Back'}], 'tmpls':[{'qfmt':'{{Front}}','afmt':'{{Back}}'}]}}
            c.execute('INSERT INTO col VALUES (?,?)',(json.dumps({'1':{'name':'Biología'},'2':{'name':'Química'}}),json.dumps(model)))
            for n in (1,2):
                c.execute('INSERT INTO notes VALUES (?,1,?)',(n,f'Figura {n}<img src="diagram.png">\x1fRespuesta {n}'))
                c.execute('INSERT INTO cards VALUES (?,0,?)',(n,n))
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as archive:
            archive.write(path,'collection.anki2');archive.writestr('media',json.dumps({'0':'diagram.png'}));archive.writestr('0',PNG)
        return out.getvalue()


class Libraries(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client();self.owned_decks=[];self.owned_libraries=[];self.owned_media=[]
        self.main=self.deck('Mazo anterior')
        self.section=self.client.post('/api/libraries',json={'name':'Medicina'}).json['id'];self.owned_libraries.append(self.section)

    def tearDown(self):
        with db() as c:
            for key in self.owned_decks:
                c.execute('DELETE FROM cards WHERE deck=?',(key,));c.execute('DELETE FROM decks WHERE id=?',(key,))
            for key in self.owned_libraries:c.execute('DELETE FROM libraries WHERE id=?',(key,))
            for key in self.owned_media:c.execute('DELETE FROM media WHERE id=?',(key,))

    def deck(self,name,library='main'):
        response=self.client.post('/api/decks',json={'name':name,'library':library});self.assertEqual(response.status_code,201,response.json)
        self.owned_decks.append(response.json['id']);return response.json['id']

    def decks(self,library='main'):
        return self.client.get('/api/decks',query_string={'library':library}).json

    def card(self,deck):
        self.assertEqual(self.client.post(f'/api/decks/{deck}/cards',json={'front':'Pregunta','back':'Respuesta'}).status_code,201)
        return self.client.get(f'/api/decks/{deck}/cards').json[0]

    def test_named_sections_and_legacy_data_survive_reinitialization(self):
        card=self.card(self.main)
        with db() as c:c.execute('DELETE FROM deck_libraries WHERE deck_id=?',(self.main,))
        initialize_storage();initialize_storage()
        client=app.test_client();sections=client.get('/api/libraries').json
        self.assertEqual(sections[0],{'id':'main','name':'Mis mazos'})
        self.assertIn({'id':self.section,'name':'Medicina'},sections)
        self.assertIn(self.main,[d['id'] for d in self.decks()]);self.assertEqual(self.decks(self.section),[])
        self.assertEqual(client.get(f'/api/decks/{self.main}/cards').json[0]['id'],card['id'])
        with db() as c:self.assertEqual(c.execute('SELECT library_id FROM deck_libraries WHERE deck_id=?',(self.main,)).fetchone()['library_id'],'main')

    def test_each_section_has_its_own_decks_with_full_study_and_edit_workflow(self):
        new=self.deck('Mismo nombre',self.section);card=self.card(new)
        self.assertEqual([d['id'] for d in self.decks(self.section)],[new])
        self.assertNotIn(new,[d['id'] for d in self.decks()])
        response=self.client.post(f'/api/decks/{new}/cards/{card["id"]}/reviews',json={'rating':'good','event_id':uuid.uuid4().hex,'expected_revision':None})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.client.patch(f'/api/decks/{new}/cards/{card["id"]}',json={'front':'Editada','back':'Respuesta'}).status_code,200)
        bundle=self.client.get(f'/api/decks/{new}/study').json
        self.assertEqual(bundle['cards'][0]['front'],'Editada');self.assertEqual(bundle['cards'][0]['progress']['status'],'learned_today')
        initialize_storage();self.assertEqual(self.decks(self.section)[0]['review']['learned_today'],1)

    def test_progress_summaries_only_read_selected_section(self):
        from datetime import date
        from review import deck_summaries
        other=self.deck('Otra sección',self.section)
        self.card(self.main);self.card(other)
        with db() as c:
            summaries=deck_summaries(c,date.today(),self.section)
        self.assertEqual(set(summaries),{other})
        self.assertEqual(summaries[other]['new'],1)

    def test_import_places_all_anki_decks_and_images_in_selected_section(self):
        raw=package()
        response=self.client.post('/api/import',data={'library':self.section,'file':(io.BytesIO(raw),'study.colpkg')})
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['decks'],2)
        decks=self.decks(self.section);self.owned_decks.extend(d['id'] for d in decks)
        self.assertEqual({d['name'] for d in decks},{'Biología','Química'})
        self.assertFalse({d['id'] for d in decks}&{d['id'] for d in self.decks()})
        for d in decks:
            bundle=self.client.get(f'/api/decks/{d["id"]}/study').json
            self.assertEqual(len(bundle['images']),1)
            self.owned_media.extend(url.removeprefix('/media/') for url in bundle['images'])
            value=next(iter(bundle['images'].values()));self.assertEqual(base64.b64decode(value.split(',')[1]),PNG)

    def test_deletion_is_scoped_and_preserves_other_sections_shared_images_and_progress(self):
        main_card=self.card(self.main);other=self.deck('Borrar',self.section);self.card(other)
        token=uuid.uuid4().hex;self.owned_media.append(token)
        with db() as c:
            c.execute('INSERT INTO media VALUES (?,?,?)',(token,'image/png',PNG))
            c.execute('UPDATE cards SET back=? WHERE deck IN (?,?)',(f'<img src="/media/{token}">',self.main,other))
        event=uuid.uuid4().hex
        self.client.post(f'/api/decks/{self.main}/cards/{main_card["id"]}/reviews',json={'rating':'good','event_id':event,'expected_revision':None})
        before=self.client.get(f'/api/decks/{self.main}/study').json
        response=self.client.delete('/api/decks',query_string={'library':self.section},json={'confirm':True})
        self.assertEqual(response.json,{'decks':1,'cards':1});self.assertEqual(self.decks(self.section),[])
        self.assertEqual(self.client.get(f'/api/decks/{self.main}/study').json,before)
        self.assertEqual(self.client.get('/media/'+token).data,PNG)
        self.assertIn(self.section,[s['id'] for s in self.client.get('/api/libraries').json])

    def test_invalid_sections_and_names_do_not_create_or_delete_data(self):
        for body in ([],{},None,{'name':[]},{'name':' '},{'name':'a'*81}):
            self.assertEqual(self.client.post('/api/libraries',json=body).status_code,400)
        before=self.decks()
        for response in (
            self.client.get('/api/decks?library=missing'),
            self.client.post('/api/decks',json={'name':'Bad','library':'missing'}),
            self.client.delete('/api/decks?library=missing',json={'confirm':True}),
            self.client.post('/api/import',data={'library':'missing','file':(io.BytesIO(package()),'test.colpkg')}),
        ):self.assertEqual(response.status_code,404,response.json)
        self.assertEqual(self.decks(),before)
        with patch.dict(os.environ,{'ANKIMIO_PASSWORD':'test-only'}):
            self.assertEqual(self.client.post('/api/libraries',json={'name':'Private'}).status_code,401)
            self.assertEqual(self.client.get('/api/libraries').status_code,401)
