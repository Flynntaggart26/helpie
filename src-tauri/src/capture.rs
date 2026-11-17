//! One-shot Windows Graphics Capture support for the desktop shell.
//!
//! The system picker is opened only in response to an authenticated request
//! from the Python backend. The selected item is captured once and encoded in
//! memory; no frame is written to disk or logged.

use std::error::Error;
use std::sync::mpsc::{self, SyncSender};

use windows_capture::capture::{Context, GraphicsCaptureApiHandler};
use windows_capture::frame::Frame;
use windows_capture::graphics_capture_api::InternalCaptureControl;
use windows_capture::graphics_capture_picker::GraphicsCapturePicker;
use windows_capture::settings::{
    ColorFormat, CursorCaptureSettings, DirtyRegionSettings, DrawBorderSettings,
    MinimumUpdateIntervalSettings, SecondaryWindowSettings, Settings,
};

const MAX_PIXELS: u64 = 16 * 1024 * 1024;

type CaptureError = Box<dyn Error + Send + Sync>;

struct OneFrameCapture {
    sender: SyncSender<Result<Vec<u8>, String>>,
}

impl GraphicsCaptureApiHandler for OneFrameCapture {
    type Flags = SyncSender<Result<Vec<u8>, String>>;
    type Error = CaptureError;

    fn new(context: Context<Self::Flags>) -> Result<Self, Self::Error> {
        Ok(Self {
            sender: context.flags,
        })
    }

    fn on_frame_arrived(
        &mut self,
        frame: &mut Frame<'_>,
        control: InternalCaptureControl,
    ) -> Result<(), Self::Error> {
        let width = frame.width();
        let height = frame.height();
        if width == 0 || height == 0 || u64::from(width) * u64::from(height) > MAX_PIXELS {
            let _ = self
                .sender
                .send(Err("capture dimensions exceed the limit".into()));
            control.stop();
            return Ok(());
        }

        let frame_buffer = frame.buffer()?;
        let mut aligned = Vec::new();
        let pixels = frame_buffer.as_nopadding_buffer(&mut aligned).to_vec();
        let mut encoded = Vec::new();
        {
            let mut encoder = png::Encoder::new(&mut encoded, width, height);
            encoder.set_color(png::ColorType::Rgba);
            encoder.set_depth(png::BitDepth::Eight);
            encoder.write_header()?.write_image_data(&pixels)?;
        }

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
    if width <= 0 || height <= 0 || u64::from(width as u32) * u64::from(height as u32) > MAX_PIXELS
    {
        return Err("selected capture target exceeds the size limit".into());
    }

    let (sender, receiver) = mpsc::sync_channel(1);
    let settings = Settings::new(
        picked,
        CursorCaptureSettings::Default,
        DrawBorderSettings::Default,
        SecondaryWindowSettings::Default,
        MinimumUpdateIntervalSettings::Default,
        DirtyRegionSettings::Default,
        ColorFormat::Rgba8,
        sender,
    );
    OneFrameCapture::start(settings)?;
    match receiver.recv() {
        Ok(Ok(image)) => Ok(Some((image, target_name))),
        Ok(Err(message)) => Err(message.into()),
        Err(_) => Ok(None),
    }
}
