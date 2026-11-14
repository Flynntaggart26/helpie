"""Spotify Plugin for Helpie - Control Spotify playback via Web API."""
import json
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Optional


class Plugin:
    def __init__(self):
        self.api = None
        self._token_lock = threading.Lock()
        self._access_token = None
        self._token_expiry = 0
        self._device_id = None

    def init(self, api):
        self.api = api
        api.register_command(
            "play",
            self.play,
            "Play or resume playback",
            ["play", "resume", "start music", "spotify play", "müzik çal", "çal"]
        )
        api.register_command(
            "pause",
            self.pause,
            "Pause playback",
            ["pause", "stop music", "duraklat", "müziği durdur"]
        )
        api.register_command(
            "next_track",
            self.next_track,
            "Skip to next track",
            ["next", "next track", "skip", "sonraki", "sonraki şarkı"]
        )
        api.register_command(
            "previous_track",
            self.previous_track,
            "Go to previous track",
            ["previous", "prev", "previous track", "önceki", "önceki şarkı"]
        )
        api.register_command(
            "search_play",
            self.search_play,
            "Search and play a track/artist/album",
            ["play ", "search ", "spotify search ", "çal ", "ara "]
        )
        api.register_command(
            "volume",
            self.set_volume,
            "Set Spotify volume",
            ["volume ", "spotify volume ", "ses "]
        )
        api.register_command(
            "current_track",
            self.current_track,
            "Show currently playing track",
            ["what's playing", "current track", "now playing", "ne çalıyor", "şu an ne çalıyor"]
        )
        api.register_command(
            "playlists",
            self.list_playlists,
            "List user playlists",
            ["playlists", "my playlists", "playlistler", "listelerim"]
        )
        api.register_command(
            "play_playlist",
            self.play_playlist,
            "Play a specific playlist",
            ["play playlist ", "aç playlist ", "çal playlist "]
        )
        print("[Spotify] Plugin loaded")

    def shutdown(self):
        print("[Spotify] Plugin unloaded")

    # --- Settings & Auth ---
    def _get_settings(self) -> dict:
        return {
            "client_id": self.api.get_setting("client_id", ""),
            "client_secret": self.api.get_setting("client_secret", ""),
            "refresh_token": self.api.get_setting("refresh_token", ""),
            "device_id": self.api.get_setting("device_id", ""),
        }

    def _save_tokens(self, access_token: str, refresh_token: str, expires_in: int):
        self.api.set_setting("refresh_token", refresh_token)
        with self._token_lock:
            self._access_token = access_token
            self._token_expiry = time.time() + expires_in - 60  # 60s buffer

    def _get_access_token(self) -> Optional[str]:
        with self._token_lock:
            if self._access_token and time.time() < self._token_expiry:
                return self._access_token

        settings = self._get_settings()
        refresh_token = settings.get("refresh_token", "")
        client_id = settings.get("client_id", "")
        client_secret = settings.get("client_secret", "")
        if not (refresh_token and client_id and client_secret):
            return None

        try:
            import requests
            data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
            resp = requests.post(
                "https://accounts.spotify.com/api/token",
                data=data,
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                self._save_tokens(data["access_token"], data.get("refresh_token", ""), data.get("expires_in", 3600))
                return data["access_token"]
        except Exception as e:
            print(f"[Spotify] Token refresh failed: {e}")
        return None

    def _spotify_request(self, method: str, endpoint: str, params: dict = None, json_data: dict = None) -> dict:
        token = self._get_access_token()
        if not token:
            return {"error": "Not authenticated. Set up Spotify OAuth in Settings."}
        import requests
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            resp = requests.request(method, f"https://api.spotify.com/v1{endpoint}", headers=headers, params=params, json=json_data, timeout=10)
            if resp.status_code == 401:
                with self._token_lock:
                    self._access_token = None
                token = self._get_access_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    resp = requests.request(method, f"https://api.spotify.com/v1{endpoint}", headers=headers, params=params, json=json_data, timeout=10)
            return {"status": resp.status_code, "json": resp.json() if resp.content else {}}
        except Exception as e:
            return {"error": str(e)}

    def _get_device_id(self) -> Optional[str]:
        settings = self._get_settings()
        if settings.get("device_id"):
            return settings["device_id"]
        # Try to get active device
        result = self._spotify_request("GET", "/me/player/devices")
        if result.get("status") == 200:
            devices = result["json"].get("devices", [])
            for d in devices:
                if d.get("is_active"):
                    return d["id"]
            if devices:
                return devices[0]["id"]
        return None

    # --- Commands ---
    def play(self, args: dict = None) -> str:
        device_id = self._get_device_id()
        endpoint = "/me/player/play"
        params = {"device_id": device_id} if device_id else {}
        result = self._spotify_request("PUT", "/me/player/play", params=params)
        if "error" in result:
            return f"Spotify error: {result['error']}"
        if result["status"] in (200, 204):
            return "Playing."
        return f"Failed: {result['json']}"

    def pause(self, args: dict = None) -> str:
        device_id = self._get_device_id()
        params = {"device_id": device_id} if device_id else {}
        result = self._spotify_request("PUT", "/me/player/pause", params=params)
        if "error" in result:
            return f"Spotify error: {result['error']}"
        if result["status"] in (200, 204):
            return "Paused."
        return f"Failed: {result['json']}"

    def next_track(self, args: dict = None) -> str:
        device_id = self._get_device_id()
        params = {"device_id": device_id} if device_id else {}
        result = self._spotify_request("POST", "/me/player/next", params=params)
        if "error" in result:
            return f"Spotify error: {result['error']}"
        if result["status"] in (200, 204):
            return "Next track."
        return f"Failed: {result['json']}"

    def previous_track(self, args: dict = None) -> str:
        device_id = self._get_device_id()
        params = {"device_id": device_id} if device_id else {}
        result = self._spotify_request("POST", "/me/player/previous", params=params)
        if "error" in result:
            return f"Spotify error: {result['error']}"
        if result["status"] in (200, 204):
            return "Previous track."
        return f"Failed: {result['json']}"

    def search_play(self, args: dict = None) -> str:
        query = (args or {}).get("text", "").strip()
        if not query:
            return "What should I search for? Try 'play bohemian rhapsody' or 'search pink floyd'."
        # Remove command words
        query = query.replace("play ", "").replace("search ", "").replace("spotify search ", "").replace("çal ", "").replace("ara ", "").strip()
        if not query:
            return "What should I search for?"

        result = self._spotify_request("GET", "/search", params={"q": query, "type": "track,artist,album", "limit": 5})
        if "error" in result:
            return f"Search failed: {result['error']}"
        if result["status"] != 200:
            return f"Search failed: {result['json']}"

        data = result["json"]
        tracks = data.get("tracks", {}).get("items", [])
        if not tracks:
            return f"No results for '{query}'."

        # Play first track
        track = tracks[0]
        uri = track["uri"]
        name = track["name"]
        artists = ", ".join(a["name"] for a in track["artists"])

        device_id = self._get_device_id()
        result = self._spotify_request("PUT", "/me/player/play", params={"device_id": device_id} if device_id else {}, json_data={"uris": [uri]})
        if result.get("status") in (200, 204):
            return f"Playing: {name} by {artists}"
        return f"Found '{name}' by {artists} but couldn't start playback."

    def set_volume(self, args: dict = None) -> str:
        # Extract volume from text
        import re
        text = (args or {}).get("text", "")
        match = re.search(r"(\d{1,3})", (args or {}).get("text", ""))
        if not match:
            return "What volume? (0-100)"
        volume = max(0, min(100, int(match.group(1))))
        device_id = self._get_device_id()
        params = {"device_id": device_id} if device_id else {}
        result = self._spotify_request("PUT", f"/me/player/volume?volume_percent={volume}", params=params)
        if "error" in result:
            return f"Failed: {result['error']}"
        if result.get("status") in (200, 204):
            return f"Volume set to {volume}%."
        return f"Failed: {result.get('json', 'unknown error')}"

    def current_track(self, args: dict = None) -> str:
        result = self._spotify_request("GET", "/me/player/currently-playing", params={"market": "TR"})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") == 204 or not result.get("json"):
            return "Nothing playing."
        if result.get("status") != 200:
            return f"Error: {result['json']}"

        data = result["json"]
        item = data.get("item")
        if not item:
            return "Nothing playing."
        name = item.get("name", "Unknown")
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        progress = data.get("progress_ms", 0) // 1000
        duration = item.get("duration_ms", 0) // 1000
        is_playing = data.get("is_playing", False)
        status = "▶" if is_playing else "⏸"
        return f"{status} {name} — {artists} ({progress//60}:{progress%60:02d} / {duration//60}:{duration%60:02d})"

    def list_playlists(self, args: dict = None) -> str:
        result = self._spotify_request("GET", "/me/playlists", params={"limit": 20})
        if "error" in result:
            return f"Error: {result['error']}"
        if result.get("status") != 200:
            return f"Error: {result['json']}"
        items = result["json"].get("items", [])
        if not items:
            return "No playlists found."
        lines = ["🎵 Your playlists:"]
        for i, pl in enumerate(items[:10], 1):
            tracks = pl.get("tracks", {}).get("total", 0)
            lines.append(f"  {i+1}. {pl['name']} ({tracks} tracks)")
        return "\n".join(lines)

    def play_playlist(self, args: dict = None) -> str:
        query = (args or {}).get("text", "").strip()
        if not query:
            return "Which playlist? Try 'play playlist Discover Weekly'."
        query = query.replace("play playlist ", "").replace("aç playlist ", "").replace("çal playlist ", "").strip()
        if not query:
            return "Which playlist?"

        result = self._spotify_request("GET", "/me/playlists", params={"limit": 50})
        if result.get("status") != 200:
            return f"Error: {result['json']}"

        playlists = result["json"].get("items", [])
        match = None
        for pl in playlists:
            if query.lower() in pl["name"].lower():
                match = pl
                break
        if not match:
            return f"Playlist '{query}' not found."

        uri = match["uri"]
        name = match["name"]
        device_id = self._get_device_id()
        result = self._spotify_request("PUT", "/me/player/play", params={"device_id": device_id} if device_id else {}, json_data={"context_uri": uri})
        if result.get("status") in (200, 204):
            return f"Playing playlist: {name}"
        return f"Found '{name}' but couldn't start playback."