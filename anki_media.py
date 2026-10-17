"""Read packaged Anki images without extracting user-controlled filesystem paths."""
import hashlib
import html
import io
import json
import unicodedata
import uuid
from html.parser import HTMLParser
from urllib.parse import unquote

import zstandard
from anki.import_export_pb2 import MediaEntries
from google.protobuf.message import DecodeError

LIMIT = 256 * 1024 * 1024

def unpack(raw, limit=LIMIT):
    if raw.startswith(b'\x28\xb5\x2f\xfd'):
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as reader:
            raw = reader.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('El contenido descomprimido supera el límite permitido.')
    return raw

def image_type(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if raw.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if raw.startswith((b'GIF87a', b'GIF89a')): return 'image/gif'
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP': return 'image/webp'
    if raw.startswith(b'BM'): return 'image/bmp'
    if len(raw)>12 and raw[4:8]==b'ftyp' and raw[8:12] in (b'avif',b'avis'): return 'image/avif'
    return None

def normalize(name):
    return unicodedata.normalize('NFC', name)

def read_images(archive, modern):
    members=set(archive.namelist())
    if 'media' not in members: return {}, []
    metadata=unpack(archive.read('media'), 16*1024*1024)
    if modern:
        try: entries=MediaEntries.FromString(metadata).entries
        except DecodeError as e: raise ValueError('El índice de imágenes de Anki está dañado.') from e
        files=[(str(e.legacy_zip_filename if e.HasField('legacy_zip_filename') else i),e.name,e.sha1,e.size) for i,e in enumerate(entries)]
    else:
        mapping=json.loads(metadata)
        if not isinstance(mapping,dict): raise ValueError('El índice multimedia de Anki no es válido.')
        files=[(str(key),name,b'',None) for key,name in mapping.items()]
    names={}; assets=[]; total=0
    for key,name,digest,size in files:
        if not key.isdecimal() or not isinstance(name,str): raise ValueError('El índice multimedia de Anki no es válido.')
        if key not in members: continue
        raw=unpack(archive.read(key), LIMIT-total)
        total+=len(raw)
        if digest and hashlib.sha1(raw).digest()!=digest: raise ValueError('Una imagen del paquete no pasó la verificación de integridad.')
        if size is not None and len(raw)!=size: raise ValueError('Un archivo multimedia tiene un tamaño incorrecto.')
        mime=image_type(raw)
        if mime:
            token=uuid.uuid4().hex
            names[normalize(name)]='/media/'+token
            assets.append((token,mime,raw))
    return names, assets

class ImageReferences(HTMLParser):
    def __init__(self,names):
        super().__init__(convert_charrefs=False)
        self.names=names;self.output=[];self.missing=0
    def handle_starttag(self,tag,attrs):
        if tag!='img': self.output.append(self.get_starttag_text());return
        values=dict(attrs);src=values.get('src') or ''
        resolved=self.names.get(normalize(src)) or self.names.get(normalize(unquote(src)))
        if resolved:
            self.output.append('<img src="'+resolved+'" alt="'+html.escape(values.get('alt') or 'Imagen de la tarjeta',quote=True)+'">')
        else:
            self.missing+=1
            self.output.append('<span>[Imagen no incluida o formato no compatible]</span>')
    def handle_startendtag(self,tag,attrs):
        if tag=='img': self.handle_starttag(tag,attrs)
        else:self.output.append(self.get_starttag_text())
    def handle_endtag(self,tag): self.output.append('</'+tag+'>')
    def handle_data(self,data): self.output.append(data)
    def handle_entityref(self,name): self.output.append('&'+name+';')
    def handle_charref(self,name): self.output.append('&#'+name+';')

def rewrite_images(markup,names):
    parser=ImageReferences(names);parser.feed(markup);parser.close()
    return ''.join(parser.output),parser.missing
