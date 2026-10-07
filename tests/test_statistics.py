from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.cache.statistics import StatisticsCache
from app.main import create_app
from database.repositories import leads as repository


def test_statistics_cover_all_pages(client, lead_data):
    ids = [client.post('/lead', json=lead_data).json['id'] for _ in range(4)]
    for lead_id, status in zip(ids[1:], ['in_progress', 'closed', 'rejected']):
        client.patch(f'/lead/{lead_id}/status', json={'status': status})
    assert client.get('/leads?limit=1').json['total'] == 4
    assert client.get('/stats').json == {
        'total': 4, 'new': 1, 'in_progress': 1, 'closed': 1, 'rejected': 1,
    }
    html = client.get('/?limit=1').get_data(as_text=True)
    assert 'data-stat="total">4<' in html
    assert 'data-stat="closed">1<' in html


def test_repeat_reads_use_cache_and_html_uses_same_service(client, monkeypatch):
    aggregate = Mock(wraps=repository.statistics)
    monkeypatch.setattr(repository, 'statistics', aggregate)
    assert client.get('/stats').json['total'] == 0
    assert client.get('/').status_code == 200
    assert client.get('/stats').json['total'] == 0
    assert aggregate.call_count == 1


def test_cache_expires_without_sleep():
    now = [100.0]
    cache = StatisticsCache(timer=lambda: now[0])
    load = Mock(return_value={'total': 1})
    assert cache.get_or_compute(load) == {'total': 1}
    now[0] += 29
    cache.get_or_compute(load)
    assert load.call_count == 1
    now[0] += 1
    load.return_value = {'total': 2}
    assert cache.get_or_compute(load) == {'total': 2}
    assert load.call_count == 2


def test_cache_does_not_expose_mutable_counters():
    cache = StatisticsCache()
    source = {'total': 2}
    result = cache.get_or_compute(lambda: source)
    result['total'] = 999
    source['total'] = 777
    assert cache.get_or_compute(lambda: {}) == {'total': 2}


def test_invalidation_during_calculation_cannot_restore_stale_values():
    cache = StatisticsCache()
    started, resume = Event(), Event()
    calls = []

    def load():
        calls.append(1)
        if len(calls) == 1:
            started.set()
            assert resume.wait(5)
            return {'total': 0}
        return {'total': 1}

    with ThreadPoolExecutor(max_workers=1) as pool:
        reading = pool.submit(cache.get_or_compute, load)
        try:
            assert started.wait(5)
            cache.invalidate()
        finally:
            resume.set()
        assert reading.result(timeout=5) == {'total': 1}
    assert cache.get_or_compute(lambda: {'total': 999}) == {'total': 1}
    assert len(calls) == 2


def test_successful_create_and_status_reset_cache(client, lead_data, monkeypatch):
    aggregate = Mock(wraps=repository.statistics)
    monkeypatch.setattr(repository, 'statistics', aggregate)
    assert client.get('/stats').json['total'] == 0
    created = client.post('/lead', json=lead_data).json
    assert client.get('/stats').json['new'] == 1
    client.patch(f"/lead/{created['id']}/status", json={'status': 'closed'})
    assert client.get('/stats').json['closed'] == 1
    assert client.get('/stats').json['new'] == 0
    assert aggregate.call_count == 3


@pytest.mark.parametrize('operation', ['create', 'status', 'validation', 'missing'])
def test_failed_write_keeps_cached_statistics(client, lead_data, monkeypatch, operation):
    lead = client.post('/lead', json=lead_data).json
    aggregate = Mock(wraps=repository.statistics)
    monkeypatch.setattr(repository, 'statistics', aggregate)
    before = client.get('/stats').json

    def fail_commit(session):
        raise RuntimeError('Simulated commit failure')

    event.listen(Session, 'before_commit', fail_commit)
    try:
        if operation == 'create':
            response = client.post('/lead', json=lead_data)
        elif operation == 'status':
            response = client.patch(f"/lead/{lead['id']}/status", json={'status': 'closed'})
        elif operation == 'validation':
            response = client.post('/lead', json={})
        else:
            response = client.patch('/lead/999/status', json={'status': 'closed'})
    finally:
        event.remove(Session, 'before_commit', fail_commit)
    assert response.status_code in (500, 422, 404)
    assert client.get('/stats').json == before
    assert aggregate.call_count == 1


def test_cache_isolation_and_recovery_from_database(app, client, tmp_path, lead_data):
    client.post('/lead', json=lead_data)
    assert client.get('/stats').json['total'] == 1
    empty = create_app({'TESTING': True, 'DATABASE_PATH': tmp_path / 'other.sqlite3'})
    restarted = create_app({'TESTING': True, 'DATABASE_PATH': app.config['DATABASE_PATH']})
    try:
        assert empty.extensions['statistics_cache'] is not app.extensions['statistics_cache']
        assert restarted.extensions['statistics_cache'] is not app.extensions['statistics_cache']
        assert empty.test_client().get('/stats').json['total'] == 0
        assert restarted.test_client().get('/stats').json['total'] == 1
    finally:
        empty.extensions['database_engine'].dispose()
        restarted.extensions['database_engine'].dispose()
