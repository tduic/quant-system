"""Tests for the analysis job store and dashboard analysis endpoints."""

from __future__ import annotations

import time

from post_trade_svc.analysis_jobs import AnalysisJob, JobStatus, JobStore

# ---------------------------------------------------------------------------
# JobStore unit tests
# ---------------------------------------------------------------------------


class TestJobStore:
    def test_submit_returns_job_id(self):
        store = JobStore(max_workers=1)
        job_id = store.submit("sensitivity", {"strategy": "mean_reversion", "num_trades": 50})
        assert job_id.startswith("job-")
        assert len(job_id) > 5

    def test_get_submitted_job(self):
        store = JobStore(max_workers=1)
        job_id = store.submit("monte_carlo", {"num_trades": 50})
        job = store.get(job_id)
        assert job is not None
        assert job.analysis_type == "monte_carlo"
        assert job.status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.COMPLETED)

    def test_get_nonexistent_job(self):
        store = JobStore(max_workers=1)
        assert store.get("nonexistent") is None

    def test_list_jobs_returns_recent(self):
        store = JobStore(max_workers=1)
        ids = []
        for i in range(5):
            ids.append(store.submit("monte_carlo", {"num_trades": 50, "seed": i}))
        jobs = store.list_jobs(limit=3)
        assert len(jobs) <= 5  # may be fewer if some executed fast
        assert all(isinstance(j, AnalysisJob) for j in jobs)

    def test_list_jobs_limit(self):
        store = JobStore(max_workers=1)
        for i in range(5):
            store.submit("monte_carlo", {"num_trades": 50, "seed": i})
        jobs = store.list_jobs(limit=2)
        assert len(jobs) <= 2

    def test_job_completes_eventually(self):
        """Monte carlo with tiny data should complete quickly."""
        store = JobStore(max_workers=1)
        job_id = store.submit(
            "monte_carlo",
            {
                "strategy": "mean_reversion",
                "num_trades": 100,
                "simulations": 10,
                "seed": 42,
            },
        )
        # Poll until done (max 30s)
        deadline = time.time() + 30
        while time.time() < deadline:
            job = store.get(job_id)
            if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                break
            time.sleep(0.2)

        job = store.get(job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED, f"Job status: {job.status}, error: {job.error}"
        assert job.result is not None
        assert "observed_sharpe" in job.result

    def test_cost_sweep_completes(self):
        store = JobStore(max_workers=1)
        job_id = store.submit(
            "cost_sweep",
            {
                "strategy": "mean_reversion",
                "num_trades": 100,
                "seed": 42,
            },
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            job = store.get(job_id)
            if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                break
            time.sleep(0.2)

        job = store.get(job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED, f"Job status: {job.status}, error: {job.error}"
        assert "best_sharpe" in job.result

    def test_invalid_type_fails(self):
        store = JobStore(max_workers=1)
        job_id = store.submit("nonexistent_analysis", {"num_trades": 50})

        deadline = time.time() + 10
        while time.time() < deadline:
            job = store.get(job_id)
            if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                break
            time.sleep(0.2)

        job = store.get(job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert "Unknown analysis type" in (job.error or "")


# ---------------------------------------------------------------------------
# Dashboard endpoint tests
# ---------------------------------------------------------------------------


class TestDashboardAnalysisEndpoints:
    def _make_app(self):
        """Create a test app with mock state."""
        from unittest.mock import MagicMock

        from post_trade_svc.dashboard import create_app

        mock_state = MagicMock()
        return create_app(mock_state)

    def test_submit_endpoint(self):
        from fastapi.testclient import TestClient

        app = self._make_app()
        client = TestClient(app)

        resp = client.post(
            "/api/analysis/submit",
            json={
                "analysis_type": "monte_carlo",
                "params": {"num_trades": 50, "simulations": 5},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data

    def test_status_endpoint(self):
        from fastapi.testclient import TestClient

        app = self._make_app()
        client = TestClient(app)

        # Submit
        resp = client.post(
            "/api/analysis/submit",
            json={
                "analysis_type": "monte_carlo",
                "params": {"num_trades": 50, "simulations": 5},
            },
        )
        job_id = resp.json()["job_id"]

        # Poll status
        resp = client.get(f"/api/analysis/status/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("pending", "running", "completed", "failed")

    def test_status_nonexistent(self):
        from fastapi.testclient import TestClient

        app = self._make_app()
        client = TestClient(app)
        resp = client.get("/api/analysis/status/nonexistent")
        assert resp.status_code == 200
        assert resp.json()["error"] == "Job not found"

    def test_result_endpoint_before_completion(self):
        from fastapi.testclient import TestClient

        app = self._make_app()
        client = TestClient(app)

        resp = client.post(
            "/api/analysis/submit",
            json={
                "analysis_type": "monte_carlo",
                "params": {"num_trades": 50, "simulations": 5},
            },
        )
        job_id = resp.json()["job_id"]

        resp = client.get(f"/api/analysis/result/{job_id}")
        assert resp.status_code == 200
        # May or may not have result yet — just verify the endpoint works
        data = resp.json()
        assert "job_id" in data or "error" in data

    def test_list_jobs_endpoint(self):
        from fastapi.testclient import TestClient

        app = self._make_app()
        client = TestClient(app)

        # Submit a couple
        client.post(
            "/api/analysis/submit",
            json={
                "analysis_type": "monte_carlo",
                "params": {"num_trades": 50},
            },
        )

        resp = client.get("/api/analysis/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert len(data["jobs"]) >= 1
