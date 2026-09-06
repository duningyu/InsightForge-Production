"""Existing-resource authorization controls; synthetic accounts and local retrieval."""
from test_open_accounts import portal, claim
import pytest


def login(client, number):
    response = client.post('/api/auth/login', json={
        'username': f'synthetic{number}', 'password': 'SYNTHETIC-only-passphrase!',
    })
    assert response.status_code == 200, response.text


def project(client, title):
    response = client.post('/api/projects', json={'title': title, 'summary': 'synthetic'})
    assert response.status_code == 201, response.text
    return response.json()['id']


def upload(client, project_id, marker):
    response = client.post(f'/api/projects/{project_id}/sources/upload',
        data={'title': marker, 'source_type': 'public_source', 'authority': '0.5'},
        files={'file': ('synthetic.txt', f'合成资料 isolationmarker {marker}'.encode(), 'text/plain')})
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_uploaded_sources_and_persisted_retrieval_are_account_and_project_scoped(portal):
    app, client = portal
    claim(app, client, 101)
    first = project(client, 'owner project')
    second = project(client, 'same owner other project')
    source = upload(client, first, 'OWNER_PRIVATE')
    upload(client, second, 'SAME_ACCOUNT_OTHER_PROJECT')
    response = client.post(f'/api/projects/{first}/retrieve', json={'query': 'isolationmarker'})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run['items'] and {item['source_id'] for item in run['items']} == {source}
    assert 'SAME_ACCOUNT_OTHER_PROJECT' not in response.text
    run_url = f"/api/retrieval/runs/{run['run_id']}"
    assert client.get(run_url).status_code == 200
    assert client.get(f'/api/projects/{first}/retrieval-runs').status_code == 200
    source_url = f'/api/projects/{first}/sources/{source}'
    for action in ('archive', 'restore'):
        response = client.post(f'{source_url}/{action}')
        assert response.status_code == 200, response.text
    before_sources = client.get(f'/api/projects/{first}/sources').json()
    before_run = client.get(run_url).json()

    def reject_private(expected):
        for url in (run_url, f'/api/projects/{first}/sources', f'/api/projects/{first}/retrieval-runs'):
            response = client.get(url, params={'workspace': first, 'participant': 'synthetic101'})
            assert response.status_code == expected, response.text
            assert 'OWNER_PRIVATE' not in response.text
        for action in ('archive', 'restore'):
            response = client.post(f'{source_url}/{action}')
            # Existing source lifecycle contract uses 422 SOURCE_SCOPE_MISMATCH.
            assert response.status_code == (401 if expected == 401 else 422), response.text
            if expected != 401:
                assert 'SOURCE_SCOPE_MISMATCH' in response.text
        assert client.post(f'/api/projects/{first}/retrieve', json={'query': 'isolationmarker'}).status_code == expected

    assert client.post('/api/auth/logout').status_code == 200
    reject_private(401)
    claim(app, client, 102)
    other = project(client, 'other account project')
    other_source = upload(client, other, 'OTHER_ACCOUNT_PRIVATE')
    reject_private(404)
    own = client.post(f'/api/projects/{other}/retrieve', json={'query': 'isolationmarker'})
    assert own.status_code == 200
    assert {item['source_id'] for item in own.json()['items']} == {other_source}
    assert 'OWNER_PRIVATE' not in own.text
    login(client, 101)
    assert client.get(f'/api/projects/{first}/sources').json() == before_sources
    assert client.get(run_url).json() == before_run


