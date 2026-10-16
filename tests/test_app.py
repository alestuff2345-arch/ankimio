import io,json,os,sqlite3,tempfile,unittest,zipfile
os.environ['ANKIMIO_DATA']=tempfile.mkdtemp()
from app import app

class Workflow(unittest.TestCase):
    def setUp(self): self.client=app.test_client()
    def test_create_and_review(self):
        r=self.client.post('/api/decks',json={'name':'Biología'})
        self.assertEqual(r.status_code,201)
        key=r.json['id']
        self.assertEqual(self.client.post(f'/api/decks/{key}/cards',json={'front':'¿ADN?','back':'Ácido desoxirribonucleico'}).status_code,201)
        for _ in range(3):
            cards=self.client.get(f'/api/decks/{key}/cards').json
            self.assertEqual(cards[0]['back'],'Ácido desoxirribonucleico')
        self.assertEqual(self.client.get('/').status_code,200)
    def test_import_real_sqlite_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=tmp+'/collection'; c=sqlite3.connect(path)
            c.executescript('CREATE TABLE col(decks TEXT,models TEXT); CREATE TABLE notes(id INTEGER,mid INTEGER,flds TEXT); CREATE TABLE cards(did INTEGER,ord INTEGER,nid INTEGER);')
            model={'1':{'flds':[{'name':'Front'},{'name':'Back'}],'tmpls':[{'qfmt':'{{Front}}','afmt':'{{Back}}'}]}}
            c.execute('INSERT INTO col VALUES (?,?)',(json.dumps({'1':{'name':'Importado'}}),json.dumps(model)))
            c.execute('INSERT INTO notes VALUES (1,1,?)',('Capital de Perú\x1fLima',))
            c.execute('INSERT INTO cards VALUES (1,0,1)'); c.commit();c.close()
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as z: z.write(path,'collection.anki2')
            buffer.seek(0)
            r=self.client.post('/api/import',data={'file':(buffer,'example.colpkg')})
            self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['count'],1)
            deck=next(d for d in self.client.get('/api/decks').json if d['name']=='Importado')
            self.assertEqual(self.client.get('/api/decks/'+deck['id']+'/cards').json[0]['back'],'Lima')
    def test_delete_all_requires_confirmation_and_removes_cards(self):
        from app import db
        keys=[]
        for name in ('Borrar uno','Borrar dos'):
            key=self.client.post('/api/decks',json={'name':name}).json['id'];keys.append(key)
            self.client.post(f'/api/decks/{key}/cards',json={'front':'Pregunta','back':'Respuesta'})
        for body in ({}, {'confirm':False}, {'confirm':'true'}, []):
            self.assertEqual(self.client.delete('/api/decks',json=body).status_code,400)
        self.assertTrue(all(self.client.get(f'/api/decks/{key}/cards').json for key in keys))
        r=self.client.delete('/api/decks',json={'confirm':True})
        self.assertEqual(r.status_code,200)
        self.assertGreaterEqual(r.json['decks'],2)
        self.assertGreaterEqual(r.json['cards'],2)
        self.assertEqual(self.client.get('/api/decks').json,[])
        with db() as c:self.assertEqual(c.execute('SELECT count(*) FROM cards').fetchone()[0],0)
        self.assertEqual(self.client.delete('/api/decks',json={'confirm':True}).json,{'decks':0,'cards':0})

    def test_edit_card_is_persistent_and_scoped_to_deck(self):
        key=self.client.post('/api/decks',json={'name':'Editable'}).json['id']
        other=self.client.post('/api/decks',json={'name':'Otro'}).json['id']
        self.client.post(f'/api/decks/{key}/cards',json={'front':'Original','back':'Original respuesta'})
        card=self.client.get(f'/api/decks/{key}/cards').json[0]
        url=f"/api/decks/{key}/cards/{card['id']}"
        for body in ({'front':' ','back':'Respuesta'},{'front':'Pregunta','back':''},{'front':[], 'back':'Respuesta'},[]):
            self.assertEqual(self.client.patch(url,json=body).status_code,400)
        self.assertEqual(self.client.patch(f"/api/decks/{other}/cards/{card['id']}",json={'front':'Mal','back':'Mal'}).status_code,404)
        self.assertEqual(self.client.get(f'/api/decks/{key}/cards').json[0]['front'],'Original')
        self.assertEqual(self.client.patch(url,json={'front':' Nueva pregunta ','back':' Nueva respuesta '}).status_code,200)
        saved=app.test_client().get(f'/api/decks/{key}/cards').json[0]
        self.assertEqual(saved['front'],'Nueva pregunta');self.assertEqual(saved['back'],'Nueva respuesta')
        self.assertEqual(saved['id'],card['id'])
        self.assertEqual(self.client.patch(f'/api/decks/{key}/cards/missing',json={'front':'A','back':'B'}).status_code,404)

    def test_invalid_package(self):
        r=self.client.post('/api/import',data={'file':(io.BytesIO(b'bad'),'bad.colpkg')})
        self.assertEqual(r.status_code,400)

if __name__=='__main__': unittest.main()

class TrialAccess(unittest.TestCase):
    def test_password_protects_data_and_allows_health(self):
        from unittest.mock import patch
        import base64
        with patch.dict(os.environ, {'ANKIMIO_PASSWORD': 'test-password-only'}):
            client = app.test_client()
            self.assertEqual(client.get('/api/decks').status_code, 401)
            self.assertEqual(client.delete('/api/decks',json={'confirm':True}).status_code,401)
            self.assertEqual(client.get('/').status_code, 401)
            self.assertEqual(client.get('/healthz').json, {'status': 'ok'})
            token = base64.b64encode(b'ankimio:test-password-only').decode()
            self.assertEqual(client.get('/api/decks', headers={'Authorization': 'Basic '+token}).status_code, 200)
            wrong = base64.b64encode(b'ankimio:wrong').decode()
            self.assertEqual(client.get('/api/decks', headers={'Authorization': 'Basic '+wrong}).status_code, 401)
