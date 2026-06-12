import json
import os
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from analytics.models import AgentQueryAudit
from analytics.services.agent import (
    AgentError,
    ask_agent,
    execute_agent_sql,
    validate_sql,
    _parse_json_block,
)

User = get_user_model()


@override_settings(
    ANALYTICS_ENABLED=True,
    AGENT_ENABLED=True,
    AGENT_LLM_API_KEY="test-key",
)
class AgentJsonParseTests(TestCase):
    def test_parse_json_block_from_markdown_fence(self):
        payload = _parse_json_block(
            'Here is the query:\n```json\n{"sql": "SELECT 1 LIMIT 1"}\n```'
        )
        self.assertEqual(payload["sql"], "SELECT 1 LIMIT 1")

    def test_parse_json_block_from_embedded_object(self):
        payload = _parse_json_block('Summary: {"answer": "ok", "chart": null}')
        self.assertEqual(payload["answer"], "ok")


class AgentSqlGuardTests(TestCase):
    databases = {"default", "analytics"}

    def test_validate_sql_rejects_insert(self):
        with self.assertRaises(AgentError):
            validate_sql("INSERT INTO bi_assignments VALUES (1)")

    def test_validate_sql_rejects_unknown_view(self):
        with self.assertRaises(AgentError):
            validate_sql("SELECT * FROM tax_operations LIMIT 10")

    def test_validate_sql_adds_limit(self):
        sql = validate_sql("SELECT COUNT(*) FROM bi_assignments")
        self.assertIn("LIMIT", sql.upper())

    def test_execute_agent_sql_on_assignments(self):
        columns, rows = execute_agent_sql(
            "SELECT COUNT(*) AS n FROM bi_assignments LIMIT 1"
        )
        self.assertEqual(columns, ["n"])
        self.assertEqual(len(rows), 1)


@override_settings(
    ANALYTICS_ENABLED=True,
    AGENT_ENABLED=True,
    AGENT_LLM_API_KEY="test-key",
)
class AgentAskTests(TestCase):
    databases = {"default", "analytics"}

    def setUp(self):
        from core.models import Organization

        self.org = Organization.objects.create(name="Agent Test Org")
        self.owner = User.objects.create_user(
            email="owner-agent@example.com",
            password="testpass123",
            organization=self.org,
            role="owner",
        )

    @patch("analytics.services.agent._call_openai")
    def test_ask_agent_success(self, mock_llm):
        mock_llm.side_effect = [
            json.dumps({
                "sql": "SELECT COUNT(*) AS total FROM bi_assignments LIMIT 10",
            }),
            json.dumps({
                "answer": "There are 0 assignments.",
                "chart": None,
            }),
        ]
        result = ask_agent("How many assignments?", user=self.owner)
        self.assertIn("assignments", result.answer.lower())
        self.assertTrue(result.sql)
        audit = AgentQueryAudit.objects.using("analytics").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.status, AgentQueryAudit.Status.SUCCESS)

    @patch("analytics.services.agent._call_openai")
    def test_ask_agent_audits_failure(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "sql": "DELETE FROM bi_assignments",
        })
        with self.assertRaises(AgentError):
            ask_agent("delete everything", user=self.owner)
        audit = AgentQueryAudit.objects.using("analytics").first()
        self.assertEqual(audit.status, AgentQueryAudit.Status.FAILED)


@override_settings(
    ANALYTICS_ENABLED=True,
    AGENT_ENABLED=True,
    AGENT_LLM_API_KEY="test-key",
    FEATURE_QBO=False,
)
class AgentViewTests(TestCase):
    databases = {"default", "analytics"}

    def setUp(self):
        from core.models import Organization

        self.org = Organization.objects.create(name="View Org")
        self.owner = User.objects.create_user(
            email="owner-view@example.com",
            password="testpass123",
            organization=self.org,
            role="owner",
        )
        self.manager = User.objects.create_user(
            email="manager-view@example.com",
            password="testpass123",
            organization=self.org,
            role="manager",
        )

    @patch("analytics.views.ask_agent")
    def test_analytics_ask_owner_ok(self, mock_ask):
        mock_ask.return_value = MagicMock(
            answer="ok",
            sql="SELECT 1 LIMIT 1",
            columns=["?column?"],
            rows=[[1]],
            chart=None,
            coverage_note="",
            etl_as_of=None,
            audit_id=1,
        )
        self.client.force_login(self.owner)
        resp = self.client.post(
            reverse("analytics:analytics_ask"),
            data=json.dumps({"question": "test?"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

    def test_analytics_ask_manager_forbidden(self):
        self.client.force_login(self.manager)
        resp = self.client.post(
            reverse("analytics:analytics_ask"),
            data=json.dumps({"question": "test?"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)


@override_settings(
    ANALYTICS_ENABLED=True,
    AGENT_ENABLED=True,
    AGENT_LLM_API_KEY=os.environ.get("AGENT_LLM_API_KEY", ""),
)
class AgentLiveSmokeTests(TestCase):
    """Run on Droplet only when AGENT_LLM_SMOKE=1 and API key is set."""

    databases = {"default", "analytics"}

    def setUp(self):
        if os.environ.get("AGENT_LLM_SMOKE") != "1" or not os.environ.get("AGENT_LLM_API_KEY"):
            self.skipTest("Set AGENT_LLM_SMOKE=1 and AGENT_LLM_API_KEY for live smoke test.")
        from core.models import Organization

        self.org = Organization.objects.create(name="Smoke Org")
        self.owner = User.objects.create_user(
            email="owner-smoke@example.com",
            password="testpass123",
            organization=self.org,
            role="owner",
        )

    def test_live_ask_matches_track_a_assignment_count(self):
        from analytics.selectors import get_dashboard_context

        ctx = get_dashboard_context()
        expected = ctx.snapshot.total_assignments if ctx.snapshot else 0

        result = ask_agent(
            "How many product assignments are in the active tax season? "
            "Return a single count column named total_assignments.",
            user=self.owner,
        )
        self.assertTrue(result.rows)
        count_val = int(result.rows[0][0])
        self.assertEqual(count_val, expected)
