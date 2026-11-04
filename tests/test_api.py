import asyncio, json
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
import httpx, pytest
from fastapi.testclient import TestClient
from backend import main
from backend.core import Extraction,Claim,Leg,OFFICES
from test_core import leg, Fixed
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('COOKIE_SECURE','false');main.sessions.clear();main.attempts.clear();monkeypatch.setattr(main,'distances',Fixed())
    with TestClient(main.app) as c:
        c.get('/api/config');yield c
@pytest.fixture
def audio_mock(monkeypatch):
    monkeypatch.setattr(main,'probe',lambda *args:None)
    calls=[]
    async def extract(audio,mime,prior):
        calls.append(prior);return Extraction(transcript='3 November 2026, Indraprastha to Sansad Marg',legs=[leg()])
    monkeypatch.setattr(main,'extract',extract);return calls
def submit(c,content=b'audio',followup='false'):
    return c.post('/api/audio',files={'audio':('journey.webm',content,'audio/webm;codecs=opus')},data={'followup':followup})
def test_no_submission_no_export(client):
    assert client.post('/api/export',json=Claim(legs=[leg()]).model_dump(mode='json')).status_code==409

def test_retry_idempotence_followup_and_export(client,audio_mock):
    assert submit(client).status_code==200;assert submit(client).status_code==200;assert len(audio_mock)==1
    claim=Claim(legs=[leg()]);r=client.post('/api/review',json=claim.model_dump(mode='json'));assert r.json()['valid']
    assert submit(client,b'followup','true').status_code==200;assert audio_mock[-1][0]['from_date']=='2026-11-03'
    out=client.post('/api/export',json=claim.model_dump(mode='json'));assert out.status_code==200;assert out.content.startswith(b'PK');assert '03-11-2026' in out.headers['content-disposition']

def test_session_isolation(client,audio_mock):
    submit(client)
    with TestClient(main.app) as other:
        other.get('/api/config');r=other.post('/api/export',json=Claim(legs=[leg()]).model_dump(mode='json'));assert r.status_code==409

def test_missing_date_blocked(client,audio_mock):
    submit(client);r=client.post('/api/export',json=Claim(legs=[leg(day=None)]).model_dump(mode='json'));assert r.status_code==422

def test_wrong_origin(client):
    assert client.post('/api/audio',headers={'Origin':'https://evil.invalid'}).status_code==403

def test_audio_error_retry(client,monkeypatch):
    monkeypatch.setattr(main,'probe',lambda *args:None);calls=[]
    async def extract(*args):
        calls.append(1)
        if len(calls)==1:raise main.HTTPException(504,'Retry')
        return Extraction(transcript='ok',legs=[leg()])
    monkeypatch.setattr(main,'extract',extract)
    assert submit(client).status_code==504;assert submit(client).status_code==200

def test_invalid_audio_magic():
    with pytest.raises(main.HTTPException) as e:main.probe(b'notaudio','audio/webm')
    assert e.value.status_code==422

def test_webm_without_duration(monkeypatch):
    outputs=[Mock(returncode=0,stdout=b'out_time_us=3000000\n')]
    monkeypatch.setattr(main.subprocess,'run',lambda *a,**kw:outputs.pop(0));main.probe(b'\x1aE\xdf\xa3test','audio/webm')

@pytest.mark.asyncio
@pytest.mark.parametrize('status,expected',[(429,429),(500,503)])
async def test_gemini_failure(monkeypatch,status,expected):
    monkeypatch.setenv('GEMINI_API_KEY','test-not-a-key')
    async def transcript(*args):
        if status==429: raise main.HTTPException(429,'quota')
        raise main.HTTPException(503,'unavailable')
    monkeypatch.setattr(main,'transcribe_live',transcript)
    with pytest.raises(main.HTTPException) as e: await main.extract(b'x','audio/webm',[])
    assert e.value.status_code==expected
@pytest.mark.asyncio
async def test_gemini_schema_and_mime(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test');seen=[]
    monkeypatch.setattr(main,'transcribe_live',lambda *args: asyncio.sleep(0,result='इंद्रप्रस्थ से संसद मार्ग'))
    async def generate_content(**kw):
        seen.append(kw);return SimpleNamespace(text=Extraction(transcript='यात्रा',legs=[leg()]).model_dump_json())
    async def aclose(): pass
    sdk=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content),aclose=aclose))
    monkeypatch.setattr(main.genai,'Client',lambda **kw:sdk)
    r=await main.extract(b'x','audio/mp4',[])
    assert r.legs[0].from_id is None
    assert 'इंद्रप्रस्थ से संसद मार्ग' in seen[0]['contents']
    assert seen[0]['config'].response_mime_type=='application/json'
    assert seen[0]['config'].response_schema is main.Extraction
@pytest.mark.asyncio
async def test_invalid_json(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test')
    monkeypatch.setattr(main,'transcribe_live',lambda *args: asyncio.sleep(0,result='spoken trip'))
    async def generate_content(**kw):return SimpleNamespace(text='invalid')
    async def aclose(): pass
    sdk=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content),aclose=aclose))
    monkeypatch.setattr(main.genai,'Client',lambda **kw:sdk)
    with pytest.raises(main.HTTPException) as e:await main.extract(b'x','audio/webm',[])
    assert e.value.status_code==503
@pytest.mark.asyncio
async def test_ten_independent_officials(monkeypatch,audio_mock):
    monkeypatch.setenv('COOKIE_SECURE','false');main.sessions.clear();main.attempts.clear();monkeypatch.setattr(main,'distances',Fixed())
    async def official(n):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://testserver') as c:
            await c.get('/api/config');r=await c.post('/api/audio',files={'audio':('recording.webm',str(n).encode(),'audio/webm')});assert r.status_code==200
            r=await c.post('/api/review',json=Claim(legs=[leg()],rate=str(11+n)).model_dump(mode='json'));assert r.json()['valid'];return c.cookies.get('ta_session'),r.json()['total_fare']
    results=await asyncio.gather(*(official(n) for n in range(10)));assert len({x[0] for x in results})==10;assert len({x[1] for x in results})==10
@pytest.mark.asyncio
async def test_followup_preserves_chosen_office_ids(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test');prior=[leg().model_dump(mode='json')]
    monkeypatch.setattr(main,'transcribe_live',lambda *args: asyncio.sleep(0,result='date correction'))
    async def generate_content(**kw):return SimpleNamespace(text=Extraction(transcript='date correction',legs=[leg(day='2026-11-04')]).model_dump_json())
    async def aclose(): pass
    sdk=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content),aclose=aclose))
    monkeypatch.setattr(main.genai,'Client',lambda **kw:sdk);r=await main.extract(b'x','audio/mp4',prior)
    assert r.legs[0].from_id==prior[0]['from_id'];assert r.legs[0].to_id==prior[0]['to_id']
