#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Helpie desktop shell.
//!
//! Owns the window, spawns the Python backend as a sidecar (`helpie-core.exe`),
//! waits for its HTTP server, then loads the UI. The backend asks for windows
//! through a tiny localhost control endpoint started here.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{
    AppHandle, Manager, PhysicalPosition, PhysicalSize, Url, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder, WindowEvent,
};

#[cfg(windows)]
mod capture;

/// Set by `--hidden` (autostart): start the backend without popping the window.
static START_HIDDEN: AtomicBool = AtomicBool::new(false);
/// Set once the user explicitly asked for the window (Ctrl+H), so the late
/// "stay hidden" enforcement stops fighting them.
static USER_SHOWED: AtomicBool = AtomicBool::new(false);

const MAIN_W: f64 = 1180.0;
const MAIN_H: f64 = 780.0;
const TINY_W: f64 = 380.0;
const TINY_H: f64 = 220.0;
const MAX_CONTROL_HEADER: usize = 4096;

struct Backend {
    child: Mutex<Option<Child>>,
    port: Mutex<u16>,
}

/// Tracks every overlay window, one per monitor, so they can be shown and
/// hidden together. Window names are unique (`overlay-0`, `overlay-1`, …).
struct OverlayWindows {
    handles: Mutex<Vec<WebviewWindow>>,
}

