import base64
import io, json, os, random, re, sqlite3, tempfile, uuid, zipfile
from pathlib import Path
from flask import Flask, jsonify, request, render_template, send_file
import zstandard
import hmac
import psycopg
from storage import DATA, db, initialize_storage, database_connection_hint
from anki.collection import Collection
from anki.errors import AnkiException
from anki_media import unpack, read_images, rewrite_images
from review import (ReviewError, today_in_zone, progress_for_deck, deck_summaries,
                    record_review, undo_review)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024 * 1024

@app.before_request
def protect_trial():
    password = os.environ.get('ANKIMIO_PASSWORD')
    if request.path == '/healthz' or not password:
        return None
    auth = request.authorization
    if (auth and auth.type == 'basic' and auth.username == 'ankimio'
            and hmac.compare_digest((auth.password or '').encode(), password.encode())):
        return None
    return ('Introduce el usuario ankimio y la contraseña configurada en Render.',
            401, {'WWW-Authenticate': 'Basic realm="Ankimio", charset="UTF-8"'})

@app.get('/healthz')
def health():
    with db() as c:
        c.execute('SELECT 1 FROM decks LIMIT 1').fetchone()
    return jsonify(status='ok')

@app.errorhandler(sqlite3.OperationalError)
@app.errorhandler(psycopg.Error)
def database_error(error):
    # Avoid logging connection strings or credentials from database exceptions.
    app.logger.warning('Database operation failed (%s)',type(error).__name__)
    return jsonify(error='La base de datos no está disponible en este momento. Conserva tus cambios y vuelve a intentarlo.'),503

try:
    initialize_storage()
except psycopg.Error as error:
    raise RuntimeError(database_connection_hint(error)+' No se usará una base temporal.') from None

@app.get('/')
def home(): return render_template('index.html')

@app.get('/api/decks')
def decks():
    today=today_in_zone(request.args.get('timezone','UTC'))
    with db() as c:
        library=library_key(c,request.args.get('library','main'))
        summaries=deck_summaries(c,today)
        return jsonify([dict(r,review=summaries.get(r['id'],{})) for r in c.execute(
            'SELECT decks.*,count(cards.id) AS count FROM decks '
            'LEFT JOIN deck_libraries ON deck_libraries.deck_id=decks.id '
            'LEFT JOIN cards ON cards.deck=decks.id '
            'WHERE COALESCE(deck_libraries.library_id,\'main\')=? GROUP BY decks.id ORDER BY name',(library,))])

def library_key(connection,value):
    if not isinstance(value,str) or not connection.execute('SELECT 1 FROM libraries WHERE id=?',(value,)).fetchone():
        raise ReviewError('La sección ya no existe. Vuelve a cargar tus secciones.',404)
    return value

@app.get('/api/libraries')
def libraries():
    with db() as c:
        return jsonify([dict(r) for r in c.execute("SELECT id,name FROM libraries ORDER BY CASE WHEN id='main' THEN 0 ELSE 1 END,name,id")])

@app.post('/api/libraries')
def create_library():
    body=request.get_json(silent=True)
    name=body.get('name') if isinstance(body,dict) else None
    if not isinstance(name,str) or not 1<=len(name.strip())<=80:
        return jsonify(error='Escribe un nombre de sección de entre 1 y 80 caracteres.'),400
    key=uuid.uuid4().hex
    with db() as c:c.execute('INSERT INTO libraries (id,name) VALUES (?,?)',(key,name.strip()))
    return jsonify(id=key,name=name.strip()),201

@app.errorhandler(ReviewError)
def invalid_review(error):
    return jsonify(error=str(error)),error.status

@app.post('/api/decks/<key>/cards/<card_id>/reviews')
def save_review(key,card_id):
    return jsonify(record_review(key,card_id,request.get_json(silent=True)))

