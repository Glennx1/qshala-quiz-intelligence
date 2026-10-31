"""Triggers a Cloud Run Job execution to process one deck, instead of running ingestion inside
the API process (QShala priority plan: split ingestion out of the monolith so a heavy deck can't
starve dashboard/search traffic or exhaust the API service's memory).

Only used when settings.INGESTION_MODE == "cloud_run_job". The in-process and upload-queue paths
in documents.py._schedule_ingestion are completely untouched by this module.

Auth: uses Application Default Credentials. On Cloud Run, that's automatic -- no key file needed,
just grant the API service's runtime service account `roles/run.developer` (or a custom role with
run.jobs.run) on the ingestion job resource. Locally (e.g. testing this path from a dev machine),
`gcloud auth application-default login` provides equivalent credentials.
"""
import logging

from backend.app.config import settings

logger = logging.getLogger(__name__)


class IngestionJobTriggerError(Exception):
    """Raised when the Cloud Run Job execution couldn't be started."""


def trigger_ingestion_job(document_id: str) -> str:
    """Starts one execution of the configured ingestion job, passing DOCUMENT_ID as an env var
    override so worker.py knows which deck to process. Returns the execution name on success.

    Raises IngestionJobTriggerError (not silently) if INGESTION_MODE=cloud_run_job but the
    required GCP_PROJECT_ID/GCP_REGION/INGESTION_JOB_NAME settings are missing, or if the API
    call itself fails -- a silent no-op here would mean an upload that never processes, with no
    indication why, which is exactly the class of bug the rest of this priority plan exists to
    eliminate.
    """
    missing = [name for name, val in (
        ("GCP_PROJECT_ID", settings.GCP_PROJECT_ID),
        ("GCP_REGION", settings.GCP_REGION),
        ("INGESTION_JOB_NAME", settings.INGESTION_JOB_NAME),
    ) if not val]
    if missing:
        raise IngestionJobTriggerError(
            f"INGESTION_MODE=cloud_run_job but {', '.join(missing)} not set. "
            "See the deployment docs for the Cloud Run Job setup steps."
        )

    try:
        from google.cloud import run_v2
    except ImportError as e:
        raise IngestionJobTriggerError(
            "google-cloud-run is not installed (should be in backend/requirements.txt)"
        ) from e

    job_name = (
        f"projects/{settings.GCP_PROJECT_ID}/locations/{settings.GCP_REGION}"
        f"/jobs/{settings.INGESTION_JOB_NAME}"
    )

    try:
        client = run_v2.JobsClient()
        request = run_v2.RunJobRequest(
            name=job_name,
            overrides=run_v2.RunJobRequest.Overrides(
                container_overrides=[
                    run_v2.RunJobRequest.Overrides.ContainerOverride(
                        env=[run_v2.EnvVar(name="DOCUMENT_ID", value=document_id)],
                    ),
                ],
            ),
        )
        operation = client.run_job(request=request)
        execution_name = getattr(operation, "operation", None)
        execution_name = getattr(execution_name, "name", None) or "unknown"
        logger.info("[INGESTION_JOB] triggered execution=%s for doc_id=%s", execution_name, document_id)
        return execution_name
    except Exception as e:
        raise IngestionJobTriggerError(f"Failed to start ingestion job for doc_id={document_id}: {e}") from e
