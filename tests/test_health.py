def test_health_checks_database_and_returns_no_customer_data(client):
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.json == {'status': 'ok'}
