import base64
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from test_config import configure_test_database
configure_test_database()
from anki.collection import Collection, ExportAnkiPackageOptions
from app import app, db

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9v0AAAAASUVORK5CYII=')

class ImageImport(unittest.TestCase):
    def package(self,legacy=False,apkg=False,media=True):
        with tempfile.TemporaryDirectory() as tmp:
            col=Collection(tmp+'/collection.anki2')
            try:
                name='diagrama á 1.png'
                Path(col.media.dir(),name).write_bytes(PNG)
                deck=col.decks.id('Imágenes')
                for front,back in ((f'<img src="{quote(name)}">','Una figura'),('Identifica la figura',f'<img src="{name}">')):
                    note=col.new_note(col.models.by_name('Basic'));note['Front']=front;note['Back']=back;col.add_note(note,deck)
                out=tmp+'/images.colpkg'
                if apkg:
                    col.export_anki_package(out_path=out,options=ExportAnkiPackageOptions(with_media=media,legacy=legacy),limit=None)
                else:col.export_collection_package(out,include_media=media,legacy=legacy)
                return Path(out).read_bytes()
            finally:col.close()

    def import_package(self,raw):
        return app.test_client().post('/api/import',data={'file':(io.BytesIO(raw),'images.colpkg')})

    def verify_images(self,raw):
        import re
        client=app.test_client();before={d['id'] for d in client.get('/api/decks').json}
        r=self.import_package(raw)
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['images'],1)
        deck=next(d for d in client.get('/api/decks').json if d['id'] not in before)
        cards=client.get('/api/decks/'+deck['id']+'/cards').json
        urls=[url for card in cards for side in ('front','back') for url in re.findall(r'src="(/media/[a-f0-9]{32})"',card[side])]
        self.assertEqual(len(urls),2)
        self.assertEqual(len(set(urls)),1)
        bundle=client.get('/api/decks/'+deck['id']+'/study')
        self.assertEqual(bundle.status_code,200)
        self.assertEqual(len(bundle.json['cards']),2)
        self.assertEqual(list(bundle.json['images']),[urls[0]])
        self.assertEqual(base64.b64decode(bundle.json['images'][urls[0]].split(',',1)[1]),PNG)
        self.assertEqual(bundle.headers['Cache-Control'],'private, no-store')
        image=client.get(urls[0]);self.assertEqual(image.status_code,200)
        self.assertEqual(image.data,PNG);self.assertEqual(image.mimetype,'image/png')
        self.assertEqual(image.headers['X-Content-Type-Options'],'nosniff')
        with patch.dict(os.environ,{'ANKIMIO_PASSWORD':'test-only'}):
            self.assertEqual(client.get(urls[0]).status_code,401)
            self.assertEqual(client.get('/api/decks/'+deck['id']+'/study').status_code,401)
        return urls[0]

    def test_modern_colpkg_images(self):self.verify_images(self.package())
    def test_legacy_colpkg_images(self):self.verify_images(self.package(legacy=True))
    def test_modern_apkg_images(self):self.verify_images(self.package(apkg=True))

    def test_missing_media_is_reported(self):
        r=self.import_package(self.package(media=False))
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['images'],0)
        self.assertIn('no estaban incluidas',r.json['warning'])

    def test_media_tampering_rejects_entire_import(self):
        out=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.package())) as src,zipfile.ZipFile(out,'w') as dest:
            for name in src.namelist():dest.writestr(name,b'invalid' if name=='0' else src.read(name))
        before=app.test_client().get('/api/decks').json
        r=self.import_package(out.getvalue());self.assertEqual(r.status_code,400)
        self.assertIn('integridad',r.json['error'])
        self.assertEqual(before,app.test_client().get('/api/decks').json)

    def test_deleting_decks_deletes_media(self):
        url=self.verify_images(self.package())
        r=app.test_client().delete('/api/decks',json={'confirm':True})
        self.assertEqual(r.status_code,200)
        self.assertEqual(app.test_client().get(url).status_code,404)
        with db() as c:self.assertEqual(c.execute('SELECT count(*) FROM media').fetchone()[0],0)

    def test_study_bundle_missing_deck_and_no_unrelated_images(self):
        client=app.test_client()
        self.assertEqual(client.get('/api/decks/missing/study').status_code,404)
        self.verify_images(self.package())
        key=client.post('/api/decks',json={'name':'Solo texto'}).json['id']
        client.post(f'/api/decks/{key}/cards',json={'front':'Pregunta','back':'Respuesta'})
        bundle=client.get(f'/api/decks/{key}/study')
        self.assertEqual(bundle.status_code,200)
        self.assertEqual(bundle.json['images'],{})
        self.assertEqual(bundle.json['cards'][0]['front'],'Pregunta')

    def test_unsupported_image_reference_is_not_a_filesystem_path(self):
        from anki_media import rewrite_images
        markup,missing=rewrite_images('<img src="../../etc/passwd"><img src="https://example.com/a.png">',{})
        self.assertEqual(missing,2);self.assertNotIn('<img',markup)
