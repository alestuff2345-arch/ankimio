import io, json, os, random, re, sqlite3, tempfile, uuid, zipfile
from pathlib import Path
from flask import Flask, jsonify, request, render_template, send_file
import zstandard
import hmac
from anki.collection import Collection
from anki.errors import AnkiException

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024 * 1024
DATA = Path(os.environ.get('ANKIMIO_DATA', Path(__file__).parent / 'data'))
DATA.mkdir(parents=True, exist_ok=True)

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

def db():
    c = sqlite3.connect(DATA / 'study.db')
    c.row_factory = sqlite3.Row
    return c

with db() as c:
    c.executescript('CREATE TABLE IF NOT EXISTS decks(id TEXT PRIMARY KEY,name TEXT); CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY,deck TEXT,front TEXT,back TEXT);')

@app.get('/')
def home(): return render_template('index.html')

@app.get('/api/decks')
def decks():
    with db() as c:
        return jsonify([dict(r) for r in c.execute('SELECT decks.*,count(cards.id) AS count FROM decks LEFT JOIN cards ON cards.deck=decks.id GROUP BY decks.id ORDER BY name')])

@app.post('/api/decks')
def create():
    body = request.get_json() or {}
    name = str(body.get('name', '')).strip()
    if not name: return jsonify(error='Escribe un nombre para el mazo.'), 400
    key = uuid.uuid4().hex
    with db() as c: c.execute('INSERT INTO decks VALUES (?,?)', (key,name))
    return jsonify(id=key), 201

@app.delete('/api/decks')
def delete_all_decks():
    body=request.get_json(silent=True)
    if not isinstance(body,dict) or body.get('confirm') is not True:
        return jsonify(error='Confirma que deseas eliminar todos los mazos y sus tarjetas.'),400
    with db() as c:
        cards=c.execute('DELETE FROM cards').rowcount
        decks=c.execute('DELETE FROM decks').rowcount
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

def unpack(raw):
    if raw.startswith(b'\x28\xb5\x2f\xfd'):
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as reader:
            raw = reader.read(256*1024*1024+1)
        if len(raw)>256*1024*1024: raise ValueError('Archivo descomprimido demasiado grande.')
    return raw

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

@app.post('/api/import')
def import_deck():
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
        pending=[];imported={};batch=uuid.uuid4().hex
        for did,name,front,back in rows:
            key=batch+'-'+str(did);imported[key]=name
            pending.append((uuid.uuid4().hex,key,front,back))
        if not pending: raise ValueError('El paquete no contiene tarjetas.')
        with db() as c:
            c.executemany('INSERT INTO decks VALUES (?,?)',imported.items())
            c.executemany('INSERT INTO cards VALUES (?,?,?,?)',pending)
        return jsonify(count=len(pending),decks=len(imported),warning='Se importó el texto. Las imágenes, audio y estilos de Anki todavía no se importan.')
    except (ValueError,KeyError,IndexError,TypeError,sqlite3.Error,zipfile.BadZipFile,
            RuntimeError,OSError,EOFError,zstandard.ZstdError,AnkiException) as e:
        message=str(e) if isinstance(e,ValueError) and not isinstance(e,json.JSONDecodeError) else 'No se pudo leer la colección. El archivo puede estar dañado o usar un formato aún no compatible.'
        return jsonify(error=message),400

@app.errorhandler(413)
def too_large(e): return jsonify(error='El archivo supera el límite de 128 MB.'),413

if __name__=='__main__': app.run(host='0.0.0.0',port=5000)
