import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.database import Database, now
from app.main import create_app
from app.models import AnalysisRequest
from app.services.analysis import AnalysisQueue
from app.services.media import MediaService


def upload(client, sample):
    with sample.open('rb') as stream:
        response = client.post('/api/videos', files={'file': (sample.name, stream, 'video/mp4')})
    assert response.status_code == 201, response.text
    return response.json()


def wait(client, path, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = client.get(path).json()
        if item['status'] not in {'queued', 'running'}:
            return item
        time.sleep(.05)
    pytest.fail(f'Trabajo sin terminar: {path}')


@pytest.fixture
def fake_engine(monkeypatch, settings):
    # Solo se sustituye la inferencia: extracción, cola, persistencia y render son reales.
    words = [{'text': t, 'start': i * .21, 'end': (i + 1) * .21 - .01}
             for i, t in enumerate('¿Cómo crear un clip sin errores? Este consejo revela un resultado increíble.'.split())]
    payload = {'words': words, 'language': 'es', 'text': ' '.join(w['text'] for w in words), 'energy': [.2] * 3}
    monkeypatch.setattr('app.ai.routes.capabilities', lambda _: {'ready': True, 'dependencies': {'whisper': True}, 'models': [{'id': 'tiny', 'installed': True}]})
    def command(self, audio, model, language, result):
        assert audio.stat().st_size > 0
        code = 'from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2],encoding="utf-8"); print(\'{"progress":90,"stage":"Transcribiendo"}\',flush=True)'
        return [sys.executable, '-c', code, str(result), json.dumps(payload)]
    monkeypatch.setattr(AnalysisQueue, '_worker_command', command)
    return payload


def test_local_capabilities_missing_model_and_no_downloads(client, sample_video, settings):
    video = upload(client, sample_video)
    caps = client.get('/api/ai/capabilities').json()
    assert len(caps['models']) == 3
    assert not any(m['installed'] for m in caps['models'])
    response = client.post(f"/api/videos/{video['id']}/analyses", json={'min_duration': 1})
    assert response.status_code in {409, 503}
    assert not settings.model_dir.exists()


def test_analysis_persistence_reuse_and_real_batch(client, settings, sample_video, fake_engine):
    video = upload(client, sample_video)
    options = {'min_duration': .6, 'max_duration': 1.2}
    assert client.post(f"/api/videos/{video['id']}/analyses", json=options).status_code == 422
    options = {'min_duration': 1, 'max_duration': 1.4, 'max_clips': 4}
    response = client.post(f"/api/videos/{video['id']}/analyses", json=options)
    assert response.status_code == 202, response.text
    identifier = response.json()['id']
    item = wait(client, f'/api/analyses/{identifier}')
    assert item['status'] == 'completed', item
    assert 'result' not in item
    result = client.get(f'/api/analyses/{identifier}/result').json()
    assert result['transcript']['words'] == fake_engine['words']
    assert len(result['moments']) >= 2
    response = client.post(f"/api/videos/{video['id']}/analyses", json={**options, 'max_clips': 2})
    second = wait(client, f"/api/analyses/{response.json()['id']}")
    assert second['status'] == 'completed' and second['reused_transcript']
    batch = {'analysis_id': identifier, 'moment_ids': [m['id'] for m in result['moments']], 'resolution': 480, 'platform': 'facebook'}
    response = client.post('/api/clips/batch', json=batch)
    assert response.status_code == 202, response.text
    assert response.json()['count'] == len(result['moments'])
    for job in response.json()['jobs']:
        complete = wait(client, f"/api/jobs/{job['id']}")
        assert complete['status'] == 'completed', complete
        assert complete['settings']['platform'] == 'facebook'
        assert complete['settings']['analysis_id'] == identifier
        assert 0 <= complete['settings']['score'] <= 100
        assert client.get(complete['download_url']).status_code == 200
    with TestClient(create_app(settings)) as reopened:
        assert reopened.get(f'/api/analyses/{identifier}/result').json() == result
    assert not list((settings.data_dir / 'analysis').iterdir())


def test_invalid_batch_selection_has_no_partial_jobs(client, sample_video, fake_engine):
    video = upload(client, sample_video)
    response = client.post(f"/api/videos/{video['id']}/analyses", json={'min_duration': 1, 'max_duration': 1.4})
    identifier = response.json()['id']
    assert wait(client, f'/api/analyses/{identifier}')['status'] == 'completed'
    result = client.get(f'/api/analyses/{identifier}/result').json()
    one = result['moments'][0]['id']
    for ids in ([], [one, one], [one, 'unknown']):
        response = client.post('/api/clips/batch', json={'analysis_id': identifier, 'moment_ids': ids})
        assert response.status_code == 422
    assert client.get('/api/jobs').json() == []


@pytest.mark.parametrize('options', [{'model': '../tiny'}, {'language': 'unknown'}, {'min_duration': 20, 'max_duration': 10}, {'max_clips': 21}, {'min_duration': -1}])
def test_invalid_analysis_options(client, sample_video, options):
    video = upload(client, sample_video)
    assert client.post(f"/api/videos/{video['id']}/analyses", json=options).status_code == 422


def test_analysis_requires_audio(client, settings, sample_video):
    video = upload(client, sample_video)
    row = client.app.state.db.get('videos', video['id'])
    row['has_audio'] = False
    client.app.state.db.put('videos', row)
    response = client.post(f"/api/videos/{video['id']}/analyses", json={'min_duration': 1})
    assert response.status_code == 422
    assert 'audio' in response.json()['detail']


def test_cancel_duplicate_and_shutdown(client, sample_video, fake_engine, monkeypatch):
    monkeypatch.setattr(AnalysisQueue, '_worker_command', lambda *args: [sys.executable, '-c', 'import time; time.sleep(60)'])
    video = upload(client, sample_video)
    response = client.post(f"/api/videos/{video['id']}/analyses", json={'min_duration': 1})
    identifier = response.json()['id']
    assert client.post(f"/api/videos/{video['id']}/analyses", json={'min_duration': 1}).status_code == 409
    assert client.get(f'/api/analyses/{identifier}/result').status_code == 409
    cancelled = client.post(f'/api/analyses/{identifier}/cancel').json()
    assert cancelled['status'] == 'cancelled'
    assert client.get('/api/analyses/missing').status_code == 404


def test_interrupted_analysis_recovery(settings):
    settings.prepare()
    db = Database(settings.data_dir / 'clipzone.sqlite3')
    db.put('analyses', {'id': 'old', 'status': 'running', 'updated_at': now()})
    partial = settings.data_dir / 'analysis/old.pcm'
    partial.write_bytes(b'partial')
    queue = AnalysisQueue(db, settings)
    queue.shutdown()
    assert db.get('analyses', 'old')['status'] == 'failed'
    assert not partial.exists()


@pytest.mark.whisper
def test_real_whisper_transcription_and_moment_export(tmp_path):
    settings = Settings(data_dir=tmp_path / 'real-data', frontend_dir=tmp_path / 'no-ui')
    sample = ROOT / 'demo/phase2-spoken-demo.mp4'
    if not importlib.util.find_spec('whisper') or not (settings.model_dir / 'tiny.pt').is_file() or not sample.is_file():
        pytest.skip('Requiere scripts/setup-ai.ps1 y scripts/create_ai_demo.ps1 (voz local).')
    with TestClient(create_app(settings)) as client:
        video = upload(client, sample)
        response = client.post(f"/api/videos/{video['id']}/analyses", json={'language': 'en', 'min_duration': 3, 'max_duration': 12, 'max_clips': 5})
        assert response.status_code == 202, response.text
        identifier = response.json()['id']
        analysis = wait(client, f'/api/analyses/{identifier}', timeout=180)
        assert analysis['status'] == 'completed', analysis
        result = client.get(f'/api/analyses/{identifier}/result').json()
        assert len(result['transcript']['words']) > 30
        assert 'video' in result['transcript']['text'].lower()
        assert len(result['moments']) >= 2
        response = client.post('/api/clips/batch', json={'analysis_id': identifier, 'moment_ids': [m['id'] for m in result['moments'][:2]], 'resolution': 480, 'platform': 'facebook'})
        assert response.status_code == 202, response.text
        for job in response.json()['jobs']:
            completed = wait(client, f"/api/jobs/{job['id']}")
            assert completed['status'] == 'completed', completed
            output = tmp_path / f"{job['id']}.mp4"
            output.write_bytes(client.get(completed['download_url']).content)
            metadata = MediaService(settings).probe(output)
            assert metadata['width'] == 480 and metadata['height'] == 854
            assert metadata['has_audio'] and metadata['codec'] == 'h264'
