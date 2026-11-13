"""Notion Plugin for Helpie - Create pages, search, and manage content in Notion."""
import json
import threading
from typing import Optional


class Plugin:
    def __init__(self):
        self.api = None
        self._base_url = "https://api.notion.com/v1"
        self._headers = None

    def init(self, api):
        self.api = api
        self._load_headers()
        api.register_command(
            "create_page",
            self.create_page,
            "Create a new page in a database or as a child page",
            ["create page ", "notion create ", "notion sayfa ", "sayfa oluştur "]
        )
        api.register_command(
            "search",
            self.search,
            "Search Notion pages and databases",
            ["notion search ", "notion ara ", "notion'da ara "]
        )
        api.register_command(
            "append_page",
            self.append_page,
            "Append content to an existing page",
            ["append to page ", "notion append ", "sayfaya ekle "]
        )
        api.register_command(
            "read_page",
            self.read_page,
            "Read content of a page",
            ["read page ", "notion read ", "sayfa oku "]
        )
        api.register_command(
            "create_database_entry",
            self.create_database_entry,
            "Add a new entry to a database",
            ["add to database ", "notion add ", "veritabanına ekle "]
        )
        print("[Notion] Plugin loaded")

    def shutdown(self):
        print("[Notion] Plugin unloaded")

    def _load_headers(self):
        settings = self._get_settings()
        api_key = settings.get("api_key", "")
        if api_key:
            self._headers = {
                "Authorization": f"Bearer {api_key}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json"
            }
        else:
            self._headers = None

    def _get_settings(self) -> dict:
        return {
            "api_key": self.api.get_setting("api_key", ""),
            "default_parent_id": self.api.get_setting("default_parent_id", ""),
        }

    def _notion_request(self, method: str, endpoint: str, json_data: dict = None) -> dict:
        if not self._headers:
            return {"error": "Not authenticated. Set Notion API key in Settings."}
        import requests
        url = f"{self._base_url}{endpoint}"
        try:
            resp = requests.request(method, url, headers=self._headers, json=json_data, timeout=15)
            if resp.status_code == 401:
                return {"error": "Invalid API key"}
            return {"status": resp.status_code, "json": resp.json() if resp.content else {}}
        except Exception as e:
            return {"error": str(e)}

    def _resolve_parent_id(self, args: dict = None) -> Optional[str]:
        explicit = (args or {}).get("parent_id", "")
        if explicit:
            return explicit
        settings = self._get_settings()
        return settings.get("default_parent_id", "")

    # --- Commands ---
    def create_page(self, args: dict = None) -> str:
        title = (args or {}).get("title", "").strip()
        content = (args or {}).get("content", "").strip()
        parent_id = self._resolve_parent_id(args)

        if not title:
            return "Page title required. Try 'create page title My Note content Hello world'."
        if not parent_id:
            return "Parent page/database ID required. Set in Settings or specify parent_id."

        data = {
            "parent": {"page_id": parent_id} if "-" in parent_id else {"database_id": parent_id},
            "properties": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        }
        if content:
            data["children"] = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}}]

        result = self._notion_request("POST", "/pages", json_data=data)
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            return f"Page created: {title}"
        return f"Failed: {result['json']}"

    def append_page(self, args: dict = None) -> str:
        page_id = (args or {}).get("page_id", "").strip()
        content = (args or {}).get("content", "").strip()
        if not page_id:
            return "Page ID required. Try 'append to page <page_id> content <text>'."
        if not content:
            return "Content required."

        data = {"children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}}]}
        result = self._notion_request("PATCH", f"/blocks/{page_id}/children", json_data={"children": data["children"]})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            return "Content appended."
        return f"Failed: {result['json']}"

    def read_page(self, args: dict = None) -> str:
        page_id = (args or {}).get("page_id", "").strip()
        if not page_id:
            return "Page ID required. Try 'read page <page_id>'."
        result = self._notion_request("GET", f"/blocks/{page_id}/children", params={"page_size": 50})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Failed: {result['json']}"
        blocks = result["json"].get("results", [])
        if not blocks:
            return "Page is empty."
        lines = []
        for block in blocks[:20]:
            btype = block.get("type")
            if btype == "paragraph":
                texts = block.get("paragraph", {}).get("rich_text", [])
                text = "".join(t.get("text", {}).get("content", "") for t in texts)
                if text:
                    lines.append(text)
            elif btype == "heading_1":
                texts = block.get("heading_1", {}).get("rich_text", [])
                text = "".join(t.get("text", {}).get("content", "") for t in texts)
                if text:
                    lines.append(f"# {text}")
            elif btype == "heading_2":
                texts = block.get("heading_2", {}).get("rich_text", [])
                text = "".join(t.get("text", {}).get("content", "") for t in texts)
                if text:
                    lines.append(f"## {text}")
            elif btype == "bulleted_list_item":
                texts = block.get("bulleted_list_item", {}).get("rich_text", [])
                text = "".join(t.get("text", {}).get("content", "") for t in texts)
                if text:
                    lines.append(f"• {text}")
        return "\n".join(lines) if lines else "No readable content."

    def search(self, args: dict = None) -> str:
        query = (args or {}).get("query", "").strip()
        if not query:
            return "Search query required. Try 'notion search meeting notes'."
        result = self._notion_request("POST", "/search", json_data={"query": query, "page_size": 10})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Search failed: {result['json']}"
        results = result["json"].get("results", [])
        if not results:
            return "No results found."
        lines = [f"🔍 Found {len(results)} results:"]
        for i, item in enumerate(results[:10], 1):
            obj_type = item.get("object", "")
            title = ""
            if obj_type == "page":
                props = item.get("properties", {})
                for prop in props.values():
                    if prop.get("type") == "title":
                        title_arr = prop.get("title", [])
                        title = "".join(t.get("text", {}).get("content", "") for t in title_arr)
                        break
            elif obj_type == "database":
                title = item.get("title", [{}])[0].get("text", {}).get("content", "")
            lines.append(f"  {i+1}. [{obj_type}] {title or '(untitled)'} ({item['id']})")
        return "\n".join(lines)

    def create_database_entry(self, args: dict = None) -> str:
        database_id = (args or {}).get("database_id", "").strip()
        properties = (args or {}).get("properties", {})
        if not database_id:
            return "Database ID required. Try 'add to database <id> properties <json>'."
        if not properties:
            return "Properties required (JSON)."

        data = {"parent": {"database_id": database_id}, "properties": properties}
        result = self._notion_request("POST", "/pages", json_data={"parent": {"database_id": database_id}, "properties": properties})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") in (200, 201):
            return "Database entry created."
        return f"Failed: {result['json']}"