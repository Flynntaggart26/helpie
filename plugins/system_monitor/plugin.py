"""System Monitor Plugin for Helpie."""
import json
import threading
import time
from pathlib import Path


class Plugin:
    def __init__(self):
        self.api = None
        self._monitor_thread = None
        self._stop_monitor = threading.Event()
        self._last_alerts = {}

    def init(self, api):
        self.api = api
        api.register_command(
            "system_stats",
            self.show_stats,
            "Show current system statistics",
            ["system stats", "system status", "cpu usage", "memory usage", "disk usage", "system monitor", "sistem durumu"]
        )
        api.register_command(
            "system_top_processes",
            self.show_top_processes,
            "Show top processes by CPU/memory",
            ["top processes", "running processes", "what is using cpu", "hanging processes"]
        )
        api.register_command(
            "system_alert",
            self.set_alert,
            "Set threshold alerts for CPU/memory/disk",
            ["alert when cpu", "alert when memory", "alert when disk", "notify me when"]
        )

        # Start background monitor
        self._start_monitor()

        print("[SystemMonitor] Plugin loaded")

    def shutdown(self):
        self._stop_monitor.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
        print("[SystemMonitor] Plugin unloaded")

    def on_interval(self):
        """Called periodically - check thresholds."""
        self._check_thresholds()

    def _start_monitor(self):
        interval = self.api.get_setting("refresh_interval", 30)
        if interval <= 0:
            return
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True, name="system-monitor")
        self._monitor_thread.start()

    def _monitor_loop(self):
        while not self._stop_monitor.is_set():
            try:
                self._check_thresholds()
            except Exception:
                pass
            interval = self.api.get_setting("refresh_interval", 30)
            for _ in range(interval):
                if self._stop_monitor.is_set():
                    break
                time.sleep(1.0)

    def _check_thresholds(self):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            cpu_thresh = self.api.get_setting("cpu_alert_threshold", 90)
            mem_thresh = self.api.get_setting("memory_alert_threshold", 85)
            disk_thresh = self.api.get_setting("disk_alert_threshold", 90)

            alerts = []
            if cpu >= cpu_thresh and self._should_alert("cpu", cpu):
                alerts.append(f"CPU at {cpu:.0f}% (threshold: {cpu_thresh}%)")
            if mem.percent >= mem_thresh and self._should_alert("memory", mem.percent):
                alerts.append(f"Memory at {mem.percent:.0f}% (threshold: {mem_thresh}%)")
            if disk.percent >= disk_thresh and self._should_alert("disk", disk.percent):
                alerts.append(f"Disk at {disk.percent:.0f}% (threshold: {disk_thresh}%)")

            for alert in alerts:
                self.api.speak(f"⚠️ System alert: {alert}")
                self.api.show_toast(f"System Alert: {alert}")
        except Exception:
            pass

    def _should_alert(self, key: str, value: float) -> bool:
        """Throttle alerts - only alert once per threshold crossing."""
        last = self._last_alerts.get(key, 0)
        if value >= 90:  # Always alert on critical
            self._last_alerts[key] = value
            return True
        if value < 50:  # Reset when back to normal
            self._last_alerts.pop(key, None)
            return False
        return value > last + 5  # Alert on 5% increase

    def _run_psutil(self, func):
        import psutil
        return func(psutil)

    # --- Commands ---
    def show_stats(self, args: dict = None) -> str:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            net = psutil.net_io_counters()

            lines = [
                "💻 System Statistics",
                f"  CPU: {cpu:.1f}%",
                f"  Memory: {mem.percent:.1f}% ({mem.used // (1024**3):.1f}GB / {mem.total // (1024**3):.1f}GB)",
                f"  Disk: {disk.percent:.1f}% ({disk.used // (1024**3):.1f}GB / {disk.total // (1024**3):.1f}GB)",
                f"  Network: ↑ {net.bytes_sent // (1024**2)}MB ↓ {net.bytes_recv // (1024**2)}MB",
            ]

            # GPU if enabled
            if self.api.get_setting("enable_gpu", False):
                try:
                    import subprocess
                    result = subprocess.run(
                        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        for line in result.stdout.strip().split("\n"):
                            gpu_util, mem_used, mem_total = line.split(", ")
                            lines.append(f"  GPU: {gpu_util}% | VRAM: {mem_used}MB / {mem_total}MB")
                except Exception:
                    pass

            return "\n".join(lines)
        except Exception as e:
            return f"Failed to get stats: {e}"

    def show_top_processes(self, args: dict = None) -> str:
        try:
            import psutil
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    procs.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Sort by CPU
            cpu_sorted = sorted([p for p in procs if p["cpu_percent"] > 0.5],
                                key=lambda x: x["cpu_percent"], reverse=True)[:5]
            lines = ["🔥 Top CPU processes:"]
            for p in cpu_sorted:
                lines.append(f"  {p['name']} (PID {p['pid']}): {p['cpu_percent']:.1f}% CPU, {p['memory_percent']:.1f}% RAM")

            # Sort by Memory
            mem_sorted = sorted([p for p in procs if p["memory_percent"] > 1.0],
                                key=lambda x: x["memory_percent"], reverse=True)[:5]
            lines.append("\n🧠 Top Memory processes:")
            for p in mem_sorted:
                lines.append(f"  {p['name']} (PID {p['pid']}): {p['memory_percent']:.1f}% RAM, {p['cpu_percent']:.1f}% CPU")

            return "\n".join(lines)
        except Exception as e:
            return f"Failed to get processes: {e}"

    def set_alert(self, args: dict = None) -> str:
        """Set custom alert threshold via voice."""
        # This would parse natural language like "alert me when cpu goes above 80"
        return "Use Settings to configure alert thresholds. Example: 'Settings → System Monitor → CPU alert at 80%'."