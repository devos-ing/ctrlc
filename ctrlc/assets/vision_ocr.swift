import Foundation
import ImageIO
import Vision

struct WordRegion: Codable {
    let text: String
    let box: [Int]
}

struct TextRegion: Codable {
    let text: String
    let confidence: Float
    let box: [Int]
    let words: [WordRegion]
}

struct OCRResult: Codable {
    let width: Int
    let height: Int
    let texts: [TextRegion]
}

enum OCRError: Error {
    case usage
    case unreadableImage
}

func pixels(_ bounds: CGRect, width: Int, height: Int) -> [Int] {
    let x = max(0, min(width, Int((bounds.minX * Double(width)).rounded())))
    let y = max(0, min(height, Int(((1 - bounds.maxY) * Double(height)).rounded())))
    let w = max(0, min(width - x, Int((bounds.width * Double(width)).rounded())))
    let h = max(0, min(height - y, Int((bounds.height * Double(height)).rounded())))
    return [x, y, w, h]
}

func recognize() throws -> OCRResult {
    guard CommandLine.arguments.count >= 2 else { throw OCRError.usage }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw OCRError.unreadableImage
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    request.recognitionLanguages = CommandLine.arguments.count > 2
        ? CommandLine.arguments[2].split(separator: ",").map(String.init)
        : ["en-US"]
    try VNImageRequestHandler(cgImage: image, orientation: .up).perform([request])
    let width = image.width
    let height = image.height
    let texts = (request.results ?? []).compactMap { observation -> TextRegion? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let words = candidate.string.split(whereSeparator: { $0.isWhitespace }).compactMap {
            word -> WordRegion? in
            guard let bounds = try? candidate.boundingBox(for: word.startIndex..<word.endIndex)
            else { return nil }
            return WordRegion(text: String(word), box: pixels(bounds.boundingBox,
                              width: width, height: height))
        }
        return TextRegion(text: candidate.string, confidence: candidate.confidence,
                          box: pixels(observation.boundingBox, width: width, height: height),
                          words: words)
    }.sorted { ($0.box[1], $0.box[0]) < ($1.box[1], $1.box[0]) }
    return OCRResult(width: width, height: height, texts: texts)
}

do {
    let data = try JSONEncoder().encode(recognize())
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
} catch {
    let message = "OCR failed: \(error). Usage: vision_ocr IMAGE [en-US,zh-Hans]\n"
    FileHandle.standardError.write(Data(message.utf8))
    exit(1)
}
