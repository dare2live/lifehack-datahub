import AppKit
import Foundation
import Vision

struct Observation: Encodable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct ImageResult: Encodable {
    let image_path: String
    let observations: [Observation]
}

func fail(_ message: String) -> Never {
    fputs(message + "\n", stderr)
    exit(2)
}

var args = Array(CommandLine.arguments.dropFirst())
var languages = [String]()
var recognitionLevel = "accurate"
var usesLanguageCorrection = false
var imagePaths = [String]()

while !args.isEmpty {
    let item = args.removeFirst()
    switch item {
    case "--languages":
        if args.isEmpty {
            fail("--languages needs a comma-separated value")
        }
        languages = args.removeFirst().split(separator: ",").map { String($0) }
    case "--recognition-level":
        if args.isEmpty {
            fail("--recognition-level needs accurate or fast")
        }
        recognitionLevel = args.removeFirst()
    case "--uses-language-correction":
        if args.isEmpty {
            fail("--uses-language-correction needs true or false")
        }
        usesLanguageCorrection = args.removeFirst().lowercased() == "true"
    default:
        imagePaths.append(item)
    }
}

if languages.isEmpty {
    fail("--languages is required")
}
if imagePaths.isEmpty {
    fail("at least one image path is required")
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys]

for imagePath in imagePaths {
    guard let image = NSImage(contentsOfFile: imagePath),
          let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        fputs("failed to load image: \(imagePath)\n", stderr)
        continue
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = recognitionLevel == "fast" ? .fast : .accurate
    request.usesLanguageCorrection = usesLanguageCorrection
    request.recognitionLanguages = languages

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
    } catch {
        fputs("ocr failed: \(imagePath): \(error)\n", stderr)
        continue
    }

    let observations = (request.results ?? []).compactMap { observation -> Observation? in
        guard let candidate = observation.topCandidates(1).first else {
            return nil
        }
        return Observation(
            text: candidate.string,
            confidence: candidate.confidence,
            x: observation.boundingBox.origin.x,
            y: observation.boundingBox.origin.y,
            width: observation.boundingBox.width,
            height: observation.boundingBox.height
        )
    }.sorted { left, right in
        if abs(left.y - right.y) > 0.01 {
            return left.y > right.y
        }
        return left.x < right.x
    }

    let result = ImageResult(image_path: imagePath, observations: observations)
    if let data = try? encoder.encode(result), let line = String(data: data, encoding: .utf8) {
        print(line)
    }
}
