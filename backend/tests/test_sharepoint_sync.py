import pytest
import httpx
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.app.database import Base
from backend.app.models.sharepoint import SharePointSyncState, SharePointFile
from backend.app.models.job import IngestionJob
from backend.app.services.sharepoint.graph_client import SharePointClient
from backend.app.services.storage.blob_storage import VercelBlobService

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def mock_blob_service(tmp_path):
    return VercelBlobService(token=None, local_dir=tmp_path / "blobs")

@pytest.mark.anyio
async def test_initial_sync_multi_page_and_filtering(test_db, mock_blob_service):
    """
    Tests:
    1. Multi-page traversal via @odata.nextLink
    2. Final deltaLink saved into SharePointSyncState
    3. File extension filtering: .pptx and .pdf included, .docx and folders ignored
    4. Enqueuing of IngestionJobs with status=PENDING
    """
    token_url = "https://login.microsoftonline.com/test-tenant/oauth2/v2.0/token"
    page1_url = "https://graph.microsoft.com/v1.0/drives/test-drive/root/delta"
    page2_url = "https://graph.microsoft.com/v1.0/drives/test-drive/root/delta?page=2"
    final_delta_token = "https://graph.microsoft.com/v1.0/drives/test-drive/root/delta?token=abc_delta_123"

    async def mock_handler(request: httpx.Request):
        url_str = str(request.url)
        if url_str == token_url:
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})

        if url_str == page1_url:
            return httpx.Response(200, json={
                "value": [
                    {
                        "id": "file_001",
                        "name": "Quiz_Championship_2023.pptx",
                        "file": {},
                        "eTag": "etag-1",
                        "cTag": "ctag-1",
                        "size": 10240,
                        "webUrl": "https://sharepoint/quiz1.pptx",
                        "@microsoft.graph.downloadUrl": "https://mock-download/quiz1.pptx"
                    },
                    {
                        "id": "folder_001",
                        "name": "Tournament_Folders",
                        "folder": {"childCount": 5}
                    },
                    {
                        "id": "file_002",
                        "name": "Rules_and_Notes.docx",
                        "file": {},
                        "eTag": "etag-docx",
                        "size": 5000
                    }
                ],
                "@odata.nextLink": page2_url
            })

        if url_str == page2_url:
            return httpx.Response(200, json={
                "value": [
                    {
                        "id": "file_003",
                        "name": "Finals_Round.pdf",
                        "file": {},
                        "eTag": "etag-3",
                        "size": 20480,
                        "webUrl": "https://sharepoint/finals.pdf",
                        "@microsoft.graph.downloadUrl": "https://mock-download/finals.pdf"
                    }
                ],
                "@odata.deltaLink": final_delta_token
            })

        if "mock-download" in url_str:
            return httpx.Response(200, content=b"fake presentation binary content")

        return httpx.Response(404)

    client = SharePointClient(
        tenant_id="test-tenant",
        client_id="test-client",
        client_secret="test-secret",
        drive_id="test-drive",
        blob_service=mock_blob_service,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    )

    res = await client.sync_delta(test_db, drive_id="test-drive")

    assert res["status"] == "SUCCESS"
    assert res["pages_processed"] == 2
    assert res["discovered_files_count"] == 2  # .pptx and .pdf only
    assert res["enqueued_jobs_count"] == 2
    assert res["delta_token"] == final_delta_token

    # Verify DB records
    files = test_db.query(SharePointFile).all()
    assert len(files) == 2
    filenames = {f.name for f in files}
    assert filenames == {"Quiz_Championship_2023.pptx", "Finals_Round.pdf"}

    jobs = test_db.query(IngestionJob).all()
    assert len(jobs) == 2
    for j in jobs:
        assert j.status == "PENDING"
        assert j.current_step == "DOWNLOAD"
        assert j.source_type == "SHAREPOINT"
        assert j.blob_url is not None

    state = test_db.query(SharePointSyncState).filter_by(id="qshala_main_library").first()
    assert state.delta_token == final_delta_token
    assert state.status == "IDLE"

