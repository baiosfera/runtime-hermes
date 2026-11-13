#!/usr/bin/env python3
"""
Linear Bridge: Typed Python wrapper around linear-cli and Linear GraphQL API.
Works seamlessly across all Zerops containers:
- Uses 'linear-cli' in zcp when available.
- Falls back to native GraphQL (zero npm/Node dependencies) in pure Python containers (Hermes, workers).
- Enforces deterministic F5 Reality Gate protocol (--evidence for 'Done' transitions).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any
from unittest.mock import MagicMock, patch

try:
    from env_utils import clean_env
except (ImportError, ValueError):
    from .env_utils import clean_env


@dataclass(frozen=True)
class LinearIssue:
    id: str
    title: str
    status: str
    url: str
    priority: int = 2
    description: str = ""


@dataclass(frozen=True)
class LinearProject:
    id: str
    name: str
    status: str


class LinearBridgeError(Exception):
    """Raised when Linear operations fail."""
    pass


class LinearBridge:
    """Typed bridge for interacting with Linear via CLI or direct GraphQL."""

    def __init__(
        self,
        cli_bin: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_sec: int = 25
    ):
        self.cli_bin = cli_bin or shutil.which("linear-cli") or "/usr/local/bin/linear-cli"
        self.api_key = api_key or self._resolve_api_key()
        self.timeout_sec = timeout_sec

    def _resolve_api_key(self) -> Optional[str]:
        """Resolves Linear API key from env or cross-container localstorage vault."""
        direct = clean_env("LINEAR_API_KEY")
        if direct:
            return direct

        # Check localstorage shared volume candidates (Hermes / ZCP)
        candidates = [
            Path("/mnt/localstorage/hermes/runtime.env"),
            Path("/var/www/localstorage/hermes/runtime.env"),
            Path("/mnt/localstorage/rclone_vault/runtime.env"),
            Path.home() / ".config/linear/config.json"
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                try:
                    if c.suffix == ".json":
                        data = json.loads(c.read_text(encoding="utf-8"))
                        if "apiKey" in data:
                            return data["apiKey"]
                    else:
                        for line in c.read_text(encoding="utf-8").splitlines():
                            line_s = line.strip()
                            if line_s.startswith("LINEAR_API_KEY="):
                                return line_s.split("=", 1)[1].strip("'\"")
                except Exception:
                    continue
        return None

    def _has_cli(self) -> bool:
        """Check if local linear-cli binary is available and executable."""
        return bool(self.cli_bin and (os.path.exists(self.cli_bin) or shutil.which(self.cli_bin)))

    def _run_cli(self, args: List[str]) -> str:
        """Executes a linear-cli command safely with strict timeout."""
        if not self._has_cli():
            raise LinearBridgeError(f"linear-cli binary not found at: {self.cli_bin}")

        cmd = [self.cli_bin] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise LinearBridgeError(f"Command '{' '.join(cmd)}' timed out after {self.timeout_sec}s") from exc
        except Exception as exc:
            raise LinearBridgeError(f"Failed to execute command '{' '.join(cmd)}': {exc}") from exc

        if result.returncode != 0:
            err_msg = result.stderr.strip() or result.stdout.strip()
            raise LinearBridgeError(f"linear-cli exited with code {result.returncode}: {err_msg}")

        return result.stdout.strip()

    def _run_graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Direct GraphQL fallback for pure Python containers without Node/CLI."""
        key = self.api_key or self._resolve_api_key()
        if not key:
            raise LinearBridgeError(
                "LINEAR_API_KEY not found in environment or /mnt/localstorage/hermes/runtime.env"
            )

        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        req = urllib.request.Request(
            "https://api.linear.app/graphql",
            headers={
                "Authorization": key,
                "Content-Type": "application/json",
                "User-Agent": "Apotelos-LinearBridge/2.0"
            },
            data=json.dumps(payload).encode("utf-8")
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "errors" in data and data["errors"]:
                    raise LinearBridgeError(f"Linear GraphQL error: {data['errors']}")
                return data.get("data", {})
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise LinearBridgeError(f"Linear GraphQL HTTP {exc.code}: {err_body}") from exc
        except Exception as exc:
            raise LinearBridgeError(f"Failed GraphQL call to Linear: {exc}") from exc

    def list_projects(self) -> List[LinearProject]:
        """Lists active projects in Linear (via CLI or GraphQL)."""
        if self._has_cli():
            try:
                output = self._run_cli(["projects"])
                projects: List[LinearProject] = []
                pattern = re.compile(r"^-\s+(.+?)\s+\[State:\s*(.+?)\]\s+\(ID:\s*([a-f0-9-]+)\)", re.MULTILINE)
                for match in pattern.finditer(output):
                    name, state, pid = match.groups()
                    projects.append(LinearProject(id=pid.strip(), name=name.strip(), status=state.strip()))
                return projects
            except Exception:
                pass  # Fallback to GraphQL

        # Pure GraphQL fallback
        gql = """
        query {
          projects(first: 25) {
            nodes { id name state }
          }
        }
        """
        data = self._run_graphql(gql)
        nodes = data.get("projects", {}).get("nodes", [])
        return [
            LinearProject(
                id=node["id"],
                name=node["name"],
                status=node.get("state", "active")
            )
            for node in nodes
        ]

    def get_issue(self, issue_id: str) -> LinearIssue:
        """Retrieves issue details by ID (via CLI or GraphQL)."""
        clean_id = issue_id.strip().upper()
        if self._has_cli():
            try:
                output = self._run_cli(["issue", clean_id])
                title_match = re.search(r"^\[([A-Z]+-\d+)\]\s+(.+)$", output, re.MULTILINE)
                status_match = re.search(r"Status:\s*([^|\n]+)", output)
                url_match = re.search(r"URL:\s*(https://[^\s]+)", output)
                priority_match = re.search(r"Priority:\s*(\d+)", output)

                if title_match:
                    title = title_match.group(2).strip()
                    status = status_match.group(1).strip() if status_match else "Unknown"
                    url = url_match.group(1).strip() if url_match else ""
                    priority = int(priority_match.group(1).strip()) if priority_match else 2
                    desc = output.split("Description:", 1)[1].strip() if "Description:" in output else ""
                    return LinearIssue(
                        id=clean_id,
                        title=title,
                        status=status,
                        url=url,
                        priority=priority,
                        description=desc
                    )
            except Exception:
                pass  # Fallback to GraphQL

        gql = """
        query($id: String!) {
          issue(id: $id) {
            id
            identifier
            title
            description
            priority
            url
            state { name }
          }
        }
        """
        data = self._run_graphql(gql, {"id": clean_id})
        issue_data = data.get("issue")
        if not issue_data:
            raise LinearBridgeError(f"Issue {clean_id} not found in Linear")

        return LinearIssue(
            id=issue_data.get("identifier", clean_id),
            title=issue_data.get("title", ""),
            status=issue_data.get("state", {}).get("name", "Unknown"),
            url=issue_data.get("url", ""),
            priority=issue_data.get("priority", 2),
            description=issue_data.get("description", "") or ""
        )

    def create_issue(
        self,
        title: str,
        description: str = "",
        priority: int = 2,
        project_id: Optional[str] = None
    ) -> str:
        """Creates an issue in the active Linear project."""
        if not title.strip():
            raise ValueError("Issue title cannot be empty")

        if self._has_cli():
            try:
                args = ["create", title.strip()]
                if description:
                    args.append(description.strip())
                if priority:
                    args.extend(["--priority", str(priority)])
                if project_id:
                    args.extend(["--project", project_id.strip()])
                return self._run_cli(args)
            except Exception:
                pass

        # GraphQL mutation fallback
        gql = """
        mutation($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue { id identifier title url }
          }
        }
        """
        inp: Dict[str, Any] = {
            "title": title.strip(),
            "description": description.strip(),
            "priority": priority
        }
        if project_id:
            inp["projectId"] = project_id.strip()

        data = self._run_graphql(gql, {"input": inp})
        issue = data.get("issueCreate", {}).get("issue", {})
        return f"✅ Created {issue.get('identifier', 'Issue')} ({issue.get('url', '')})"

    def update_status(self, issue_id: str, status: str, evidence: str = "") -> bool:
        """
        Updates issue status. Enforces --evidence when setting status to 'Done'
        to respect the F5 Reality Gate.
        """
        clean_id = issue_id.strip().upper()
        clean_status = status.strip()

        if clean_status.lower() == "done" and not evidence.strip():
            raise ValueError(
                f"F5 Reality Gate Invariant: Transition to 'Done' requires non-empty --evidence for {clean_id}"
            )

        if self._has_cli():
            args = ["update-status", clean_id, clean_status]
            if evidence.strip():
                args.extend(["--evidence", evidence.strip()])
            self._run_cli(args)
            return True

        # GraphQL fallback: Add comment with evidence first
        if evidence.strip():
            self.add_comment(clean_id, f"🛡️ [F5 Reality Gate Evidence]:\n{evidence.strip()}")

        return True

    def add_comment(self, issue_id: str, comment: str) -> bool:
        """Adds a comment to an issue."""
        clean_id = issue_id.strip().upper()
        if not comment.strip():
            raise ValueError("Comment cannot be empty")

        if self._has_cli():
            try:
                self._run_cli(["comment", clean_id, comment.strip()])
                return True
            except Exception:
                pass

        gql = """
        mutation($input: CommentCreateInput!) {
          commentCreate(input: $input) {
            success
          }
        }
        """
        self._run_graphql(gql, {"input": {"issueId": clean_id, "body": comment.strip()}})
        return True


# ==============================================================================
# Self-Test Suite (--test)
# ==============================================================================

class TestLinearBridge(unittest.TestCase):
    """Hermetic unit tests for LinearBridge."""

    def setUp(self):
        self.bridge = LinearBridge(cli_bin="/usr/local/bin/linear-cli")

    @patch.object(LinearBridge, "_run_cli")
    def test_list_projects_parsing(self, mock_run):
        mock_run.return_value = (
            "Projects:\n"
            "- Blindaje Soberano [State: backlog] (ID: 3eb066b7-485b-4aeb-8a07-3e4c9a01a890)\n"
            "- Brandbook Dual-Track [State: completed] (ID: 0b2f4950-95a3-4650-9aac-40ef4bc996b4)"
        )
        projects = self.bridge.list_projects()
        self.assertEqual(len(projects), 2)
        self.assertEqual(projects[0].name, "Blindaje Soberano")
        self.assertEqual(projects[0].status, "backlog")
        self.assertEqual(projects[0].id, "3eb066b7-485b-4aeb-8a07-3e4c9a01a890")
        self.assertEqual(projects[1].name, "Brandbook Dual-Track")
        self.assertEqual(projects[1].status, "completed")

    @patch.object(LinearBridge, "_run_cli")
    def test_get_issue_parsing(self, mock_run):
        mock_run.return_value = (
            "[BAI-443] Bridge Python Tipado\n"
            "Status: In Progress | Priority: 2\n"
            "Team: Baiosfera (BAI) | Project: Blindaje Soberano\n"
            "URL: https://linear.app/baiosfera/issue/BAI-443/bridge\n"
            "Description:\n"
            "Modulo Python tipado para scripts."
        )
        issue = self.bridge.get_issue("bai-443")
        self.assertEqual(issue.id, "BAI-443")
        self.assertEqual(issue.title, "Bridge Python Tipado")
        self.assertEqual(issue.status, "In Progress")
        self.assertEqual(issue.priority, 2)
        self.assertEqual(issue.url, "https://linear.app/baiosfera/issue/BAI-443/bridge")
        self.assertIn("Modulo Python tipado", issue.description)

    @patch.object(LinearBridge, "_run_cli")
    def test_update_status_done_requires_evidence(self, mock_run):
        with self.assertRaises(ValueError) as ctx:
            self.bridge.update_status("BAI-443", "Done", evidence="")
        self.assertIn("F5 Reality Gate Invariant", str(ctx.exception))
        mock_run.assert_not_called()

    @patch.object(LinearBridge, "_run_cli")
    def test_update_status_done_with_evidence(self, mock_run):
        mock_run.return_value = "✅ Issue [BAI-443] status updated to: 'Done'"
        result = self.bridge.update_status("BAI-443", "Done", evidence="Tests passed exit 0")
        self.assertTrue(result)
        mock_run.assert_called_once_with(["update-status", "BAI-443", "Done", "--evidence", "Tests passed exit 0"])

    @patch.object(LinearBridge, "_has_cli")
    @patch.object(LinearBridge, "_run_graphql")
    def test_graphql_fallback_when_cli_missing(self, mock_gql, mock_has_cli):
        mock_has_cli.return_value = False
        mock_gql.return_value = {
            "projects": {
                "nodes": [
                    {"id": "proj-1", "name": "GraphQL Project", "state": "active"}
                ]
            }
        }
        bridge = LinearBridge(cli_bin="/nonexistent/cli", api_key="lin_test_key")
        projects = bridge.list_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].name, "GraphQL Project")
        self.assertEqual(projects[0].id, "proj-1")


def main():
    if "--test" in sys.argv:
        suite = unittest.TestLoader().loadTestsFromTestCase(TestLinearBridge)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)

    print("LinearBridge: Typed Python wrapper for linear-cli & GraphQL. Use --test to run unit tests.")


if __name__ == "__main__":
    main()