def test_document_draft_commit_is_scoped_and_uses_authenticated_actor(portal):
    from test_v3_handoff_and_tools import _prepare_v3
    app, client = portal
    claim(app, client, 111)
    identity = client.get('/api/auth/me').json()['id']
    project_id, _ = _prepare_v3(client)
    generated = client.post(f'/api/projects/{project_id}/documents/generate',
                           json={'doc_type': 'prd', 'idempotency_key': 'fixture-local-document'})
    assert generated.status_code == 200, generated.text
    version = generated.json()['version_id']
    route = f'/api/projects/{project_id}/documents/prd/draft'
    assert client.put(route, json={'base_version_id': version,
                                  'content': 'Synthetic private edited draft'}).status_code == 200
    before = client.get(route).json()
    child = app.state.workspace_pool.entries[identity]['child']
    db = child.state.db
    before_version = db.fetch_one('SELECT * FROM document_versions WHERE id=?', (version,))
    client.post('/api/auth/logout')
    assert client.post(route + '/commit', json={}).status_code == 401
    claim(app, client, 112)
    assert client.post(route + '/commit', json={'actor': identity,
                    'expected_base_version_id': version}).status_code == 404
    assert db.fetch_one('SELECT * FROM document_versions WHERE id=?', (version,)) == before_version
    login(client, 111)
    assert client.get(route).json() == before
    result = client.post(route + '/commit', headers={'X-Actor': 'forged-header'},
                         json={'actor': 'forged-body', 'expected_base_version_id': version})
    assert result.status_code == 201, result.text
    new_id = result.json()['id']
    assert client.get(f'/api/documents/{new_id}').status_code == 200
    assert db.fetch_one('SELECT * FROM document_versions WHERE id=?', (version,)) == before_version
    audit = db.fetch_one("SELECT * FROM audit_events WHERE action='document_edit_draft_committed' ORDER BY id DESC LIMIT 1")
    assert audit and audit['actor'] == identity


def test_handoff_zip_and_global_snapshot_have_owner_positive_controls(portal):
    """Authorization fixture, not a claim of validation or browser E2E success."""
    import io
    import zipfile
    from test_v3_handoff_and_tools import _prepare_v3
    app, client = portal
    claim(app, client, 121)
    identity = client.get('/api/auth/me').json()['id']
    project_id, snapshot = _prepare_v3(client)
    db = app.state.workspace_pool.entries[identity]['child'].state.db
    versions = []
    for kind in ('prd', 'techdoc'):
        generated = client.post(f'/api/projects/{project_id}/documents/generate',
            json={'doc_type': kind, 'idempotency_key': f'authorization-fixture-{kind}'})
        assert generated.status_code == 200, generated.text
        version = generated.json()['version_id']
        # Synthetic precondition only: the operation under test is export authorization.
        db.execute("UPDATE document_versions SET validation_status='passed' WHERE id=?", (version,))
        response = client.post(f'/api/document-versions/{version}/confirm',
                               json={'actor': identity, 'human_confirmed': True})
        assert response.status_code == 200, response.text
        versions.append(version)
    snapshot_url = f"/api/project-snapshots/{snapshot['id']}"
    readiness = f'/api/projects/{project_id}/handoff/readiness'
    export = f'/api/projects/{project_id}/handoff/export'
    before_snapshot = client.get(snapshot_url).json()
    assert client.get(readiness).json()['ready'] is True
    response = client.post(export, json={'target_client': 'codex'})
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert 'PROJECT_SNAPSHOT.json' in archive.namelist()
    before = [db.fetch_one('SELECT * FROM document_versions WHERE id=?', (v,)) for v in versions]
    exports_before = db.fetch_all('SELECT * FROM handoff_runs')
    client.post('/api/auth/logout')
    for status in (401, 404):
        if status == 404:
            claim(app, client, 122)
            own_project, own_snapshot = _prepare_v3(client)
            assert client.get(f"/api/project-snapshots/{own_snapshot['id']}").status_code == 200
            assert client.get(f'/api/projects/{own_project}/handoff/readiness').status_code == 200
        for url in (snapshot_url, readiness):
            assert client.get(url).status_code == status
        assert client.post(export, json={'target_client': 'codex'}).status_code == status
    assert db.fetch_all('SELECT * FROM handoff_runs') == exports_before
    assert [db.fetch_one('SELECT * FROM document_versions WHERE id=?', (v,)) for v in versions] == before
    login(client, 121)
    assert client.get(snapshot_url).json() == before_snapshot