// --------------------------------------------------------------------------- //
//  Paths and probing
// --------------------------------------------------------------------------- //
fn data_dir() -> PathBuf {
    // The Python backend honours HELPIE_DATA_DIR, so the shell must use the
    // same directory or the two disagree about where port.txt lives.
    if let Ok(override_dir) = std::env::var("HELPIE_DATA_DIR") {
        let trimmed = override_dir.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    match std::env::var("APPDATA") {
        Ok(base) => PathBuf::from(base).join("Helpie"),
        Err(_) => PathBuf::from("data"),
    }
}

/// Small append-only log so a failed start on someone else's machine is
/// diagnosable instead of a silent splash screen.
fn log(message: &str) {
    use std::io::Write as _;
    let _ = std::fs::create_dir_all(data_dir());
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(data_dir().join("shell.log"))
    {
        let _ = writeln!(file, "{message}");
    }
}

fn read_port_file() -> Option<u16> {
    std::fs::read_to_string(data_dir().join("port.txt"))
        .ok()
        .and_then(|raw| raw.trim().parse::<u16>().ok())
}

/// The health probe request. The Host header must carry the port: the backend
/// rejects any Host that is not exactly `127.0.0.1:<port>` with 421, so a
/// port-less Host makes the shell think its own backend never started.
fn health_request(port: u16) -> String {
    format!("GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n")
}

/// True when something answers `/api/health` with a 200 on this port.
fn http_ok(port: u16) -> bool {
    let addr = match format!("127.0.0.1:{port}").parse() {
        Ok(addr) => addr,
        Err(_) => return false,
    };
    let mut stream = match TcpStream::connect_timeout(&addr, Duration::from_millis(600)) {
        Ok(stream) => stream,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    if stream.write_all(health_request(port).as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 256];
    match stream.read(&mut buf) {
        Ok(n) if n > 0 => String::from_utf8_lossy(&buf[..n]).contains("200"),
        _ => false,
    }
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(8765)
}

fn base_url(port: u16) -> String {
    format!("http://127.0.0.1:{port}")
}

// --------------------------------------------------------------------------- //
//  Backend sidecar
// --------------------------------------------------------------------------- //
fn sidecar_path() -> Option<PathBuf> {
    let exe_dir = std::env::current_exe().ok()?.parent()?.to_path_buf();

    // Installed layout puts the folder next to the shell; the dev layout keeps
    // it under src-tauri/sidecar. Try both so `cargo run` works too.
    let candidates = [
        exe_dir.join("helpie-core").join("helpie-core.exe"),
        exe_dir
            .join("sidecar")
            .join("helpie-core")
            .join("helpie-core.exe"),
        exe_dir.join("helpie-core.exe"),
        exe_dir
            .join("sidecar")
            .join("helpie-core")
            .join("helpie-core.exe"),
    ];
    candidates.into_iter().find(|path| path.exists())
}

/// Older installers shipped `helpie-core.exe` next to the shell; 1.16.1 ships a
/// folder. Remove the leftover so a stale 80 MB binary does not linger after an
/// upgrade (nothing probes it any more).
fn cleanup_legacy_sidecar() {
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    let Some(dir) = exe.parent() else {
        return;
    };
    let legacy = dir.join("helpie-core.exe");
    if dir.join("helpie-core").join("helpie-core.exe").exists()
        && legacy.exists()
        && std::fs::remove_file(&legacy).is_ok()
    {
        log("cleanup: removed legacy helpie-core.exe");
    }
}

fn spawn_backend(port: u16, control_port: u16, control_token: &str) -> Option<Child> {
    let exe = sidecar_path()?;
    let mut command = Command::new(&exe);
    command
        .env("HELPIE_PORT", port.to_string())
        .env("HELPIE_CONTROL_PORT", control_port.to_string())
        .env("HELPIE_CONTROL_TOKEN", control_token)
        .env("HELPIE_NO_BROWSER", "1")
        .env("HELPIE_DATA_DIR", data_dir())
        .current_dir(exe.parent()?);

    // Keep an autostart launch silent: no greeting, no voice, no window.
    if START_HIDDEN.load(Ordering::Relaxed) {
        command.arg("--hidden");
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    match command.spawn() {
        Ok(child) => Some(child),
        Err(err) => {
            eprintln!("[helpie] could not start backend: {err}");
            None
        }
    }
}

// --------------------------------------------------------------------------- //
//  Windows
// --------------------------------------------------------------------------- //
fn show_main(app: &AppHandle, port: u16, force: bool) {
    let base = base_url(port);
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let current = window.url().map(|url| url.to_string()).unwrap_or_default();
    if !current.starts_with(&base) {
        // window.eval is used instead of a Rust navigation call so it also works
        // once the webview is showing a remote (localhost) page.
        let _ = window.eval(&format!("location.replace('{base}/');"));
    }
    if force || !START_HIDDEN.load(Ordering::Relaxed) {
        if force {
            USER_SHOWED.store(true, Ordering::Relaxed);
            hide_tiny(app);
            hide_overlay(app);
        }
        let _ = window.show();
        let _ = window.set_focus();
        return;
    }

    // WebView2 shows the host window when the webview finishes attaching, which
    // undoes `visible(false)`. The backend can take a while to boot, so keep
    // pushing it back down until the page has settled.
    let hidden_window = window.clone();
    std::thread::spawn(move || {
        for _ in 0..150 {
            std::thread::sleep(Duration::from_millis(400));
            if USER_SHOWED.load(Ordering::Relaxed) {
                return;
            }
            if hidden_window.is_visible().unwrap_or(false) {
                let _ = hidden_window.hide();
            }
        }
    });
}

fn tiny_position(app: &AppHandle) -> PhysicalPosition<i32> {
    let monitor = app
        .primary_monitor()
        .ok()
        .flatten()
        .or_else(|| app.available_monitors().ok()?.into_iter().next());
    let Some(monitor) = monitor else {
        return PhysicalPosition::new(16, 16);
    };
    let origin = monitor.position();
    let size = monitor.size();
    let scale = monitor.scale_factor();
    let width = (TINY_W * scale).round() as i32;
    let height = (TINY_H * scale).round() as i32;
    let margin = (16.0 * scale).round() as i32;
    PhysicalPosition::new(
        origin.x + (size.width as i32 - width - margin).max(0),
        origin.y + (size.height as i32 - height - margin).max(0),
    )
}

fn show_tiny(app: &AppHandle, port: u16) {
    let base = base_url(port);
    let url = format!("{base}/?view=tiny");

    if let Some(window) = app.get_webview_window("tiny") {
        let _ = window.eval(&format!("location.replace('{url}');"));
        let _ = window.set_position(tiny_position(app));
        let _ = window.show();
        let _ = window.set_focus();
        return;
    }

    let parsed = match Url::parse(&url) {
        Ok(parsed) => parsed,
        Err(_) => return,
    };
    let built = WebviewWindowBuilder::new(app, "tiny", WebviewUrl::External(parsed))
        .title("Helpie")
        .inner_size(TINY_W, TINY_H)
        .resizable(false)
        .maximizable(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(true)
        .visible(false)
        .build();

    match built {
        Ok(window) => {
            let _ = window.set_position(tiny_position(app));
            let _ = window.show();
            let _ = window.set_focus();
        }
        Err(err) => eprintln!("[helpie] could not open tiny window: {err}"),
    }
}

fn hide_tiny(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("tiny") {
        let _ = window.hide();
    }
}

// --------------------------------------------------------------------------- //
//  Screen overlay
// --------------------------------------------------------------------------- //
// The overlay is the Phase 1 annotation layer: a transparent, click-through
// window that covers the primary monitor and never takes focus. It draws a
// marker that is deliberately distinct from the user's pointer. It is a visual
// surface only - it cannot click, type, or capture screen pixels. The delayed
// pointer echo is sampled locally by the backend while this window is visible.
fn show_overlay(app: &AppHandle, port: u16) {
    let url = format!("{}/?view=overlay", base_url(port));

    // Existing overlay windows already have their monitor bounds in the URL.
    {
        let state = app.state::<OverlayWindows>();
        let handles = state.handles.lock().unwrap();
        if !handles.is_empty() {
            for window in handles.iter() {
                let _ = window.eval("window.helpieResumeOverlay?.();");
                show_without_activation(window);
            }
            return;
        }
    }

    // Create one overlay window per monitor so the annotation layer covers
    // every display, including mixed-DPI setups. Physical coordinates place
    // each window exactly on its monitor regardless of scale factor.
    let mut new_handles = Vec::new();
    match app.available_monitors() {
        Ok(monitors) => {
            for (index, monitor) in monitors.iter().enumerate() {
                let window_name = format!("overlay-{}", index);
                let position = monitor.position();
                let size = monitor.size();
                let mut monitor_url = match Url::parse(&url) {
                    Ok(p) => p,
                    Err(_) => continue,
                };
                monitor_url
                    .query_pairs_mut()
                    .append_pair("screen_x", &position.x.to_string())
                    .append_pair("screen_y", &position.y.to_string())
                    .append_pair("screen_w", &size.width.to_string())
                    .append_pair("screen_h", &size.height.to_string());
                let parsed = monitor_url;
                let built =
                    WebviewWindowBuilder::new(app, &window_name, WebviewUrl::External(parsed))
                        .title("Helpie overlay")
                        .decorations(false)
                        .transparent(true)
                        .shadow(false)
                        .resizable(false)
                        .maximizable(false)
                        .minimizable(false)
                        .always_on_top(true)
                        .skip_taskbar(true)
                        .focused(false)
                        .visible(false)
                        .build();

                if let Ok(window) = built {
                    // Click-through: the overlay must never sit between the
                    // user and their work.
                    let _ = window.set_ignore_cursor_events(true);
                    let _ = window.set_position(PhysicalPosition::new(position.x, position.y));
                    let _ = window.set_size(PhysicalSize::new(size.width, size.height));
                    show_without_activation(&window);
                    new_handles.push(window);
                }
            }
        }
        Err(err) => eprintln!("[helpie] could not enumerate monitors: {err}"),
    }

    if !new_handles.is_empty() {
        let state = app.state::<OverlayWindows>();
        let mut handles = state.handles.lock().unwrap();
        *handles = new_handles;
    }
}

fn hide_overlay(app: &AppHandle) {
    let state = app.state::<OverlayWindows>();
    let handles = state.handles.lock().unwrap();
    for window in handles.iter() {
        let _ = window.eval("window.helpieOverlayActive = false;");
        hide_without_activation(window);
    }
}

fn show_companion(app: &AppHandle, port: u16) {
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.hide();
    }
    show_overlay(app, port);
    show_tiny(app, port);
}

/// Hide through Win32 rather than `window.hide()`.
///
/// The overlay is shown with a raw `ShowWindow`, so tao's tracked window flags
/// still say "hidden". `hide()` only applies a *diff* against those flags, so it
/// does nothing and the overlay stays on screen.
#[cfg(windows)]
fn hide_without_activation(window: &WebviewWindow) {
    use std::ffi::c_void;

    #[link(name = "user32")]
    extern "system" {
        fn ShowWindow(hwnd: *mut c_void, cmd: i32) -> i32;
    }

    const SW_HIDE: i32 = 0;

    if let Ok(hwnd) = window.hwnd() {
        unsafe {
            ShowWindow(hwnd.0 as *mut c_void, SW_HIDE);
        }
    }
}

#[cfg(not(windows))]
fn hide_without_activation(window: &WebviewWindow) {
    let _ = window.hide();
}

/// Show a window without activating it, so the overlay never steals focus from
/// whatever the user is doing.
#[cfg(windows)]
fn show_without_activation(window: &WebviewWindow) {
    use std::ffi::c_void;

    #[link(name = "user32")]
    extern "system" {
        fn ShowWindow(hwnd: *mut c_void, cmd: i32) -> i32;
        fn GetWindowLongPtrW(hwnd: *mut c_void, index: i32) -> isize;
        fn SetWindowLongPtrW(hwnd: *mut c_void, index: i32, value: isize) -> isize;
    }

    const GWL_EXSTYLE: i32 = -20;
    const WS_EX_TRANSPARENT: isize = 0x0000_0020;
    const WS_EX_TOOLWINDOW: isize = 0x0000_0080;
    const WS_EX_NOACTIVATE: isize = 0x0800_0000;
    const SW_SHOWNOACTIVATE: i32 = 4;

    let Ok(hwnd) = window.hwnd() else {
        return;
    };
    let raw = hwnd.0 as *mut c_void;
    unsafe {
        let style = GetWindowLongPtrW(raw, GWL_EXSTYLE);
        SetWindowLongPtrW(
            raw,
            GWL_EXSTYLE,
            style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        );
        ShowWindow(raw, SW_SHOWNOACTIVATE);
    }
}

#[cfg(not(windows))]
fn show_without_activation(window: &WebviewWindow) {
    let _ = window.show();
}

// --------------------------------------------------------------------------- //
//  Tray
// --------------------------------------------------------------------------- //
fn current_port(app: &AppHandle) -> Option<u16> {
    let state = app.try_state::<Backend>()?;
    let port = *state.port.lock().ok()?;
    if port == 0 {
        read_port_file()
    } else {
        Some(port)
    }
}

fn setup_tray(app: &AppHandle) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Show Helpie", true, None::<&str>)?;
    let tiny = MenuItem::with_id(app, "tiny", "Show companion", true, None::<&str>)?;
    let overlay = MenuItem::with_id(app, "overlay", "Show screen overlay", true, None::<&str>)?;
    let hide = MenuItem::with_id(
        app,
        "hide-overlay",
        "Hide screen overlay",
        true,
        None::<&str>,
    )?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Helpie", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &tiny, &overlay, &hide, &separator, &quit])?;

    let mut builder = TrayIconBuilder::with_id("helpie-tray")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .tooltip("Helpie");
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }

    builder
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => {
                if let Some(port) = current_port(app) {
                    show_main(app, port, true);
                }
            }
            "tiny" => {
                if let Some(port) = current_port(app) {
                    show_companion(app, port);
                }
            }
            "overlay" => {
                if let Some(port) = current_port(app) {
                    show_overlay(app, port);
                }
            }
            "hide-overlay" => hide_overlay(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;

    Ok(())
}

// --------------------------------------------------------------------------- //
//  Control endpoint used by the Python backend
// --------------------------------------------------------------------------- //
fn new_control_token() -> Option<String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).ok()?;
    Some(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn start_control(app: AppHandle, backend_port: u16, token: String) -> std::io::Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();

    std::thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            handle_control(&app, backend_port, &token, stream);
        }
    });

    Ok(port)
}

