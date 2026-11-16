"""Build and runtime trust policy for the bundled Python plugins."""

REVIEWED_BUNDLED_PLUGINS = frozenset({
    "clipboard_history",
    "email_calendar",
    "example_weather",
    "github",
    "home_assistant",
    "notion",
    "ollama",
    "spotify",
    "system_monitor",
})

PLUGIN_RUNTIME_FILES = ("manifest.json", "plugin.py")
