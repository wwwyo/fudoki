import Foundation
import Vision
import ImageIO
import CoreGraphics

struct Config: Decodable {
    let dpi: Int
    let revision: Int
    let languages: [String]
    let language_correction: Bool
    let max_pixels: Int
    let custom_words: [String]
    let minimum_text_height: Float?
}
struct Region: Decodable {
    let id: String
    let bbox_normalized: [Double]
}
struct Input: Decodable {
    let input_path: String
    let input_kind: String
    let pages: [Int]
    let config: Config
    let regions: [Region]
}
enum OcrFailure: Error { case invalid(String) }

func rgbContext(width: Int, height: Int, maxPixels: Int) throws -> CGContext {
    guard width > 0, height > 0, Double(width) * Double(height) <= Double(maxPixels),
          let space = CGColorSpace(name: CGColorSpace.sRGB),
          let context = CGContext(data: nil, width: width, height: height,
              bitsPerComponent: 8, bytesPerRow: width * 4, space: space,
              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
        throw OcrFailure.invalid("Cannot allocate image; check dimensions and max_pixels")
    }
    context.setFillColor(CGColor(gray: 1, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    return context
}

func recognize(_ image: CGImage, pageNumber: Int, pdfSize: CGSize?, input: Input) throws -> [String: Any] {
    let width = Double(image.width), height = Double(image.height)
    var output: [[String: Any]] = []
    let numeric = try NSRegularExpression(pattern: "[0-9０-９][0-9０-９,，]*")
    for area in input.regions {
        try autoreleasepool {
            let n = area.bbox_normalized
            let x0 = floor(n[0] * width), y0 = floor(n[1] * height)
            let x1 = ceil(n[2] * width), y1 = ceil(n[3] * height)
            let crop = CGRect(x: x0, y: y0, width: x1-x0, height: y1-y0)
            guard let cut = image.cropping(to: crop) else { throw OcrFailure.invalid("Cannot crop region \(area.id)") }
            let context = try rgbContext(width: cut.width, height: cut.height, maxPixels: input.config.max_pixels)
            context.draw(cut, in: CGRect(x: 0, y: 0, width: cut.width, height: cut.height))
            guard let rgb = context.makeImage() else { throw OcrFailure.invalid("Cannot draw RGB image") }
            let request = VNRecognizeTextRequest()
            guard VNRecognizeTextRequest.supportedRevisions.contains(input.config.revision) else {
                throw OcrFailure.invalid("Unsupported Vision request revision")
            }
            request.revision = input.config.revision
            request.recognitionLevel = .accurate
            request.recognitionLanguages = input.config.languages
            request.usesLanguageCorrection = input.config.language_correction
            request.customWords = input.config.custom_words
            if let minimum = input.config.minimum_text_height {
                request.minimumTextHeight = minimum
            }
            request.automaticallyDetectsLanguage = false
            let supported = try request.supportedRecognitionLanguages()
            guard input.config.languages.allSatisfy({ supported.contains($0) }) else {
                throw OcrFailure.invalid("Unsupported recognition language")
            }
            let start = Date()
            try VNImageRequestHandler(cgImage: rgb, options: [:]).perform([request])
            let seconds = Date().timeIntervalSince(start)
            var observations: [[String: Any]] = []
            func observation(_ text: String, _ bbox: CGRect?, _ kind: String, _ id: String,
                             _ parent: String?, _ confidence: Float) -> [String: Any] {
                var value: [String: Any] = ["id": id, "parent_id": parent as Any? ?? NSNull(), "kind": kind,
                    "raw_text": text, "confidence": Double(confidence), "bbox_status": "unavailable",
                    "bbox_px": NSNull(), "bbox_normalized": NSNull(), "bbox_pdf_pt": NSNull()]
                guard let bbox = bbox, bbox.width > 0, bbox.height > 0,
                      bbox.minX.isFinite, bbox.minY.isFinite, bbox.maxX.isFinite, bbox.maxY.isFinite else { return value }
                let b = [x0 + Double(bbox.minX)*Double(cut.width),
                         y0 + (1-Double(bbox.maxY))*Double(cut.height),
                         x0 + Double(bbox.maxX)*Double(cut.width),
                         y0 + (1-Double(bbox.minY))*Double(cut.height)]
                let normalized = [b[0]/width, b[1]/height, b[2]/width, b[3]/height]
                let pt: Any = pdfSize.map { size in
                    [b[0]*size.width/width, b[1]*size.height/height,
                     b[2]*size.width/width, b[3]*size.height/height]
                } ?? (NSNull() as Any)
                value["bbox_status"] = "available"
                value["bbox_px"] = b
                value["bbox_normalized"] = normalized
                value["bbox_pdf_pt"] = pt
                return value
            }
            for (index, region) in (request.results ?? []).enumerated() {
                guard let candidate = region.topCandidates(1).first else { continue }
                let parent = "p\(pageNumber):\(area.id):r\(index)"
                observations.append(observation(candidate.string, region.boundingBox, "region", parent, nil, candidate.confidence))
                var wordIndex = 0
                candidate.string.enumerateSubstrings(in: candidate.string.startIndex..<candidate.string.endIndex, options: .byWords) { _, range, _, _ in
                    let text = String(candidate.string[range])
                    guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
                    let box = (try? candidate.boundingBox(for: range))?.boundingBox
                    observations.append(observation(text, box, "word", "\(parent):w\(wordIndex)", parent, candidate.confidence))
                    wordIndex += 1
                }
                for (numberIndex, match) in numeric.matches(in: candidate.string, range: NSRange(candidate.string.startIndex..<candidate.string.endIndex, in: candidate.string)).enumerated() {
                    if let range = Range(match.range, in: candidate.string) {
                        let box = (try? candidate.boundingBox(for: range))?.boundingBox
                        observations.append(observation(String(candidate.string[range]), box, "number", "\(parent):n\(numberIndex)", parent, candidate.confidence))
                    }
                }
            }
            output.append(["id": area.id, "crop_bbox_px": [x0,y0,x1,y1], "inference_seconds": seconds,
                           "minimum_text_height": Double(request.minimumTextHeight),
                           "request_revision": request.revision, "observations": observations])
        }
    }
    let size: Any = pdfSize.map { [$0.width, $0.height] } ?? (NSNull() as Any)
    return ["page_number": pageNumber, "image_width": image.width, "image_height": image.height,
            "displayed_pdf_size_pt": size, "regions": output]
}

func run(_ input: Input) throws -> [String: Any] {
    let url = URL(fileURLWithPath: input.input_path)
    var pages: [[String: Any]] = []
    if input.input_kind == "pdf" {
        guard let document = CGPDFDocument(url as CFURL), !document.isEncrypted else {
            throw OcrFailure.invalid("Cannot open PDF, or PDF is encrypted")
        }
        for number in input.pages {
            try autoreleasepool {
                guard let page = document.page(at: number) else { throw OcrFailure.invalid("Physical page \(number) does not exist") }
                let box = page.getBoxRect(.cropBox)
                let rotated = abs(page.rotationAngle) % 180 == 90
                let size = CGSize(width: rotated ? box.height : box.width, height: rotated ? box.width : box.height)
                let scale = Double(input.config.dpi)/72
                guard size.width.isFinite, size.height.isFinite, size.width > 0, size.height > 0,
                      ceil(size.width*scale)*ceil(size.height*scale) <= Double(input.config.max_pixels) else {
                    throw OcrFailure.invalid("PDF page exceeds max_pixels or has invalid dimensions")
                }
                let context = try rgbContext(width: Int(ceil(size.width*scale)), height: Int(ceil(size.height*scale)), maxPixels: input.config.max_pixels)
                // Explicit bitmap scaling also works when the PDF drawing
                // transform does not enlarge a page to a larger destination.
                context.scaleBy(x: Double(context.width)/size.width, y: Double(context.height)/size.height)
                context.concatenate(page.getDrawingTransform(.cropBox, rect: CGRect(origin: .zero, size: size), rotate: 0, preserveAspectRatio: true))
                context.drawPDFPage(page)
                guard let image = context.makeImage() else { throw OcrFailure.invalid("Cannot render PDF") }
                pages.append(try recognize(image, pageNumber: number, pdfSize: size, input: input))
            }
        }
    } else {
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            throw OcrFailure.invalid("Cannot open image")
        }
        let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
        let orientation = properties?[kCGImagePropertyOrientation] as? Int ?? 1
        guard orientation == 1 else { throw OcrFailure.invalid("Image must be upright; normalize EXIF orientation first") }
        guard Double(image.width)*Double(image.height) <= Double(input.config.max_pixels) else {
            throw OcrFailure.invalid("Image exceeds max_pixels")
        }
        pages.append(try recognize(image, pageNumber: 1, pdfSize: nil, input: input))
    }
    return ["schema_version": 1, "engine": ["name": "Apple Vision", "api": "VNRecognizeTextRequest",
        "macos": ProcessInfo.processInfo.operatingSystemVersionString,
        "requested_revision": input.config.revision, "recognition_level": "accurate",
        "languages": input.config.languages, "language_correction": input.config.language_correction,
        "custom_words": input.config.custom_words,
        "requested_minimum_text_height": input.config.minimum_text_height.map { Double($0) } as Any? ?? NSNull(),
        "automatically_detects_language": false, "dpi": input.config.dpi,
        "max_pixels": input.config.max_pixels, "color_space": "8-bit sRGB RGBA",
        "bbox_precision": "word precision; not exact character or cell boundaries",
        "confidence_scope": "parent recognition candidate; reused for its substrings"], "pages": pages]
}

do {
    let input = try JSONDecoder().decode(Input.self, from: FileHandle.standardInput.readDataToEndOfFile())
    let data = try JSONSerialization.data(withJSONObject: run(input), options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    let data = try JSONSerialization.data(withJSONObject: ["error": ["code": "vision_ocr_failed", "message": String(describing: error)]])
    FileHandle.standardError.write(data)
    FileHandle.standardError.write(Data("\n".utf8))
    exit(1)
}