fn read_control_headers(stream: &mut TcpStream) -> Result<Vec<u8>, u16> {
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .map_err(|_| 400u16)?;
    let mut request_bytes = Vec::with_capacity(512);
    let mut chunk = [0u8; 512];
    loop {
        let read = match stream.read(&mut chunk) {
            Ok(0) => return Err(400),
            Ok(read) => read,
            Err(_) => return Err(400),
        };
        request_bytes.extend_from_slice(&chunk[..read]);
        if request_bytes.len() > MAX_CONTROL_HEADER {
            return Err(431);
        }
        if request_bytes.windows(4).any(|window| window == b"\r\n\r\n") {
            return Ok(request_bytes);
        }
    }
}

fn write_control_error(stream: &mut TcpStream, status: u16) {
    let response: &[u8] = match status {
        431 => b"HTTP/1.1 431 Request Header Fields Too Large\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        _ => b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
    };
    let _ = stream.write_all(response);
}

fn handle_control(app: &AppHandle, port: u16, token: &str, mut stream: TcpStream) {
    let request_bytes = match read_control_headers(&mut stream) {
        Ok(bytes) => bytes,
        Err(status) => {
            write_control_error(&mut stream, status);
            return;
        }
    };

    let request = String::from_utf8_lossy(&request_bytes).to_string();
    let mut lines = request.split("\r\n");
    let mut request_line = lines.next().unwrap_or("").split_whitespace();
    let method = request_line.next().unwrap_or("");
    let target = request_line.next().unwrap_or("");
    let version = request_line.next().unwrap_or("");
    if !matches!(method, "GET" | "POST")
        || !matches!(version, "HTTP/1.0" | "HTTP/1.1")
        || request_line.next().is_some()
    {
        let _ = stream.write_all(
            b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        );
        return;
    }

    let mut supplied_token = None;
    let mut duplicate_token = false;
    for line in lines {
        if line.is_empty() {
            break;
        }
        if let Some((name, value)) = line.split_once(':') {
            if name.eq_ignore_ascii_case("x-helpie-control-token") {
                if supplied_token.is_some() {
                    duplicate_token = true;
                    break;
                }
                supplied_token = Some(value.trim());
            }
        }
    }
    if duplicate_token || !supplied_token.is_some_and(|value| token_matches(value, token)) {
        let _ = stream
            .write_all(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
        return;
    }

    let action = target
        .strip_prefix('/')
        .unwrap_or("")
        .split('?')
        .next()
        .unwrap_or("")
        .to_string();
    if action == "capture" {
        if method != "POST" || target != "/capture" {
            let _ = stream.write_all(
                b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            );
            return;
        }
        #[cfg(windows)]
        match capture::capture_one_frame() {
            Ok(Some((image, target_name))) => {
                let safe_target: String = target_name
                    .chars()
                    .filter(|character| character.is_ascii_graphic() || *character == ' ')
                    .take(200)
                    .collect();
                let header = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nContent-Length: {}\r\nX-Helpie-Capture-Target: {}\r\nConnection: close\r\n\r\n",
                    image.len(), safe_target
                );
                if stream.write_all(header.as_bytes()).is_ok() {
                    let _ = stream.write_all(&image);
                }
            }
            Ok(None) => {
                let _ = stream.write_all(
                    b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                );
            }
            Err(_) => {
                let _ = stream.write_all(
                    b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                );
            }
        }
        #[cfg(not(windows))]
        let _ = stream.write_all(
            b"HTTP/1.1 501 Not Implemented\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        );
        return;
    }
    if !matches!(
        action.as_str(),
        "full" | "focus" | "companion" | "tiny" | "hide-tiny" | "overlay" | "hide-overlay" | "quit"
    ) {
        let _ = stream
            .write_all(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
        return;
    }

    if method != "GET" {
        let _ = stream.write_all(
            b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
        );
        return;
    }

    match action.as_str() {
        "full" | "focus" => show_main(app, port, true),
        "companion" => show_companion(app, port),
        "tiny" => show_tiny(app, port),
        "hide-tiny" => hide_tiny(app),
        "overlay" => show_overlay(app, port),
        "hide-overlay" => hide_overlay(app),
        "quit" => app.exit(0),
        _ => {}
    }

    let _ =
        stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok");
}

fn token_matches(supplied: &str, expected: &str) -> bool {
    if supplied.len() != expected.len() {
        return false;
    }
    supplied
        .bytes()
        .zip(expected.bytes())
        .fold(0u8, |difference, (left, right)| difference | (left ^ right))
        == 0
}

#[cfg(test)]
mod control_tests {
    use super::{health_request, read_control_headers, TcpListener, TcpStream};
    use std::io::Write;
    use std::thread;
    use std::time::Duration;

    /// Regression: the backend answers 421 to any Host that is not exactly
    /// `127.0.0.1:<port>`, so a port-less Host silently stopped the shell from
    /// starting its own backend.
    #[test]
    fn health_probe_sends_the_port_in_the_host_header() {
        let request = health_request(58538);
        assert!(
            request.contains("Host: 127.0.0.1:58538\r\n"),
            "health probe must send the port in Host: {request:?}"
        );
        assert!(request.starts_with("GET /api/health HTTP/1.1\r\n"));
    }

    #[test]
    fn fragmented_control_header_is_reassembled() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind test listener");
        let address = listener.local_addr().expect("read test address");
        let sender = thread::spawn(move || {
            let mut client = TcpStream::connect(address).expect("connect test client");
            client
                .write_all(b"GET /tiny HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Helpie-Control-")
                .expect("send first header fragment");
            thread::sleep(Duration::from_millis(25));
            client
                .write_all(b"Token: test-token\r\nConnection: close\r\n\r\n")
                .expect("send second header fragment");
        });

        let (mut stream, _) = listener.accept().expect("accept test client");
        let header = read_control_headers(&mut stream).expect("reassemble full header");
        sender.join().expect("finish test sender");
        let header = String::from_utf8(header).expect("valid UTF-8 header");
        assert!(header.contains("X-Helpie-Control-Token: test-token"));
        assert!(header.ends_with("\r\n\r\n"));
    }
}

// --------------------------------------------------------------------------- //
//  Boot sequence
// --------------------------------------------------------------------------- //
fn show_error(app: &AppHandle, title: &str, detail: &str) {
    log(&format!("ERROR {title}: {detail}"));
    USER_SHOWED.store(true, Ordering::Relaxed);

    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    // The splash page may not have parsed yet when boot fails, so retry until
    // the card exists instead of silently doing nothing.
    let script = format!(
        r#"(function(){{
  var tries = 0;
  function paint() {{
    var card = document.querySelector('.card');
    if (!card) {{
      if (tries++ < 60) setTimeout(paint, 250);
      return;
    }}
    card.innerHTML =
      '<div class="mark" style="background:linear-gradient(145deg,#b91c1c,#7f1d1d)">!</div>' +
      '<h1>{title}</h1>' +
      '<p style="max-width:340px;line-height:1.55">{detail}</p>' +
      '<p style="margin-top:16px;font-size:11px;color:#6b7280">Details: %APPDATA%\Helpie\shell.log</p>';
  }}
  paint();
}})();"#
    );
    let _ = window.eval(&script);
    let _ = window.show();
    let _ = window.set_focus();
}

