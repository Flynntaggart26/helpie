"""Windows bildirimleri (balon bildirim)."""
from __future__ import annotations

import subprocess

CREATE_NO_WINDOW = 0x08000000


def _escape(text: str) -> str:
    return str(text).replace("'", "''").replace("\n", " ")


def toast(title: str, message: str) -> None:
    """Görev çubuğunda kısa süreli bir bildirim gösterir."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; "
        "$n.Visible = $true; "
        f"$n.ShowBalloonTip(7000, '{_escape(title)}', '{_escape(message)}', "
        "[System.Windows.Forms.ToolTipIcon]::Info); "
        "Start-Sleep -Seconds 7; $n.Dispose()"
    )
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         creationflags=CREATE_NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