@app.post('/api/decks/<key>/cards/<card_id>/reviews/<event_id>/undo')
def revert_review(key,card_id,event_id):
    return jsonify(undo_review(key,card_id,event_id,request.get_json(silent=True)))

@app.post('/api/decks')
def create():
    body = request.get_json() or {}
    name = str(body.get('name', '')).strip()
    if not name: return jsonify(error='Escribe un nombre para el mazo.'), 400
    key = uuid.uuid4().hex
    with db() as c:
        library=library_key(c,body.get('library','main'))
        c.execute('INSERT INTO decks VALUES (?,?)', (key,name))
        c.execute('INSERT INTO deck_libraries VALUES (?,?)',(key,library))
    return jsonify(id=key), 201

@app.delete('/api/decks')
def delete_all_decks():
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or body.get('confirm') is not True:
        return jsonify(error='Confirma que deseas eliminar todos los mazos y sus tarjetas.'),400
    with db() as c:
        library=library_key(c,request.args.get('library','main'))
        members="SELECT decks.id FROM decks LEFT JOIN deck_libraries ON deck_libraries.deck_id=decks.id WHERE COALESCE(deck_libraries.library_id,'main')=?"
        removed_media=set()
        for card in c.execute(f'SELECT front,back FROM cards WHERE deck IN ({members})',(library,)):
            for side in ('front','back'):removed_media.update(re.findall(r'/media/([0-9a-f]{32})',card[side]))
        cards=c.execute(f'DELETE FROM cards WHERE deck IN ({members})',(library,)).rowcount
        decks=c.execute(f'DELETE FROM decks WHERE id IN ({members})',(library,)).rowcount
        # Other sections may still use these assets, including shared references.
        referenced=set()
        for card in c.execute('SELECT front,back FROM cards'):
            for side in ('front','back'):referenced.update(re.findall(r'/media/([0-9a-f]{32})',card[side]))
        if not c.execute('SELECT 1 FROM cards LIMIT 1').fetchone():c.execute('DELETE FROM media')
        else:
            unused=[(token,) for token in removed_media-referenced]
            if unused:c.executemany('DELETE FROM media WHERE id=?',unused)
    return jsonify(decks=decks,cards=cards)

@app.post('/api/decks/<key>/cards')
def add(key):
    body = request.get_json() or {}
    front, back = str(body.get('front','')).strip(), str(body.get('back','')).strip()
    if not front or not back: return jsonify(error='Completa la pregunta y la respuesta.'), 400
    with db() as c:
        if not c.execute('SELECT 1 FROM decks WHERE id=?',(key,)).fetchone(): return jsonify(error='Mazo inexistente.'),404
        c.execute('INSERT INTO cards VALUES (?,?,?,?)',(uuid.uuid4().hex,key,front,back))
    return jsonify(ok=True),201

@app.get('/api/decks/<key>/cards')
def cards(key):
    with db() as c: rows = [dict(r) for r in c.execute('SELECT * FROM cards WHERE deck=?',(key,))]
    random.shuffle(rows)
    return jsonify(rows)

@app.get('/api/decks/<key>/study')
def study_bundle(key):
    # Deliver the referenced images in the same response as the cards. Once
    # loaded, a session no longer depends on later requests to /media/.
    today=today_in_zone(request.args.get('timezone','UTC'))
    with db() as c:
        if not c.execute('SELECT 1 FROM decks WHERE id=?',(key,)).fetchone():
            return jsonify(error='El mazo ya no está en el servidor. Vuelve a importar el archivo original.'),404
        rows=[dict(r) for r in c.execute('SELECT * FROM cards WHERE deck=?',(key,))]
        progress=progress_for_deck(c,key,today)
        for card in rows:card['progress']=progress[card['id']]
        tokens=set()
        for card in rows:
            for side in ('front','back'):tokens.update(re.findall(r'/media/([0-9a-f]{32})',card[side]))
        images={};tokens=list(tokens)
        for start in range(0,len(tokens),400):
            batch=tokens[start:start+400]
            marks=','.join('?' for _ in batch)
            for asset in c.execute(f'SELECT id,mime,content FROM media WHERE id IN ({marks})',batch):
                images['/media/'+asset['id']]='data:'+asset['mime']+';base64,'+base64.b64encode(asset['content']).decode('ascii')
    random.shuffle(rows)
    response=jsonify(cards=rows,images=images,today=today.isoformat())
    response.headers['Cache-Control']='private, no-store'
    return response

