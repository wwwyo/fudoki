import Foundation
import CoreGraphics
import ImageIO

struct RenderRequest: Decodable {
    let input_path: String
    let pages: [Int]
    let output_directory: String
    let dpi: Int
    let max_pixels: Int
}
enum RenderFailure: Error { case invalid(String) }

func render(_ request: RenderRequest) throws -> [String: Any] {
    guard (72...600).contains(request.dpi), request.max_pixels > 0,
          !request.pages.isEmpty, Set(request.pages).count == request.pages.count,
          request.pages.allSatisfy({ $0 > 0 }),
          let document = CGPDFDocument(URL(fileURLWithPath: request.input_path) as CFURL),
          !document.isEncrypted else { throw RenderFailure.invalid("Invalid request or encrypted/unreadable PDF") }
    // Validate every requested page before producing any PNG.
    for number in request.pages {
        guard let page = document.page(at: number) else { throw RenderFailure.invalid("Physical page does not exist: \(number)") }
        let box = page.getBoxRect(.cropBox)
        let scale = Double(request.dpi) / 72
        guard box.width.isFinite, box.height.isFinite, box.width > 0, box.height > 0,
              ceil(box.width * scale) * ceil(box.height * scale) <= Double(request.max_pixels) else {
            throw RenderFailure.invalid("Invalid geometry or max_pixels exceeded")
        }
    }
    var records: [[String: Any]] = []
    for number in request.pages {
        try autoreleasepool {
            let page = document.page(at: number)!
            let box = page.getBoxRect(.cropBox)
            let rotated = abs(page.rotationAngle) % 180 == 90
            let size = CGSize(width: rotated ? box.height : box.width, height: rotated ? box.width : box.height)
            let scale = Double(request.dpi) / 72
            let width = Int(ceil(size.width * scale)), height = Int(ceil(size.height * scale))
            guard let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let context = CGContext(data: nil, width: width, height: height,
                    bitsPerComponent: 8, bytesPerRow: width * 4, space: space,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
                throw RenderFailure.invalid("Cannot allocate rendered page")
            }
            context.setFillColor(CGColor(gray: 1, alpha: 1))
            context.fill(CGRect(x: 0, y: 0, width: width, height: height))
            context.scaleBy(x: Double(width) / size.width, y: Double(height) / size.height)
            context.concatenate(page.getDrawingTransform(.cropBox, rect: CGRect(origin: .zero, size: size), rotate: 0, preserveAspectRatio: true))
            context.drawPDFPage(page)
            let path = URL(fileURLWithPath: request.output_directory).appendingPathComponent("page-\(number).png")
            guard let image = context.makeImage(),
                  let destination = CGImageDestinationCreateWithURL(path as CFURL, "public.png" as CFString, 1, nil) else {
                throw RenderFailure.invalid("Cannot create PNG")
            }
            CGImageDestinationAddImage(destination, image, nil)
            guard CGImageDestinationFinalize(destination) else { throw RenderFailure.invalid("Cannot write PNG") }
            records.append(["page_number": number, "image_path": path.path, "image_width": width,
                "image_height": height, "displayed_pdf_size_pt": [size.width, size.height],
                "crop_box_pdf_pt": [box.minX, box.minY, box.maxX, box.maxY], "rotation_degrees": page.rotationAngle])
        }
    }
    return ["pages": records, "renderer": "CoreGraphics", "color_space": "sRGB", "dpi": request.dpi]
}

do {
    let request = try JSONDecoder().decode(RenderRequest.self, from: FileHandle.standardInput.readDataToEndOfFile())
    let result = try render(request)
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    let data = try JSONSerialization.data(withJSONObject: ["error": String(describing: error)])
    FileHandle.standardError.write(data)
    exit(1)
}