fn boot(app: AppHandle) {
    log("boot: start");
    cleanup_legacy_sidecar();

    // Reuse an already running backend instead of starting a second one.
    if let Some(existing) = read_port_file() {
        log(&format!(
            "boot: probing existing backend on port {existing}"
        ));
        if http_ok(existing) {
            log("boot: reusing running backend");
            if let Some(state) = app.try_state::<Backend>() {
                *state.port.lock().unwrap() = existing;
            }
            show_main(&app, existing, false);
            return;
        }
    }

    let sidecar = sidecar_path();
    match sidecar.as_ref() {
        Some(path) => log(&format!("boot: sidecar at {}", path.display())),
        None => log(&format!(
            "boot: sidecar not found next to {}",
            std::env::current_exe()
                .map(|path| path.display().to_string())
                .unwrap_or_else(|_| "?".into())
        )),
    }

    let port = free_port();
    let Some(control_token) = new_control_token() else {
        show_error(
            &app,
            "Helpie could not start",
            "Secure window control could not be initialized.",
        );
        return;
    };
    let control = start_control(app.clone(), port, control_token.clone()).unwrap_or(0);
    log(&format!(
        "boot: backend port {port}, control port {control}"
    ));

    let _ = std::fs::create_dir_all(data_dir());
    if control > 0 {
        let _ = std::fs::write(data_dir().join("control_port.txt"), control.to_string());
    }

    let child = spawn_backend(port, control, &control_token);
    if child.is_none() {
        show_error(
            &app,
            "Helpie could not start",
            "The assistant engine is missing from the installation. \
             Reinstall Helpie from the latest release and try again.",
        );
        return;
    }
    if let Some(state) = app.try_state::<Backend>() {
        *state.child.lock().unwrap() = child;
        *state.port.lock().unwrap() = port;
    }

    // A folder build starts in a second or two; 60 s still covers a cold start
    // on a slow disk without leaving the user staring at a spinner.
    let deadline = Instant::now() + Duration::from_secs(60);
    let mut healthy = false;
    while Instant::now() < deadline {
        if http_ok(port) {
            healthy = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(400));
    }

    if !healthy {
        log("boot: backend never answered /api/health");
        show_error(
            &app,
            "Helpie could not start",
            "The assistant engine did not respond in time. \
             Your antivirus may have blocked it, or another program is using the required port. \
             Restart your computer and try again.",
        );
        return;
    }

    log("boot: backend healthy");
    show_main(&app, port, false);
}

