import subprocess
import unittest
from unittest.mock import patch

import wiki


class TestParseProjects(unittest.TestCase):
    def test_parses_and_sorts(self):
        text = "zeta\t2\nalpha\t10\nbeta\t0\n"
        self.assertEqual(
            wiki.parse_projects(text),
            [
                {"name": "alpha", "pages": 10},
                {"name": "beta", "pages": 0},
                {"name": "zeta", "pages": 2},
            ],
        )

    def test_empty(self):
        self.assertEqual(wiki.parse_projects(""), [])


class TestParsePages(unittest.TestCase):
    def test_session_page_without_kind(self):
        text = "sessions/a.md\tConversa A\t\n"
        pages = wiki.parse_pages(text)
        self.assertEqual(
            pages,
            [{"path": "sessions/a.md", "title": "Conversa A", "kind": "", "group": "sessions"}],
        )

    def test_decision_page_with_kind(self):
        text = "decisions/x.md\tDecisão X\tdecision\n"
        pages = wiki.parse_pages(text)
        self.assertEqual(pages[0]["kind"], "decision")
        self.assertEqual(pages[0]["group"], "decisions")

    def test_root_page_without_title_uses_filename(self):
        text = "log-2026-09.md\t\t\n"
        pages = wiki.parse_pages(text)
        self.assertEqual(pages[0]["title"], "log-2026-09.md")
        self.assertEqual(pages[0]["group"], "(raiz)")
        self.assertEqual(pages[0]["kind"], "")

    def test_double_quoted_title(self):
        text = 'sessions/a.md\t"responda apenas: ok"\t\n'
        pages = wiki.parse_pages(text)
        self.assertEqual(pages[0]["title"], "responda apenas: ok")

    def test_single_quoted_title_with_escaped_quote(self):
        text = "sessions/a.md\t'it''s'\t\n"
        pages = wiki.parse_pages(text)
        self.assertEqual(pages[0]["title"], "it's")

    def test_sorted_by_path(self):
        text = "b.md\tB\t\na.md\tA\t\n"
        pages = wiki.parse_pages(text)
        self.assertEqual([p["path"] for p in pages], ["a.md", "b.md"])


class TestListPagesValidation(unittest.TestCase):
    @patch.object(wiki, "run")
    def test_invalid_name_does_not_call_run(self, mock_run):
        for bad in ("../x", "a b", "x;rm", ""):
            with self.assertRaises(wiki.WikiError):
                wiki.list_pages(bad)
        mock_run.assert_not_called()

    @patch.object(wiki, "run", return_value="")
    def test_name_goes_in_args_not_script(self, mock_run):
        wiki.list_pages("hoobot")
        args, kwargs = mock_run.call_args
        self.assertEqual(args[1], "hoobot")
        self.assertNotIn("hoobot", args[0])


class TestProjectNotFound(unittest.TestCase):
    @patch("wiki.subprocess.run")
    def test_wraps_not_found_message(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            3,
            ["docker"],
            output="",
            stderr="wiki: projeto 'x' não encontrado → confira o nome na lista de projetos\n",
        )
        with self.assertRaises(wiki.WikiError) as ctx:
            wiki.list_pages("x")
        self.assertIn("não encontrado", str(ctx.exception))


class TestRunErrors(unittest.TestCase):
    @patch("wiki.subprocess.run")
    def test_container_stopped(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1,
            ["docker"],
            output="",
            stderr="Error response from daemon: container abc is not running",
        )
        with self.assertRaises(wiki.WikiError) as ctx:
            wiki.run("echo hi")
        self.assertEqual(
            str(ctx.exception), "container ai-memory parado → docker start ai-memory"
        )

    @patch("wiki.subprocess.run")
    def test_docker_missing(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        with self.assertRaises(wiki.WikiError):
            wiki.run("echo hi")

    @patch("wiki.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["docker"], timeout=15)
        with self.assertRaises(wiki.WikiError):
            wiki.run("echo hi")

    @patch("wiki.subprocess.run")
    def test_builds_expected_command(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        result = wiki.run("some script", "x")
        self.assertEqual(result, "ok")
        call_args, call_kwargs = mock_run.call_args
        self.assertEqual(
            call_args[0],
            ["docker", "exec", "ai-memory", "sh", "-c", "some script", "sh", "x"],
        )
        self.assertEqual(call_kwargs["timeout"], 15)


if __name__ == "__main__":
    unittest.main()
