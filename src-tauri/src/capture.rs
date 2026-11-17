//! One-shot Windows Graphics Capture support for the desktop shell.
//!
//! The system picker is opened only in response to an authenticated request
//! from the Python backend. The selected item is captured once and encoded in
//! memory; no frame is written to disk or logged.

use std::error::Error;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, SyncSender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use windows_capture::capture::{CaptureControl, Context, GraphicsCaptureApiHandler};
use windows_capture::frame::Frame;
use windows_capture::graphics_capture_api::InternalCaptureControl;
use windows_capture::graphics_capture_picker::GraphicsCapturePicker;
use windows_capture::monitor::Monitor;
use windows_capture::settings::{
    ColorFormat, CursorCaptureSettings, DirtyRegionSettings, DrawBorderSettings,
    MinimumUpdateIntervalSettings, SecondaryWindowSettings, Settings,
};

const MAX_PIXELS: u64 = 16 * 1024 * 1024;

type CaptureError = Box<dyn Error + Send + Sync>;
const LIVE_FRAME_MAX_WIDTH: u32 = 1600;
const LIVE_FRAME_MAX_PIXELS: u64 = 8 * 1024 * 1024;
const LIVE_FRAME_INTERVAL: Duration = Duration::from_secs(1);
const LIVE_FRAME_TTL: Duration = Duration::from_secs(3);

#[derive(Clone)]
pub struct LatestFrame {
    pub png: Vec<u8>,
    pub captured_at_ms: u128,
    pub target: String,
    captured_at: Instant,
}

type SharedLatestFrame = Arc<Mutex<Option<LatestFrame>>>;

struct LiveCaptureFlags {
    latest: SharedLatestFrame,
    target: String,
}

/// Owns one opt-in, primary-monitor capture session and only its newest frame.
/// The encoded frame is memory-only and becomes unavailable after three seconds.
pub struct LiveCaptureSession {
    control: Mutex<Option<CaptureControl<LiveFrameCapture, CaptureError>>>,
    latest: SharedLatestFrame,
    target: Mutex<Option<String>>,
    running: Arc<AtomicBool>,
    fresh_frame: Mutex<()>,
}

impl Default for LiveCaptureSession {
    fn default() -> Self {
        Self {
            control: Mutex::new(None),
            latest: Arc::new(Mutex::new(None)),
            target: Mutex::new(None),
            running: Arc::new(AtomicBool::new(false)),
            fresh_frame: Mutex::new(()),
        }
    }
}

impl LiveCaptureSession {
    pub fn start(&self) -> Result<(), String> {
        let mut control = self
            .control
            .lock()
            .map_err(|_| "capture state unavailable")?;
        if control
            .as_ref()
            .is_some_and(|session| !session.is_finished())
        {
            return Ok(());
        }
        if let Some(finished) = control.take() {
            let _ = finished.wait();
        }
        *self
            .latest
            .lock()
            .map_err(|_| "capture state unavailable")? = None;

        let monitor = Monitor::primary().map_err(|_| "primary display unavailable")?;
        let target = monitor.name().unwrap_or_else(|_| "Primary display".into());
        let target_label = target.clone();
        let settings = Settings::new(
            monitor,
            CursorCaptureSettings::WithoutCursor,
            DrawBorderSettings::WithBorder,
            SecondaryWindowSettings::Exclude,
            MinimumUpdateIntervalSettings::Custom(LIVE_FRAME_INTERVAL),
            DirtyRegionSettings::ReportAndRender,
            ColorFormat::Rgba8,
            LiveCaptureFlags {
                latest: self.latest.clone(),
                target,
            },
        );
        let session = LiveFrameCapture::start_free_threaded(settings)
            .map_err(|_| "Windows screen capture could not start")?;
        let mut stored_target = self
            .target
            .lock()
            .map_err(|_| "capture state unavailable")?;
        *stored_target = Some(target_label);
        *control = Some(session);
        self.running.store(true, Ordering::Release);
        Ok(())
    }

    pub fn status(&self) -> (bool, bool, Option<u128>, String) {
        let active = self.running.load(Ordering::Acquire)
            && self
                .control
                .lock()
                .map(|control| {
                    control
                        .as_ref()
                        .is_some_and(|session| !session.is_finished())
                })
                .unwrap_or(false);
        let mut latest = self
            .latest
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        let fresh = active
            && latest
                .as_ref()
                .is_some_and(|frame| frame.captured_at.elapsed() <= LIVE_FRAME_TTL);
        if !fresh {
            *latest = None;
        }
        let frame_time = latest.as_ref().map(|frame| frame.captured_at_ms);
        let target = self
            .target
            .lock()
            .ok()
            .and_then(|target| target.clone())
            .unwrap_or_default();
        (active, fresh, frame_time, target)
    }