#[cfg(windows)]
fn message_box(title: &str, body: &str) {
    use std::os::windows::ffi::OsStrExt;

    #[link(name = "user32")]
    extern "system" {
        fn MessageBoxW(
            hwnd: *mut std::ffi::c_void,
            text: *const u16,
            caption: *const u16,
            utype: u32,
        ) -> i32;
    }

    let wide = |value: &str| -> Vec<u16> {
        std::ffi::OsStr::new(value)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    };
    let text = wide(body);
    let caption = wide(title);
    // MB_ICONERROR | MB_SETFOREGROUND
    unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            text.as_ptr(),
            caption.as_ptr(),
            0x0000_0010 | 0x0001_0000,
        );
    }
}

#[cfg(not(windows))]
fn message_box(title: &str, body: &str) {
    eprintln!("{title}: {body}");
}

fn main() {
    tauri::Builder::default()
        .manage(Backend {
            child: Mutex::new(None),
            port: Mutex::new(0),
        })
        .manage(OverlayWindows {
            handles: Mutex::new(Vec::new()),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            let args: Vec<String> = std::env::args().collect();
            let hidden = args.iter().any(|arg| arg == "--hidden");
            START_HIDDEN.store(hidden, Ordering::Relaxed);

            let _ = std::fs::create_dir_all(data_dir());
            // Fresh log per launch so the file cannot grow without bound.
            let _ = std::fs::write(data_dir().join("shell.log"), "");
            log(&format!(
                "start: v{} args={:?} hidden={}",
                env!("CARGO_PKG_VERSION"),
                args,
                hidden
            ));

            let window =
                match WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                    .title("Helpie")
                    .inner_size(MAIN_W, MAIN_H)
                    .min_inner_size(760.0, 520.0)
                    .center()
                    .visible(!hidden)
                    .build()
                {
                    Ok(window) => window,
                    Err(err) => {
                        log(&format!("fatal: could not create main window: {err}"));
                        message_box(
                            "Helpie could not start",
                            &format!(
                                "Helpie could not open its window.\n\n{err}\n\n\
                             This usually means Microsoft Edge WebView2 is missing or \
                             damaged. Install it from\n\
                             https://go.microsoft.com/fwlink/p/?LinkId=2124703\n\
                             then start Helpie again."
                            ),
                        );
                        std::process::exit(1);
                    }
                };

            if hidden {
                let _ = window.hide();
            }

            if let Err(err) = setup_tray(app.handle()) {
                log(&format!("tray: {err}"));
            }

            std::thread::spawn(move || boot(handle));
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .unwrap_or_else(|err| {
            log(&format!("fatal: {err}"));
            message_box("Helpie could not start", &format!("{err}"));
            std::process::exit(1);
        })
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                if let Some(state) = app.try_state::<Backend>() {
                    if let Some(mut child) = state.child.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
