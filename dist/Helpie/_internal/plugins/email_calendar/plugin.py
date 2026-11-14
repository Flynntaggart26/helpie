"""Email & Calendar Plugin for Helpie (Microsoft Graph / Gmail)."""
import json
import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional


class Plugin:
    def __init__(self):
        self.api = None
        self._token_lock = threading.Lock()
        self._access_token = None
        self._token_expiry = 0

    def init(self, api):
        self.api = api
        api.register_command(
            "read_email",
            self.read_email,
            "Read recent emails",
            ["read email", "check email", "show emails", "what emails", "email oku", "emailları oku"]
        )
        api.register_command(
            "send_email",
            self.send_email,
            "Send an email",
            ["send email", "send mail", "email to", "mail gönder", "eposta gönder"]
        )
        api.register_command(
            "calendar_events",
            self.calendar_events,
            "Show upcoming calendar events",
            ["calendar", "upcoming events", "my schedule", "what meetings", "ajanda", "toplantılarım"]
        )
        api.register_command(
            "create_event",
            self.create_event,
            "Create a calendar event",
            ["create event", "schedule meeting", "add to calendar", "toplantı ekle", "ajanda ekle"]
        )
        print("[EmailCalendar] Plugin loaded")

    def shutdown(self):
        print("[EmailCalendar] Plugin unloaded")

    # --- Settings helpers ---
    def _get_settings(self) -> dict:
        return {
            "provider": self.api.get_setting("provider", "microsoft"),
            "client_id": self.api.get_setting("client_id", ""),
            "client_secret": self.api.get_setting("client_secret", ""),
            "refresh_token": self.api.get_setting("refresh_token", ""),
            "default_folder": self.api.get_setting("default_folder", "inbox"),
            "max_emails": self.api.get_setting("max_emails", 5),
        }

    def _save_tokens(self, access_token: str, refresh_token: str, expires_in: int):
        self.api.set_setting("refresh_token", refresh_token)
        self._access_token = access_token
        self._token_expiry = time.time() + expires_in - 60  # 60s buffer

    def _get_access_token(self) -> Optional[str]:
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
            if settings["provider"] == "gmail":
                resp = requests.post("https://oauth2.googleapis.com/token", data=data, timeout=10)
            else:
                resp = requests.post("https://login.microsoftonline.com/common/oauth2/v2.0/token", data=data, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self._save_tokens(data["access_token"], data.get("refresh_token", ""), data.get("expires_in", 3600))
                return data["access_token"]
        except Exception as e:
            print(f"[EmailCalendar] Token refresh failed: {e}")
        return None

    def _graph_request(self, method: str, url: str, params: dict = None, json_data: dict = None) -> dict:
        token = self._get_access_token()
        if not token:
            return {"error": "Not authenticated. Please set up OAuth2 in Settings."}
        import requests
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            resp = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=15)
            if resp.status_code == 401:
                # Token expired, try once more
                with self._token_lock:
                    self._access_token = None
                token = self._get_access_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    resp = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=15)
            return {"status": resp.status_code, "json": resp.json() if resp.content else {}}
        except Exception as e:
            return {"error": str(e)}

    # --- Commands ---
    def read_email(self, args: dict = None) -> str:
        """Read recent emails."""
        settings = self._get_settings()
        folder = args.get("folder", settings["default_folder"]) if args else settings["default_folder"]
        max_items = args.get("max", settings["max_emails"]) if args else settings["max_emails"]

        provider = settings["provider"]
        if provider == "gmail":
            return self._read_gmail(folder, max_items)
        else:
            return self._read_outlook(folder, max_items)

    def _read_outlook(self, folder: str, max_items: int) -> str:
        result = self._graph_request("GET", f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages",
                                     params={"$top": max_items, "$orderby": "receivedDateTime desc",
                                             "$select": "subject,from,receivedDateTime,bodyPreview,isRead"})
        if "error" in result:
            return f"Outlook error: {result['error']}"
        if result["status"] != 200:
            return f"Outlook error: {result['json']}"
        messages = result["json"].get("value", [])
        if not messages:
            return "No emails found."
        lines = [f"📧 Recent emails ({len(messages)}):"]
        for i, msg in enumerate(messages, 1):
            sender = msg.get("from", {}).get("emailAddress", {}).get("name", "Unknown")
            subject = msg.get("subject", "(no subject)")
            preview = msg.get("bodyPreview", "")[:80]
            read = "✓" if msg.get("isRead") else "●"
            lines.append(f"  {i+1}. {read} {sender}: {subject} — {preview}...")
        return "\n".join(lines)

    def _read_gmail(self, folder: str, max_items: int) -> str:
        # Gmail API would go here
        return "Gmail support not yet implemented. Use Microsoft provider for now."

    def send_email(self, args: dict = None) -> str:
        """Send an email. Args: to, subject, body, cc, bcc."""
        to = (args or {}).get("to", "")
        subject = (args or {}).get("subject", "")
        body = (args or {}).get("body", "")
        if not to or not subject or not body:
            return "Usage: send email to <address> subject <subject> body <text>"

        settings = self._get_settings()
        provider = settings["provider"]
        if provider == "gmail":
            return "Gmail send not yet implemented."
        return self._send_outlook(to, subject, body)

    def _send_outlook(self, to: str, subject: str, body: str) -> str:
        result = self._graph_request("POST", "https://graph.microsoft.com/v1.0/me/sendMail",
                                     json_data={
                                         "message": {
                                             "subject": subject,
                                             "body": {"contentType": "Text", "content": body},
                                             "toRecipients": [{"emailAddress": {"address": to}}],
                                         },
                                         "saveToSentItems": "true"
                                     })
        if "error" in result:
            return f"Failed: {result['error']}"
        if result["status"] in (200, 202):
            return f"Email sent to {to}."
        return f"Failed to send: {result['json']}"

    def calendar_events(self, args: dict = None) -> str:
        """Show upcoming calendar events."""
        max_items = (args or {}).get("max", 10)
        settings = self._get_settings()
        if settings["provider"] == "gmail":
            return "Gmail calendar not yet implemented."
        return self._calendar_outlook(max_items)

    def _calendar_outlook(self, max_items: int) -> str:
        from datetime import datetime, timedelta
        now = datetime.utcnow().isoformat() + "Z"
        end = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
        result = self._graph_request("GET", "https://graph.microsoft.com/v1.0/me/calendar/events",
                                     params={"$top": max_items, "$orderby": "start/dateTime asc",
                                             "$filter": f"start/dateTime ge '{now}' and end/dateTime le '{end}'",
                                             "$select": "subject,start,end,location,attendees"})
        if "error" in result:
            return f"Calendar error: {result['error']}"
        if result["status"] != 200:
            return f"Calendar error: {result['json']}"
        events = result["json"].get("value", [])
        if not events:
            return "No upcoming events."
        lines = [f"📅 Upcoming events ({len(events)}):"]
        for ev in events:
            subject = ev.get("subject", "(no title)")
            start = ev.get("start", {}).get("dateTime", "")
            end = ev.get("end", {}).get("dateTime", "")
            location = ev.get("location", {}).get("displayName", "")
            loc_str = f" @ {location}" if location else ""
            lines.append(f"  • {subject} ({start} → {end}){loc_str}")
        return "\n".join(lines)

    def create_event(self, args: dict = None) -> str:
        """Create a calendar event. Args: subject, start, end, location, attendees."""
        subject = (args or {}).get("subject", "")
        start = (args or {}).get("start", "")
        end = (args or {}).get("end", "")
        location = (args or {}).get("location", "")
        attendees = (args or {}).get("attendees", [])

        if not subject or not start or not end:
            return "Usage: create event subject <title> start <ISO datetime> end <ISO datetime> [location] [attendees]"

        settings = self._get_settings()
        if settings["provider"] == "gmail":
            return "Gmail calendar not yet implemented."
        return self._create_outlook_event(subject, start, end, location, attendees)

    def _create_outlook_event(self, subject: str, start: str, end: str, location: str, attendees: list) -> str:
        attendee_list = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees]
        body = {
            "subject": subject,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
            "location": {"displayName": location} if location else {},
            "attendees": attendee_list,
        }
        result = self._graph_request("POST", "https://graph.microsoft.com/v1.0/me/events", json_data=body)
        if "error" in result:
            return f"Failed: {result['error']}"
        if result["status"] in (200, 201):
            return f"Event created: {subject}"
        return f"Failed: {result['json']}"