@app.delete('/api/decks/<key>/cards/<card_id>')
def delete_card(key,card_id):
    with db() as c:
        if not c.execute('SELECT 1 FROM cards WHERE id=? AND deck=?',(card_id,key)).fetchone():
            return jsonify(error='La tarjeta ya no existe en este mazo.'),404
        c.execute('DELETE FROM review_events WHERE card_id=?',(card_id,))
        c.execute('DELETE FROM card_progress WHERE card_id=?',(card_id,))
        c.execute('DELETE FROM cards WHERE id=? AND deck=?',(card_id,key))
    return jsonify(ok=True)

@app.patch('/api/decks/<key>/cards/<card_id>')
def edit_card(key,card_id):
    body=request.get_json(silent=True)
    if not isinstance(body,dict): return jsonify(error='Datos de tarjeta inválidos.'),400
    front,back=body.get('front'),body.get('back')
    if not isinstance(front,str) or not isinstance(back,str) or not front.strip() or not back.strip():
        return jsonify(error='Completa la pregunta y la respuesta.'),400
    with db() as c:
        updated=c.execute('UPDATE cards SET front=?,back=? WHERE id=? AND deck=?',
                          (front.strip(),back.strip(),card_id,key)).rowcount
        if not updated: return jsonify(error='La tarjeta ya no existe en este mazo.'),404
    return jsonify(ok=True)

def render(template, fields, answer=False):
    template = re.sub(r'{{FrontSide}}', '', template)
    for name, value in fields.items():
        template = re.sub(r'{{[#^]'+re.escape(name)+r'}}(.*?){{/'+re.escape(name)+r'}}', lambda m: m[1] if value else '', template, flags=re.S)
    def sub(m):
        name=m[1].split(':')[-1]
        value=fields.get(name,'')
        return re.sub(r'{{c\d+::(.*?)(?:::(.*?))?}}', lambda x: x[1] if answer else '['+(x[2] or '…')+']',value)
    return re.sub(r'{{([^{}]+)}}',sub,template)

def collection_cards(path):
    """Read legacy metadata directly; use Anki for modern normalized schemas."""
    source=sqlite3.connect(path)
    try:
        meta=source.execute('SELECT decks, models FROM col').fetchone()
        if meta is None: raise ValueError('La colección de Anki no contiene metadatos.')
        deckmap,models=json.loads(meta[0] or '{}'),json.loads(meta[1] or '{}')
        if models:
            rows=source.execute('SELECT cards.did,cards.ord,notes.mid,notes.flds FROM cards JOIN notes ON notes.id=cards.nid').fetchall()
        else: rows=None
    finally: source.close()
    if rows is not None:
        result=[]
        for did,ordinal,mid,values in rows:
            model=models[str(mid)]
            fields={f['name']:v for f,v in zip(model['flds'],values.split('\x1f'))}
            templates=model['tmpls']
            if not templates: raise ValueError('El mazo contiene un tipo de nota sin plantillas.')
            template=templates[0 if model.get('type')==1 else ordinal % len(templates)]
            result.append((did,deckmap.get(str(did),{}).get('name','Importado'),
                           render(template['qfmt'],fields),render(template['afmt'],fields,True)))
        return result
    # Opening a temporary copy lets Anki decode protobuf metadata and render
    # modern templates/cloze cards without altering the user's original file.
    collection=Collection(str(path))
    try:
        result=[]
        for cid,did,odid in collection.db.all('SELECT id,did,odid FROM cards'):
            card=collection.get_card(cid)
            front,back=card.question(),card.answer()
            # Basic Anki templates include FrontSide before this answer marker.
            parts=re.split(r"<hr\b(?=[^>]*\bid\s*=\s*[\"']?answer\b)[^>]*>",back,maxsplit=1,flags=re.I)
            if len(parts)==2: back=parts[1].strip()
            deck=collection.decks.get(odid or did)
            result.append((odid or did,deck['name'] if deck else 'Importado',front,back))
        return result
    finally: collection.close()

