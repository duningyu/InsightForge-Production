"""Project-scoped manual candidates; real accounts/API and isolated databases."""
from test_open_accounts import portal, claim
from test_account_resource_matrix import login


def project(client, title):
    response = client.post('/api/projects', json={'title': title, 'summary': 'Synthetic decision project'})
    assert response.status_code == 201
    return response.json()['id']


def test_manual_candidates_are_not_sources_or_automatically_selected(portal):
    app, client = portal
    claim(app, client, 301)
    p = project(client, 'Synthetic A')
    route = f'/api/projects/{p}/competitors'
    response = client.post(route, json={'name': 'Synthetic product', 'url': 'https://example.invalid/product',
                                      'description': 'User observation, not verified'})
    assert response.status_code == 201, response.text
    candidate = response.json()
    assert candidate['selected'] is False
    assert candidate['verification_status'] == 'UNVERIFIED'
    assert client.get(route + '/' + candidate['id']).json() == candidate
    assert client.get(f'/api/projects/{p}/sources').json() == []
    assert client.get(route).json()['candidates'] == [candidate]
    selected = client.put(route + '/' + candidate['id'] + '/selection', json={'selected': True})
    assert selected.status_code == 200, selected.text
    assert selected.json()['selected'] is True
    assert selected.json()['verification_status'] == 'UNVERIFIED'
    assert client.put(route + '/' + candidate['id'] + '/selection',
                      json={'selected': True}).json() == selected.json()
    assert client.get(f'/api/projects/{p}/sources').json() == []
    # Caller cannot turn their selection into verified evidence or choose an actor.
    assert client.put(route + '/' + candidate['id'] + '/selection',
                      json={'selected': True, 'confirmed': True, 'actor': 'forged'}).status_code == 422
    identity = client.get('/api/auth/me').json()['id']
    db = app.state.workspace_pool.entries[identity]['child'].state.db
    events = db.fetch_all("SELECT actor FROM audit_events WHERE action='competitor_selection_changed'")
    assert events == [{'actor': identity}]


def test_candidates_scope_both_account_and_project_and_do_not_leak(portal):
    app, client = portal
    claim(app, client, 302)
    p = project(client, 'Synthetic private project')
    other = project(client, 'Same owner other project')
    route = f'/api/projects/{p}/competitors'
    response = client.post(route, json={'name': 'PRIVATE_CANDIDATE_A'})
    assert response.status_code == 201, response.text
    candidate = response.json()
    own_identity = client.get('/api/auth/me').json()['id']
    for wrong_project in [other]:
        base = f'/api/projects/{wrong_project}/competitors/{candidate["id"]}'
        assert client.get(base).status_code == 404
        assert client.put(base + '/selection', json={'selected': True}).status_code == 404
    client.post('/api/auth/logout')
    assert client.get(route).status_code == 401
    assert client.get(route + '/' + candidate['id']).status_code == 401
    assert client.post(route, json={'name': 'Anonymous attempt'}).status_code == 401
    assert client.put(route + '/' + candidate['id'] + '/selection', json={'selected': True}).status_code == 401
    claim(app, client, 303)
    b = project(client, 'Synthetic B')
    response = client.post(f'/api/projects/{b}/competitors', json={'name': 'PRIVATE_CANDIDATE_B'})
    assert response.status_code == 201
    # Existing local IDs can coincide across databases; scope must remain server-selected.
    db_b = app.state.workspace_pool.entries[client.get('/api/auth/me').json()['id']]['child'].state.db
    db_b.execute('UPDATE competitor_candidates SET id=? WHERE id=?', (candidate['id'], response.json()['id']))
    own_b = client.get(f'/api/projects/{b}/competitors/{candidate["id"]}', params={
        'user_id': own_identity, 'workspace': own_identity, 'participant': own_identity,
        'database_path': 'forged-path'})
    assert own_b.status_code == 200 and own_b.json()['name'] == 'PRIVATE_CANDIDATE_B'
    for method, suffix, kwargs in [('get', '', {}), ('get', '/' + candidate['id'], {}),
        ('post', '', {'json': {'name': 'Foreign attempt'}}),
        ('put', '/' + candidate['id'] + '/selection', {'json': {'selected': True}})]:
        rejected = getattr(client, method)(route + suffix, **kwargs)
        assert rejected.status_code == 404 and 'PRIVATE_CANDIDATE_A' not in rejected.text
    login(client, 302)
    assert client.get(route + '/' + candidate['id']).json() == candidate
    assert client.get(route).json()['candidates'] == [candidate]


def test_invalid_url_and_unconfigured_search_are_honest(portal):
    app, client = portal
    claim(app, client, 304)
    p = project(client, 'Synthetic search unavailable')
    route = f'/api/projects/{p}/competitors'
    for url in ['javascript:alert(1)', 'file:///private', 'https://user:password@example.invalid']:
        assert client.post(route, json={'name': 'Synthetic', 'url': url}).status_code == 422
    response = client.get(route)
    assert response.status_code == 200, response.text
    assert response.json()['search_status'] == 'NOT_CONFIGURED'
    assert response.json()['candidates'] == []
    assert '联网查找暂未开启' in response.json()['search_disclosure']


def test_candidate_persistence_and_existing_project_purge_contract(portal):
    app, client = portal
    claim(app, client, 305)
    p = project(client, 'Synthetic purge scope')
    route = f'/api/projects/{p}/competitors'
    response = client.post(route, json={'name': 'Synthetic persisted candidate'})
    assert response.status_code == 201
    identity = client.get('/api/auth/me').json()['id']
    child = app.state.workspace_pool.entries[identity]['child']
    from app.db import Database
    from app.services.projects import ProjectService
    from app.services.competitors import CompetitorService
    reopened = Database(child.state.db.path)
    reopened.init_schema()
    projects = ProjectService(reopened)
    assert CompetitorService(reopened, projects).get(p, response.json()['id']) == response.json()
    projects.move_to_trash(p, actor=identity)
    projects.purge_from_trash(p, actor=identity)
    assert reopened.fetch_all('SELECT * FROM competitor_candidates WHERE project_id=?', (p,)) == []
