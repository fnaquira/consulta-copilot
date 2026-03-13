// screencapture_audio.swift
// Captura audio del sistema via ScreenCaptureKit (macOS 13+).
// Emite PCM float32 mono 48 kHz por stdout.
//
// Compilar:
//   swiftc -O -o screencapture_audio screencapture_audio.swift \
//     -framework ScreenCaptureKit -framework CoreMedia -framework Foundation
//
// Señales:
//   stderr  → "READY\n" cuando la captura inicia, "ERROR: …\n" si falla.
//   stdout  → raw float32 mono 48 kHz PCM (little-endian).
//   SIGTERM / SIGINT → detiene captura y sale limpio.

import ScreenCaptureKit
import CoreMedia
import Foundation
import Darwin

// MARK: - Escritura directa a stdout (sin buffering)

private func writeStdout(_ data: Data) {
    data.withUnsafeBytes { raw in
        guard let base = raw.baseAddress else { return }
        var offset = 0
        var remaining = raw.count
        while remaining > 0 {
            let n = Darwin.write(STDOUT_FILENO, base + offset, remaining)
            if n <= 0 { break }
            offset += n
            remaining -= n
        }
    }
}

private func writeStderr(_ msg: String) {
    FileHandle.standardError.write(Data(msg.utf8))
}

// MARK: - Capturer

class AudioCapturer: NSObject, SCStreamDelegate, SCStreamOutput {
    private var stream: SCStream?

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: false
        )
        guard let display = content.displays.first else {
            writeStderr("ERROR: No se encontró display\n")
            Foundation.exit(1)
        }

        let filter = SCContentFilter(
            display: display,
            excludingApplications: [],
            exceptingWindows: []
        )

        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.sampleRate = 48_000
        config.channelCount = 1
        config.excludesCurrentProcessAudio = true
        // Video mínimo (no se puede desactivar por completo)
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)

        let s = SCStream(filter: filter, configuration: config, delegate: self)
        try s.addStreamOutput(
            self,
            type: .audio,
            sampleHandlerQueue: DispatchQueue(label: "audio", qos: .userInteractive)
        )
        try await s.startCapture()
        self.stream = s

        writeStderr("READY\n")
    }

    // --- SCStreamOutput: audio callback ---
    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .audio else { return }
        guard let buf = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }

        var length = 0
        var ptr: UnsafeMutablePointer<Int8>?
        let st = CMBlockBufferGetDataPointer(
            buf, atOffset: 0,
            lengthAtOffsetOut: nil, totalLengthOut: &length,
            dataPointerOut: &ptr
        )
        guard st == kCMBlockBufferNoErr, let p = ptr, length > 0 else { return }

        writeStdout(Data(bytes: p, count: length))
    }

    // --- SCStreamDelegate: error ---
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        writeStderr("ERROR: Stream detenido: \(error.localizedDescription)\n")
        Foundation.exit(1)
    }

    func stop() async {
        try? await stream?.stopCapture()
    }
}

// MARK: - Main

let capturer = AudioCapturer()

// Manejar señales de terminación
for sig: Int32 in [SIGTERM, SIGINT] {
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    Darwin.signal(sig, SIG_IGN)
    src.setEventHandler {
        Task {
            await capturer.stop()
            Foundation.exit(0)
        }
    }
    src.resume()
}

Task {
    do {
        try await capturer.start()
    } catch {
        writeStderr("ERROR: \(error.localizedDescription)\n")
        Foundation.exit(1)
    }
}

RunLoop.main.run()
