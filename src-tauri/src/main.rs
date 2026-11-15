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

use tauri::{AppHandle, Manager, PhysicalPosition, Url, WebviewUrl, WebviewWindowBuilder};

/// Set by `--hidden` (autostart): start the backend without popping the window.
static START_HIDDEN: AtomicBool = AtomicBool::new(false);
/// Set once the user explicitly asked for the window (Ctrl+H), so the late
/// "stay hidden" enforcement stops fighting them.
static USER_SHOWED: AtomicBool = AtomicBool::new(false);

const MAIN_W: f64 = 1180.0;
const MAIN_H: f64 = 780.0;
const TINY_W: f64 = 380.0;
const TINY_H: f64 = 220.0;

struct Backend {
    child: Mutex<Option<Child>>,
    port: Mutex<u16>,
}

// --------------------------------------------------------------------------- //
//  Paths and probing
// --------------------------------------------------------------------------- //
fn data_dir() -> PathBuf {
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
    let request = b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(request).is_err() {
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
        exe_dir.join("sidecar").join("helpie-core").join("helpie-core.exe"),
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

fn spawn_backend(port: u16, control_port: u16) -> Option<Child> {
    let exe = sidecar_path()?;
    let mut command = Command::new(&exe);
    command
        .env("HELPIE_PORT", port.to_string())
        .env("HELPIE_CONTROL_PORT", control_port.to_string())
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

#[cfg(windows)]
fn cursor_pos() -> (i32, i32) {
    #[repr(C)]
    struct Point {
        x: i32,
        y: i32,
    }

    extern "system" {
        fn GetCursorPos(point: *mut Point) -> i32;
    }

    let mut point = Point { x: 0, y: 0 };
    unsafe {
        GetCursorPos(&mut point);
    }
    (point.x, point.y)
}

#[cfg(not(windows))]
fn cursor_pos() -> (i32, i32) {
    (200, 200)
}

fn show_tiny(app: &AppHandle, port: u16) {
    let base = base_url(port);
    let url = format!("{base}/?view=tiny");

    if let Some(window) = app.get_webview_window("tiny") {
        let _ = window.eval(&format!("location.replace('{url}');"));
        let (x, y) = cursor_pos();
        let _ = window.set_position(PhysicalPosition::new(x + 24, y + 24));
        let _ = window.show();
        let _ = window.set_focus();
        return;
    }

    let parsed = match Url::parse(&url) {
        Ok(parsed) => parsed,
        Err(_) => return,
    };
    let (x, y) = cursor_pos();
    let built = WebviewWindowBuilder::new(app, "tiny", WebviewUrl::External(parsed))
        .title("Helpie")
        .inner_size(TINY_W, TINY_H)
        .position(x as f64 + 24.0, y as f64 + 24.0)
        .resizable(false)
        .maximizable(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(true)
        .visible(false)
        .build();

    match built {
        Ok(window) => {
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
//  Control endpoint used by the Python backend
// --------------------------------------------------------------------------- //
fn start_control(app: AppHandle, backend_port: u16) -> std::io::Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();

    std::thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            handle_control(&app, backend_port, stream);
        }
    });

    Ok(port)
}

fn handle_control(app: &AppHandle, port: u16, mut stream: TcpStream) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let mut buf = [0u8; 512];
    let read = stream.read(&mut buf).unwrap_or(0);
    let request = String::from_utf8_lossy(&buf[..read]).to_string();
    let action = request
        .split_whitespace()
        .nth(1)
        .unwrap_or("/")
        .trim_start_matches('/')
        .split('?')
        .next()
        .unwrap_or("")
        .to_string();

    match action.as_str() {
        "full" | "focus" => show_main(app, port, true),
        "tiny" => show_tiny(app, port),
        "hide-tiny" => hide_tiny(app),
        "quit" => app.exit(0),
        _ => {}
    }

    let _ = stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok");
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
        log(&format!("boot: probing existing backend on port {existing}"));
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
    let control = start_control(app.clone(), port).unwrap_or(0);
    log(&format!("boot: backend port {port}, control port {control}"));

    let _ = std::fs::create_dir_all(data_dir());
    if control > 0 {
        let _ = std::fs::write(data_dir().join("control_port.txt"), control.to_string());
    }

    let child = spawn_backend(port, control);
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

            let window = match WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::App("index.html".into()),
            )
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

            std::thread::spawn(move || boot(handle));
            Ok(())
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
