"""GitHub Plugin for Helpie - Issues, PRs, repos, search via REST API."""
import json
import threading
from typing import Optional


class Plugin:
    def __init__(self):
        self.api = None
        self._base_url = "https://api.github.com"
        self._headers = None

    def init(self, api):
        self.api = api
        self._load_headers()
        api.register_command(
            "list_issues",
            self.list_issues,
            "List issues in a repository",
            ["github issues", "gh issues", "issues list", "github sorunları"]
        )
        api.register_command(
            "create_issue",
            self.create_issue,
            "Create a new issue",
            ["create issue", "github issue", "issue oluştur", "sorun bildir"]
        )
        api.register_command(
            "list_prs",
            self.list_prs,
            "List pull requests",
            ["github prs", "gh prs", "pull requests", "pr listesi"]
        )
        api.register_command(
            "create_pr",
            self.create_pr,
            "Create a pull request",
            ["create pr", "github pr", "pr oluştur", "pull request oluştur"]
        )
        api.register_command(
            "search_repos",
            self.search_repos,
            "Search repositories",
            ["github search", "gh search", "repo ara", "github ara"]
        )
        api.register_command(
            "get_repo",
            self.get_repo,
            "Get repository info",
            ["github repo", "gh repo", "repo info", "depo bilgi"]
        )
        api.register_command(
            "list_repos",
            self.list_repos,
            "List user/org repositories",
            ["github repos", "gh repos", "my repos", "depolarım"]
        )
        print("[GitHub] Plugin loaded")

    def shutdown(self):
        print("[GitHub] Plugin unloaded")

    def _load_headers(self):
        settings = self._get_settings()
        token = settings.get("token", "")
        if token:
            self._headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json"
            }
        else:
            self._headers = None

    def _get_settings(self) -> dict:
        return {
            "token": self.api.get_setting("token", ""),
            "default_owner": self.api.get_setting("default_owner", ""),
            "default_repo": self.api.get_setting("default_repo", ""),
        }

    def _gh_request(self, method: str, endpoint: str, json_data: dict = None, params: dict = None) -> dict:
        if not self._headers:
            return {"error": "Not authenticated. Set GitHub token in Settings."}
        import requests
        url = f"{self._base_url}{endpoint}"
        try:
            resp = requests.request(method, url, headers=self._headers, json=json_data, params=params, timeout=15)
            if resp.status_code == 401:
                return {"error": "Invalid token"}
            if resp.status_code == 403:
                return {"error": "Rate limited or forbidden"}
            return {"status": resp.status_code, "json": resp.json() if resp.content else {}}
        except Exception as e:
            return {"error": str(e)}

    def _resolve_repo(self, args: dict = None) -> tuple:
        owner = (args or {}).get("owner", "").strip() or self._get_settings().get("default_owner", "")
        repo = (args or {}).get("repo", "").strip() or self._get_settings().get("default_repo", "")
        return owner, repo

    def _get_settings(self) -> dict:
        return {
            "token": self.api.get_setting("token", ""),
            "default_owner": self.api.get_setting("default_owner", ""),
            "default_repo": self.api.get_setting("default_repo", ""),
        }

    # --- Commands ---
    def list_issues(self, args: dict = None) -> str:
        owner, repo = self._resolve_repo(args)
        if not owner or not repo:
            return "Repository required. Set default in Settings or specify owner/repo."
        state = (args or {}).get("state", "open")
        result = self._gh_request("GET", f"/repos/{owner}/{repo}/issues", params={"state": state, "per_page": 20})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Error: {result['json']}"
        issues = result["json"]
        if not issues:
            return f"No {state} issues in {owner}/{repo}."
        lines = [f"📋 Issues in {owner}/{repo} ({state}):"]
        for i, issue in enumerate(issues[:10], 1):
            num = issue.get("number")
            title = issue.get("title", "")
            state_label = "🟢" if issue.get("state") == "open" else "🔴"
            lines.append(f"  {i+1}. #{num} {state_label} {title}")
        return "\n".join(lines)

    def create_issue(self, args: dict = None) -> str:
        owner, repo = self._resolve_repo(args)
        if not owner or not repo:
            return "Repository required. Set default in Settings or specify owner/repo."
        title = (args or {}).get("title", "").strip()
        body = (args or {}).get("body", "").strip()
        labels = (args or {}).get("labels", [])
        if not title:
            return "Title required. Try 'create issue title Bug in login body Cannot log in'."
        data = {"title": title}
        if body:
            data["body"] = body
        if labels:
            data["labels"] = [l.strip() for l in labels.split(",")] if isinstance(labels, str) else labels
        result = self._gh_request("POST", f"/repos/{owner}/{repo}/issues", json_data=data)
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            return f"Issue created: #{result['json'].get('number')} - {title}"
        return f"Failed: {result['json']}"

    def list_prs(self, args: dict = None) -> str:
        owner, repo = self._resolve_repo(args)
        if not owner or not repo:
            return "Repository required. Set default in Settings or specify owner/repo."
        state = (args or {}).get("state", "open")
        result = self._gh_request("GET", f"/repos/{owner}/{repo}/pulls", params={"state": state, "per_page": 20})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Error: {result['json']}"
        prs = result["json"]
        if not prs:
            return f"No {state} PRs in {owner}/{repo}."
        lines = [f"🔀 PRs in {owner}/{repo} ({state}):"]
        for i, pr in enumerate(prs[:10], 1):
            num = pr.get("number")
            title = pr.get("title", "")
            state_emoji = "🟢" if pr.get("state") == "open" else "🔴"
            lines.append(f"  {i+1}. #{num} {state_emoji} {title}")
        return "\n".join(lines)

    def create_pr(self, args: dict = None) -> str:
        owner, repo = self._resolve_repo(args)
        if not owner or not repo:
            return "Repository required. Set default in Settings or specify owner/repo."
        title = (args or {}).get("title", "").strip()
        body = (args or {}).get("body", "").strip()
        head = (args or {}).get("head", "").strip()
        base = (args or {}).get("base", "main").strip()
        if not title or not head:
            return "Title and head branch required. Try 'create pr title Fix bug head feature-branch base main'."
        data = {"title": title, "head": head, "base": base}
        if body:
            data["body"] = body
        result = self._gh_request("POST", f"/repos/{owner}/{repo}/pulls", json_data=data)
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            return f"PR created: #{result['json'].get('number')} - {title}"
        return f"Failed: {result['json']}"

    def search_repos(self, args: dict = None) -> str:
        query = (args or {}).get("query", "").strip()
        if not query:
            return "Query required. Try 'github search language:python stars:>1000'."
        result = self._gh_request("GET", "/search/repositories", params={"q": query, "per_page": 10, "sort": "stars", "order": "desc"})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Error: {result['json']}"
        repos = result["json"].get("items", [])
        if not repos:
            return "No repositories found."
        lines = [f"🔍 Found {result['json'].get('total_count', 0)} repositories:"]
        for i, repo in enumerate(repos[:10], 1):
            name = repo.get("full_name", "")
            stars = repo.get("stargazers_count", 0)
            desc = repo.get("description", "")[:80]
            lines.append(f"  {i+1}. {name} ⭐{stars} - {desc}")
        return "\n".join(lines)

    def get_repo(self, args: dict = None) -> str:
        owner, repo = self._resolve_repo(args)
        if not owner or not repo:
            return "Repository required. Try 'github repo owner/repo' or set defaults."
        result = self._gh_request("GET", f"/repos/{owner}/{repo}")
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Error: {result['json']}"
        r = result["json"]
        name = r.get("full_name", "")
        stars = r.get("stargazers_count", 0)
        forks = r.get("forks_count", 0)
        desc = r.get("description", "") or "No description"
        lang = r.get("language", "")
        lines = [f"📦 {name}", f"  ⭐ {stars}  🍴 {forks}  💻 {lang}", f"  {desc}"]
        return "\n".join(lines)

    def list_repos(self, args: dict = None) -> str:
        owner = (args or {}).get("owner", "").strip() or self._get_settings().get("default_owner", "")
        if not owner:
            return "Owner required. Try 'github repos octocat' or set default owner."
        result = self._gh_request("GET", f"/users/{owner}/repos", params={"per_page": 30, "sort": "updated"})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Error: {result['json']}"
        repos = result["json"]
        if not repos:
            return f"No repos for {owner}."
        lines = [f"📁 Repositories for {owner} ({len(repos)}):"]
        for i, repo in enumerate(repos[:15], 1):
            name = repo.get("name", "")
            stars = repo.get("stargazers_count", 0)
            private = "🔒" if repo.get("private") else "🌐"
            lines.append(f"  {i+1}. {private} {name} ⭐{stars}")
        return "\n".join(lines)