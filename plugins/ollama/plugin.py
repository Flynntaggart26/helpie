"""Ollama Plugin for Helpie - Local LLM inference, embeddings, model management."""
import json
import threading
import time
from typing import Optional, List


class Plugin:
    def __init__(self):
        self.api = None
        self._base_url = "http://localhost:11434"
        self._default_model = "llama3.2"
        self._timeout = 120

    def init(self, api):
        self.api = api
        self._load_config()
        # Register more specific patterns first to avoid conflicts with general "ollama " pattern
        api.register_command(
            "list_models",
            self.list_models,
            "List available Ollama models",
            ["ollama models", "ollama list", "yerel modeller"]
        )
        api.register_command(
            "pull_model",
            self.pull_model,
            "Pull/download a model",
            ["ollama pull ", "ollama indir ", "model indir "]
        )
        api.register_command(
            "embed",
            self.embed,
            "Generate embeddings for text",
            ["ollama embed ", "embedding ", "gömme "]
        )
        api.register_command(
            "set_model",
            self.set_model,
            "Set default model",
            ["ollama model ", "model seç ", "model ayarla "]
        )
        api.register_command(
            "chat",
            self.chat,
            "Chat with local LLM",
            ["ollama chat ", "ollama ", "local llm ", "local chat ", "yerel sohbet "]
        )
        print("[Ollama] Plugin loaded")

    def shutdown(self):
        print("[Ollama] Plugin unloaded")

    def _load_config(self):
        settings = self._get_settings()
        self._base_url = settings.get("url", "http://localhost:11434").rstrip("/")
        self._default_model = settings.get("default_model", "llama3.2")
        self._timeout = settings.get("timeout", 120)

    def _get_settings(self) -> dict:
        return {
            "url": self.api.get_setting("url", "http://localhost:11434"),
            "default_model": self.api.get_setting("default_model", "llama3.2"),
            "timeout": self.api.get_setting("timeout", 120),
        }

    def _ollama_request(self, method: str, endpoint: str, json_data: dict = None, stream: bool = False) -> dict:
        import requests
        url = f"{self._base_url}{endpoint}"
        try:
            if stream:
                resp = requests.request(method, url, headers={"Content-Type": "application/json"}, json=json_data, timeout=self._timeout, stream=True)
            else:
                resp = requests.request(method, url, headers={"Content-Type": "application/json"}, json=json_data, timeout=self._timeout)
            if resp.status_code == 404:
                return {"error": "Ollama not found. Is Ollama running?"}
            if resp.status_code != 200:
                return {"status": resp.status_code, "error": resp.text}
            if stream:
                return {"status": 200, "stream": resp.iter_lines()}
            return {"status": resp.status_code, "json": resp.json() if resp.content else {}}
        except requests.exceptions.ConnectionError:
            return {"error": "Cannot connect to Ollama. Is it running on " + self._base_url + "?"}
        except Exception as e:
            return {"error": str(e)}

    # --- Commands ---
    def chat(self, args: dict = None) -> str:
        """Chat with local LLM. Args: text, model (optional), stream (optional)"""
        text = (args or {}).get("text", "").strip()
        if not text:
            return "What would you like to chat about? Try 'ollama hello world'."

        # Remove command prefix
        for prefix in ["ollama ", "local llm ", "local chat ", "yerel sohbet "]:
            if text.lower().startswith(prefix):
                text = text[len(prefix):].strip()
                break

        model = (args or {}).get("model", self._default_model)
        stream = (args or {}).get("stream", False)

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": text}],
            "stream": stream
        }

        if stream:
            # Streaming response - collect and return
            result = self._ollama_request("POST", "/api/chat", json_data=payload, stream=True)
            if "error" in result:
                return f"Error: {result['error']}"
            if result.get("status") != 200:
                return f"Error: {result.get('error', 'Unknown error')}"

            full_response = ""
            try:
                for line in result["stream"]:
                    if line:
                        data = json.loads(line)
                        if "message" in data:
                            content = data["message"].get("content", "")
                            full_response += content
                            if data.get("done"):
                                break
            except Exception as e:
                return f"Stream error: {e}"
            return full_response or "No response."
        else:
            result = self._ollama_request("POST", "/api/chat", json_data=payload)
            if "error" in result:
                return f"Error: {result['error']}"
            if result.get("status") != 200:
                return f"Error: {result.get('json', {}).get('error', 'Unknown error')}"
            message = result["json"].get("message", {})
            return message.get("content", "No response.")

    def list_models(self, args: dict = None) -> str:
        result = self._ollama_request("GET", "/api/tags")
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Error: {result.get('json', {})}"
        models = result["json"].get("models", [])
        if not models:
            return "No models installed. Try 'ollama pull llama3.2'."
        lines = ["🤖 Available models:"]
        for m in models:
            name = m.get("name", "")
            size = m.get("size", 0)
            size_gb = size / (1024**3)
            modified = m.get("modified_at", "")[:10]
            lines.append(f"  • {name} ({size_gb:.1f} GB, updated {modified})")
        return "\n".join(lines)

    def pull_model(self, args: dict = None) -> str:
        model = (args or {}).get("model", "").strip()
        if not model:
            return "Model name required. Try 'ollama pull llama3.2' or 'ollama pull mistral'."
        print(f"[Ollama] Pulling {model}...")
        result = self._ollama_request("POST", "/api/pull", json_data={"name": model, "stream": True})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Error: {result.get('json', {})}"

        # Stream progress
        last_status = ""
        try:
            for line in result["stream"]:
                if line:
                    data = json.loads(line)
                    status = data.get("status", "")
                    if status != last_status:
                        print(f"  {status}")
                        last_status = status
                    if data.get("completed"):
                        break
        except Exception as e:
            return f"Pull error: {e}"
        return f"Model {model} pulled successfully."

    def embed(self, args: dict = None) -> str:
        text = (args or {}).get("text", "").strip()
        if not text:
            return "Text required. Try 'ollama embed hello world'."
        model = (args or {}).get("model", "nomic-embed-text")
        result = self._ollama_request("POST", "/api/embeddings", json_data={"model": model, "prompt": text})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Error: {result.get('json', {})}"
        embedding = result["json"].get("embedding", [])
        return f"Embedding generated ({len(embedding)} dimensions): [{', '.join(f'{x:.4f}' for x in embedding[:5])}...]"

    def set_model(self, args: dict = None) -> str:
        model = (args or {}).get("model", "").strip()
        if not model:
            return "Model name required. Try 'ollama model llama3.2'."
        self._default_model = model
        self.api.set_setting("default_model", model)
        return f"Default model set to {model}."