    pub fn latest(&self) -> Option<LatestFrame> {
        let active = self.running.load(Ordering::Acquire)
            && self
                .control
                .lock()
                .ok()?
                .as_ref()
                .is_some_and(|session| !session.is_finished());
        if !active {
            if let Ok(mut latest) = self.latest.lock() {
                *latest = None;
            }
            return None;
        }
        let mut latest = self.latest.lock().ok()?;
        let fresh = latest
            .as_ref()
            .is_some_and(|frame| frame.captured_at.elapsed() <= LIVE_FRAME_TTL);
        if !fresh {
            *latest = None;
            return None;
        }
        latest.clone()
    }

    /// Return the buffered frame if it is recent, otherwise take a fresh
    /// primary-monitor frame. This method is called only for an explicit
    /// screen question from the companion.
    pub fn latest_or_fresh(&self) -> Option<LatestFrame> {
        let _fresh_frame = self.fresh_frame.lock().ok()?;
        let active = self.running.load(Ordering::Acquire)
            && self
                .control
                .lock()
                .ok()?
                .as_ref()
                .is_some_and(|session| !session.is_finished());
        if !active {
            return None;
        }
        if let Some(frame) = self.latest() {
            return Some(frame);
        }
        let monitor = Monitor::primary().ok()?;
        let width = monitor.width().ok()?;
        let height = monitor.height().ok()?;
        let target = monitor.name().unwrap_or_else(|_| "Primary display".into());
        let (png, target) = capture_item(
            monitor,
            target,
            width as i32,
            height as i32,
            Some(self.running.clone()),
        )
        .ok()??;
        if !self.running.load(Ordering::Acquire) {
            return None;
        }
        Some(LatestFrame {
            png,
            captured_at_ms: now_ms(),
            target,
            captured_at: Instant::now(),
        })
    }

    pub fn stop(&self) {
        self.running.store(false, Ordering::Release);
        if let Ok(mut latest) = self.latest.lock() {
            *latest = None;
        }
        if let Ok(mut target) = self.target.lock() {
            *target = None;
        }
        let session = self
            .control
            .lock()
            .ok()
            .and_then(|mut control| control.take());
        if let Some(session) = session {
            let _ = session.stop();
        }
        if let Ok(mut latest) = self.latest.lock() {
            *latest = None;
        }
    }
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

struct LiveFrameCapture {
    latest: SharedLatestFrame,
    target: String,
    last_frame: Instant,
}

impl GraphicsCaptureApiHandler for LiveFrameCapture {
    type Flags = LiveCaptureFlags;
    type Error = CaptureError;

    fn new(context: Context<Self::Flags>) -> Result<Self, Self::Error> {
        Ok(Self {
            latest: context.flags.latest,
            target: context.flags.target,
            last_frame: Instant::now() - LIVE_FRAME_INTERVAL,
        })
    }

    fn on_frame_arrived(
        &mut self,
        frame: &mut Frame<'_>,
        _control: InternalCaptureControl,
    ) -> Result<(), Self::Error> {
        if self.last_frame.elapsed() < LIVE_FRAME_INTERVAL {
            return Ok(());
        }
        self.last_frame = Instant::now();
        let width = frame.width();
        let height = frame.height();
        let pixel_count = u64::from(width) * u64::from(height);
        if width == 0 || height == 0 || pixel_count > MAX_PIXELS {
            return Ok(());
        }
        let encoded = encode_downscaled_png(frame)?;
        let latest = LatestFrame {
            png: encoded,
            captured_at_ms: now_ms(),
            target: self.target.clone(),
            captured_at: Instant::now(),
        };
        if let Ok(mut current) = self.latest.lock() {
            *current = Some(latest);
        }
        Ok(())
    }
}

fn scaled_dimensions(width: u32, height: u32) -> (u32, u32) {
    let pixels = u64::from(width) * u64::from(height);
    let scale_width = f64::from(LIVE_FRAME_MAX_WIDTH) / f64::from(width);
    let scale_pixels = (LIVE_FRAME_MAX_PIXELS as f64 / pixels as f64).sqrt();
    let scale = 1.0_f64.min(scale_width).min(scale_pixels);
    (
        (f64::from(width) * scale).round().max(1.0) as u32,
        (f64::from(height) * scale).round().max(1.0) as u32,
    )
}

fn encode_downscaled_png(frame: &mut Frame<'_>) -> Result<Vec<u8>, CaptureError> {
    let width = frame.width();
    let height = frame.height();
    if width == 0 || height == 0 || u64::from(width) * u64::from(height) > MAX_PIXELS {
        return Err("capture dimensions exceed the limit".into());
    }
    let buffer = frame.buffer()?;
    let mut aligned = Vec::new();
    let pixels = buffer.as_nopadding_buffer(&mut aligned);
    let (out_width, out_height) = scaled_dimensions(width, height);
    let mut scaled = Vec::with_capacity(out_width as usize * out_height as usize * 4);
    for y in 0..out_height {
        let src_y = (u64::from(y) * u64::from(height) / u64::from(out_height)) as usize;
        for x in 0..out_width {
            let src_x = (u64::from(x) * u64::from(width) / u64::from(out_width)) as usize;
            let offset = (src_y * width as usize + src_x) * 4;
            scaled.extend_from_slice(&pixels[offset..offset + 4]);
        }
    }

    let mut encoded = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut encoded, out_width, out_height);
        encoder.set_color(png::ColorType::Rgba);
        encoder.set_depth(png::BitDepth::Eight);
        encoder.write_header()?.write_image_data(&scaled)?;
    }
    Ok(encoded)
}