@pytest.mark.anyio
async def test_incremental_sync_and_deletion(test_db, mock_blob_service):
    """
    Tests:
    1. Resuming sync from saved deltaLink
    2. Deletion tracking (@removed flag marks sync_status = 'DELETED')
    3. Updating existing file metadata when etag changes
    """
    # Pre-seed existing state and files
    existing_delta = "https://graph.microsoft.com/v1.0/drives/test-drive/root/delta?token=existing_token"
    state = SharePointSyncState(
        id="qshala_main_library",
        drive_id="test-drive",
        delta_token=existing_delta,
        status="IDLE"
    )
    test_db.add(state)

    f1 = SharePointFile(
        id="file_001",
        name="Quiz_1.pptx",
        etag="etag-v1",
        sync_status="COMPLETED"
    )
    f2 = SharePointFile(
        id="file_to_delete",
        name="Old_Quiz.pdf",
        etag="etag-del",
        sync_status="COMPLETED"
    )
    test_db.add_all([f1, f2])
    test_db.commit()

    token_url = "https://login.microsoftonline.com/test-tenant/oauth2/v2.0/token"
    new_delta = "https://graph.microsoft.com/v1.0/drives/test-drive/root/delta?token=new_token_456"

    async def mock_handler(request: httpx.Request):
        url_str = str(request.url)
        if url_str == token_url:
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})

        if url_str == existing_delta:
            return httpx.Response(200, json={
                "value": [
                    {
                        "id": "file_001",
                        "name": "Quiz_1_Updated.pptx",
                        "file": {},
                        "eTag": "etag-v2",
                        "size": 15000,
                        "@microsoft.graph.downloadUrl": "https://mock-download/quiz1_v2.pptx"
                    },
                    {
                        "id": "file_to_delete",
                        "@removed": {"reason": "deleted"}
                    }
                ],
                "@odata.deltaLink": new_delta
            })

        if "mock-download" in url_str:
            return httpx.Response(200, content=b"updated binary")

        return httpx.Response(404)

    client = SharePointClient(
        tenant_id="test-tenant",
        client_id="test-client",
        client_secret="test-secret",
        drive_id="test-drive",
        blob_service=mock_blob_service,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    )

    res = await client.sync_delta(test_db, drive_id="test-drive")

    assert res["status"] == "SUCCESS"
    assert res["deleted_files_count"] == 1
    assert res["discovered_files_count"] == 1

    # Verify deleted file status
    del_file = test_db.query(SharePointFile).filter_by(id="file_to_delete").first()
    assert del_file.sync_status == "DELETED"

    # Verify updated file
    upd_file = test_db.query(SharePointFile).filter_by(id="file_001").first()
    assert upd_file.etag == "etag-v2"
    assert upd_file.name == "Quiz_1_Updated.pptx"
    assert upd_file.sync_status == "QUEUED"

@pytest.mark.anyio
async def test_410_gone_stale_delta_recovery(test_db, mock_blob_service):
    """
    Tests:
    1. HTTP 410 Gone triggers delta_token reset
    2. Client automatically falls back to full /delta root sync
    """
    stale_delta = "https://graph.microsoft.com/v1.0/drives/test-drive/root/delta?token=expired_token"
    root_delta = "https://graph.microsoft.com/v1.0/drives/test-drive/root/delta"
    recovered_delta = "https://graph.microsoft.com/v1.0/drives/test-drive/root/delta?token=fresh_token_789"

    state = SharePointSyncState(
        id="qshala_main_library",
        drive_id="test-drive",
        delta_token=stale_delta,
        status="IDLE"
    )
    test_db.add(state)
    test_db.commit()

    token_url = "https://login.microsoftonline.com/test-tenant/oauth2/v2.0/token"

    async def mock_handler(request: httpx.Request):
        url_str = str(request.url)
        if url_str == token_url:
            return httpx.Response(200, json={"access_token": "mock-token", "expires_in": 3600})

        if url_str == stale_delta:
            # Graph API returns 410 Gone for expired delta tokens
            return httpx.Response(410, json={"error": {"code": "resyncRequired", "message": "Delta token expired"}})

        if url_str == root_delta:
            return httpx.Response(200, json={
                "value": [
                    {
                        "id": "file_after_410",
                        "name": "Fresh_Start.pptx",
                        "file": {},
                        "eTag": "etag-fresh",
                        "size": 8000,
                        "@microsoft.graph.downloadUrl": "https://mock-download/fresh.pptx"
                    }
                ],
                "@odata.deltaLink": recovered_delta
            })

        if "mock-download" in url_str:
            return httpx.Response(200, content=b"fresh binary")

        return httpx.Response(404)

    client = SharePointClient(
        tenant_id="test-tenant",
        client_id="test-client",
        client_secret="test-secret",
        drive_id="test-drive",
        blob_service=mock_blob_service,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    )

    res = await client.sync_delta(test_db, drive_id="test-drive")

    assert res["status"] == "SUCCESS"
    assert res["delta_token"] == recovered_delta
    assert res["discovered_files_count"] == 1

    saved_state = test_db.query(SharePointSyncState).filter_by(id="qshala_main_library").first()
    assert saved_state.delta_token == recovered_delta
