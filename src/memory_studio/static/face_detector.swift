import Foundation
import Vision

while let path = readLine() {
    let request = VNDetectFaceRectanglesRequest()
    request.usesCPUOnly = true
    do {
        try VNImageRequestHandler(url: URL(fileURLWithPath: path)).perform([request])
        let width = (request.results ?? []).map { $0.boundingBox.width }.max() ?? 0
        print(String(format: "%.4f", width))
    } catch {
        print("0")
    }
}