struct OneFrameCapture {
    sender: SyncSender<Result<Vec<u8>, String>>,
    cancelled: Option<Arc<AtomicBool>>,
}

struct OneFrameCaptureFlags {
    sender: SyncSender<Result<Vec<u8>, String>>,
    cancelled: Option<Arc<AtomicBool>>,
}

impl GraphicsCaptureApiHandler for OneFrameCapture {
    type Flags = OneFrameCaptureFlags;
    type Error = CaptureError;

    fn new(context: Context<Self::Flags>) -> Result<Self, Self::Error> {
        Ok(Self {
            sender: context.flags.sender,
            cancelled: context.flags.cancelled,
        })
    }

    fn on_frame_arrived(
        &mut self,
        frame: &mut Frame<'_>,
        control: InternalCaptureControl,
    ) -> Result<(), Self::Error> {
        if self
            .cancelled
            .as_ref()
            .is_some_and(|cancelled| !cancelled.load(Ordering::Acquire))
        {
            control.stop();
            return Ok(());
        }
        let width = frame.width();
        let height = frame.height();
        if width == 0 || height == 0 || u64::from(width) * u64::from(height) > MAX_PIXELS {
            let _ = self
                .sender
                .send(Err("capture dimensions exceed the limit".into()));
            control.stop();
            return Ok(());
        }

        let encoded = encode_downscaled_png(frame)?;

        let _ = self.sender.send(Ok(encoded));
        control.stop();
        Ok(())
    }
}

/// Ask the Windows system picker for one display/window and return one PNG.
/// `Ok(None)` means the user cancelled or closed the picker.
pub fn capture_one_frame() -> Result<Option<(Vec<u8>, String)>, CaptureError> {
    let Some(picked) = GraphicsCapturePicker::pick_item()? else {
        return Ok(None);
    };
    let target_name = picked.item.DisplayName()?.to_string();
    let (width, height) = picked.size()?;
    capture_item(picked, target_name, width, height, None)
}

fn capture_item<T>(
    item: T,
    target_name: String,
    width: i32,
    height: i32,
    cancelled: Option<Arc<AtomicBool>>,
) -> Result<Option<(Vec<u8>, String)>, CaptureError>
where
    T: TryInto<windows_capture::settings::GraphicsCaptureItemType>,
{
    if width <= 0 || height <= 0 || u64::from(width as u32) * u64::from(height as u32) > MAX_PIXELS
    {
        return Err("selected capture target exceeds the size limit".into());
    }

    let (sender, receiver) = mpsc::sync_channel(1);
    let settings = Settings::new(
        item,
        CursorCaptureSettings::Default,
        DrawBorderSettings::Default,
        SecondaryWindowSettings::Default,
        MinimumUpdateIntervalSettings::Default,
        DirtyRegionSettings::Default,
        ColorFormat::Rgba8,
        OneFrameCaptureFlags { sender, cancelled },
    );
    OneFrameCapture::start(settings)?;
    match receiver.recv() {
        Ok(Ok(image)) => Ok(Some((image, target_name))),
        Ok(Err(message)) => Err(message.into()),
        Err(_) => Ok(None),
    }
}
