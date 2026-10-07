from datetime import datetime

import pytest

from app.main import create_app
from models.lead import Lead


def test_empty_html_and_api_form(client):
    response = client.get('/')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.mimetype == 'text/html'
    assert '<html lang="ru">' in html
    assert '<h1>Заявки</h1>' in html
    assert 'Заявок пока нет' in html
    assert 'action="/lead"' in html
    assert 'name="name"' in html
    assert 'name="phone"' in html
    assert 'name="message"' in html
    assert '/static/js/leads.js' in html


def test_html_escapes_user_content(client, lead_data):
    client.post('/lead', json={**lead_data, 'name': '<b>Иван</b>', 'message': '<script>alert(1)</script>'})
    html = client.get('/').get_data(as_text=True)
    assert '&lt;b&gt;Иван&lt;/b&gt;' in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '<script>alert(1)</script>' not in html
    assert 'action="/lead/1/status"' in html
    assert 'Новая' in html


def test_html_pagination(client, lead_data):
    first = client.post('/lead', json={**lead_data, 'name': 'Первая'}).json
    client.post('/lead', json={**lead_data, 'name': 'Вторая'})
    page = client.get('/?limit=1').get_data(as_text=True)
    assert 'Вторая' in page and '>Первая<' not in page
    assert 'offset=1' in page
    older = client.get('/?limit=1&offset=1').get_data(as_text=True)
    assert f"№ {first['id']}" in older
    assert 'Предыдущая' in older
    assert client.get('/?limit=0').status_code == 422


@pytest.mark.parametrize('zone,expected', [
    ('Europe/Moscow', '02.01.2026 01:15'),
    ('UTC', '01.01.2026 22:15'),
    ('Asia/Vladivostok', '02.01.2026 08:15'),
])
def test_ui_timezone_preserves_utc_in_database(tmp_path, lead_data, zone, expected):
    app = create_app({'TESTING': True, 'DATABASE_PATH': tmp_path / 'zone.sqlite3', 'UI_TIMEZONE': zone})
    try:
        client = app.test_client()
        lead_id = client.post('/lead', json=lead_data).json['id']
        with app.extensions['db_session_factory'].begin() as session:
            session.get(Lead, lead_id).created_at = datetime(2026, 1, 1, 22, 15)
        assert expected in client.get('/').get_data(as_text=True)
        assert client.get('/leads').json['items'][0]['created_at'] == '2026-01-01T22:15:00Z'
    finally:
        app.extensions['database_engine'].dispose()


def test_default_timezone_is_moscow(app):
    assert app.config['UI_TIMEZONE'] == 'Europe/Moscow'