@app.get('/media/<token>')
def card_image(token):
    if not re.fullmatch(r'[0-9a-f]{32}',token): return '',404
    with db() as c: asset=c.execute('SELECT mime,content FROM media WHERE id=?',(token,)).fetchone()
    if not asset:return '',404
    response=send_file(io.BytesIO(asset['content']),mimetype=asset['mime'],max_age=0)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='private, no-store'
    return response

@app.post('/api/import')
def import_deck():
    with db() as c:library=library_key(c,request.form.get('library','main'))
    upload=request.files.get('file')
    if not upload or not upload.filename.lower().endswith(('.colpkg','.apkg')):
        return jsonify(error='Selecciona un archivo .colpkg o .apkg.'),400
    try:
        with zipfile.ZipFile(upload) as archive:
            if sum(x.file_size for x in archive.infolist())>256*1024*1024:
                raise ValueError('El paquete supera el límite de 256 MB descomprimidos.')
            candidates=[n for n in ('collection.anki21b','collection.anki21','collection.anki2') if n in archive.namelist()]
            if not candidates: raise ValueError('No se encontró una colección Anki.')
            raw=unpack(archive.read(candidates[0]))
            if not raw.startswith(b'SQLite format 3\x00'):
                raise ValueError('La colección no contiene una base de datos Anki válida.')
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'collection.anki2';path.write_bytes(raw)
                rows=collection_cards(path)
            names,assets=read_images(archive,candidates[0]=='collection.anki21b')
        pending=[];imported={};batch=uuid.uuid4().hex;missing=0
        for did,name,front,back in rows:
            front,front_missing=rewrite_images(front,names)
            back,back_missing=rewrite_images(back,names)
            missing+=front_missing+back_missing
            key=batch+'-'+str(did);imported[key]=name
            pending.append((uuid.uuid4().hex,key,front,back))
        if not pending: raise ValueError('El paquete no contiene tarjetas.')
        with db() as c:
            library_key(c,library)
            c.executemany('INSERT INTO media VALUES (?,?,?)',assets)
            c.executemany('INSERT INTO decks VALUES (?,?)',imported.items())
            c.executemany('INSERT INTO deck_libraries VALUES (?,?)',[(key,library) for key in imported])
            c.executemany('INSERT INTO cards VALUES (?,?,?,?)',pending)
        warning='Se importaron las tarjetas y sus imágenes. El audio y los estilos personalizados aún no se admiten.'
        if missing:warning+=f' {missing} referencias a imágenes no estaban incluidas o usan un formato no compatible.'
        return jsonify(count=len(pending),decks=len(imported),images=len(assets),warning=warning)
    except (ValueError,KeyError,IndexError,TypeError,sqlite3.Error,zipfile.BadZipFile,
            RuntimeError,OSError,EOFError,zstandard.ZstdError,AnkiException) as e:
        message=str(e) if isinstance(e,ValueError) and not isinstance(e,json.JSONDecodeError) else 'No se pudo leer la colección. El archivo puede estar dañado o usar un formato aún no compatible.'
        return jsonify(error=message),400

@app.errorhandler(413)
def too_large(e): return jsonify(error='El archivo supera el límite de 128 MB.'),413

if __name__=='__main__': app.run(host='0.0.0.0',port=5000)
