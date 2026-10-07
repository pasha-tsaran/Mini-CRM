import pytest

from app.main import create_app
from app.schemas.lead import LeadRead


def test_normal_start_has_no_demo_data(tmp_path, monkeypatch):
    from app import config

    monkeypatch.delenv('DATABASE_PATH', raising=False)
    monkeypatch.setattr(config, 'PROJECT_ROOT', tmp_path)
    for _ in range(2):
        app = create_app({'TESTING': True})
        try:
            assert (tmp_path / 'instance' / 'crm.sqlite3').is_file()
            client = app.test_client()
            assert client.get('/leads').json['items'] == []
            assert client.get('/stats').json['total'] == 0
            assert 'Заявок пока нет' in client.get('/').get_data(as_text=True)
        finally:
            app.extensions['database_engine'].dispose()


def test_internal_validation_error_is_safe_500(client, monkeypatch):
    from api import leads

    def invalid_internal_result(*args):
        return LeadRead.model_validate({'internal-secret-field': 'private'})

    monkeypatch.setattr(leads.service, 'list_leads', invalid_internal_result)
    response = client.get('/leads')
    assert response.status_code == 500
    assert response.json == {
        'error': {'code': 'internal_error', 'message': 'Внутренняя ошибка сервера.'},
    }


@pytest.mark.parametrize('lead_id', ['-1', 'text', '1.5'])
def test_non_integer_or_negative_id_is_not_found(client, lead_id):
    assert client.patch(f'/lead/{lead_id}/status', json={'status': 'closed'}).status_code == 404


def test_empty_out_of_range_page_has_consistent_page_count(client):
    html = client.get('/?limit=1&offset=99').get_data(as_text=True)
    assert '100 из 1' not in html
    assert 'Заявок пока нет' in html