def test_user_profile_settings_are_private_without_reading_credentials(portal):
    app, client = portal
    claim(app, client, 131)
    project_id = project(client, 'settings owner')
    collection = '/api/settings/model-profiles'
    response = client.post(collection, json={'display_name': 'PRIVATE_OWNER_PROFILE',
        'provider': 'openai', 'model_id': 'synthetic-model'})
    assert response.status_code == 201, response.text
    profile = response.json()['id']
    route = f'{collection}/{profile}'
    assert client.patch(route, json={'display_name': 'PRIVATE_OWNER_UPDATED'}).status_code == 200
    assert client.post(route + '/set-default').status_code == 200
    binding = f'/api/projects/{project_id}/model-profile'
    assert client.put(binding, json={'profile_id': profile}).status_code == 200
    before_profiles = client.get(collection).json()
    before_binding = client.get(binding).json()
    client.post('/api/auth/logout')
    for expected in (401, 404):
        if expected == 404:
            claim(app, client, 132)
            own = client.post(collection, json={'display_name': 'OTHER_PROFILE',
                'provider': 'openai', 'model_id': 'synthetic-other'})
            assert own.status_code == 201
            assert 'PRIVATE_OWNER' not in client.get(collection).text
            # Product mode metadata is legitimate, not another user's secret settings.
            assert client.get('/api/settings/mode').status_code == 200
        else:
            assert client.get(collection).status_code == 401
        assert client.get(binding).status_code == expected
        assert client.put(binding, json={'profile_id': profile}).status_code == expected
        assert client.patch(route, json={'display_name': 'forged'}).status_code == expected
        assert client.post(route + '/set-default').status_code == expected
        assert client.delete(route).status_code == expected
    login(client, 131)
    assert client.get(collection).json() == before_profiles
    assert client.get(binding).json() == before_binding
    # The active default profile is intentionally protected from deletion.
    assert client.delete(route).status_code == 409
    removable = client.post(collection, json={'display_name': 'REMOVABLE',
        'provider': 'openai', 'model_id': 'synthetic-unused'}).json()['id']
    assert client.delete(f'{collection}/{removable}').status_code == 204


@pytest.mark.parametrize('action', ['accept', 'reject', 'defer'])
def test_global_change_proposal_actions_are_workspace_scoped(portal, action):
    from test_v3_change_proposals import prepare_snapshot, set_claim_status
    app, client = portal
    claim(app, client, 141)
    identity = client.get('/api/auth/me').json()['id']
    project_id, snapshot = prepare_snapshot(client)
    child = app.state.workspace_pool.entries[identity]['child']
    db = child.state.db
    assumption = db.fetch_one("""SELECT pc.* FROM project_claims pc
        JOIN decision_claim_links dcl ON dcl.claim_id=pc.id
        WHERE pc.project_id=? AND dcl.role='assumption' LIMIT 1""", (project_id,))
    set_claim_status(db, assumption['id'], 'conflict')
    proposal = child.state.impact.resolve_claim_change(project_id=project_id,
        claim_id=assumption['id'], before_status='unverified', after_status='conflict',
        trigger_source_id=None, actor=identity)['proposal_id']
    listing = f'/api/projects/{project_id}/change-proposals'
    before = client.get(listing).json()
    assert any(item['id'] == proposal for item in before)
    original = client.get(f"/api/project-snapshots/{snapshot['id']}").json()
    route = f'/api/change-proposals/{proposal}/{action}'
    payload = {'human_confirmed': True, 'note': 'synthetic authorized decision'}
    client.post('/api/auth/logout')
    assert client.get(listing).status_code == 401
    assert client.post(route, json=payload).status_code == 401
    claim(app, client, 142)
    assert client.get(listing).status_code == 404
    assert client.post(route, json=payload).status_code == 404
    login(client, 141)
    assert client.get(listing).json() == before
    assert client.get(f"/api/project-snapshots/{snapshot['id']}").json() == original
    result = client.post(route, json=payload)
    assert result.status_code == 200, result.text
