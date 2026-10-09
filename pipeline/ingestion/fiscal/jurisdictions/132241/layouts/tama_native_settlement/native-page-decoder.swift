import Foundation
import CoreGraphics
import ImageIO
import Vision
let root=URL(fileURLWithPath:CommandLine.arguments[2],isDirectory:true)
let spec=try JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))) as! [String:Any]
let input=URL(fileURLWithPath:spec["object_path"] as! String)
let document=CGPDFDocument(input as CFURL)!
let part=spec["part"] as! Int, first=spec["first_printed_page"] as! Int
let sha=spec["sha256"] as! String
try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
let left:[(String,Double,Double)] = [("kan",0.044,0.145),("kou",0.145,0.245),("moku",0.245,0.344),("initial_budget",0.344,0.452),("supplementary_delta",0.452,0.56),("carried_budget",0.56,0.665),("reserve_and_transfer_delta",0.665,0.771),("current_budget",0.771,0.882)]
let right:[(String,Double,Double)] = [("setsu",0.09,0.215),("budget_current",0.215,0.322),("executed",0.322,0.432),("carryover",0.432,0.55),("unused",0.55,0.65),("remarks",0.65,0.93)]
func observe(_ image:CGImage,_ column:String,_ lo:Double,_ hi:Double) throws -> [[String:Any]] {
 let crop=CGRect(x:lo*Double(image.width),y:0,width:(hi-lo)*Double(image.width),height:Double(image.height))
 let cropped=image.cropping(to:crop)!
 let request=VNRecognizeTextRequest();request.recognitionLevel = .accurate
 request.recognitionLanguages=["ja-JP","en-US"];request.usesLanguageCorrection=false
 request.minimumTextHeight=0.002
 try VNImageRequestHandler(cgImage:cropped).perform([request])
 return (request.results ?? []).enumerated().compactMap { index,obs in
  guard let candidate=obs.topCandidates(3).first else{return nil}
  let bb=obs.boundingBox
  return ["column":column,"observation_index":index+1,"text":candidate.string,"confidence":candidate.confidence,
   "alternatives":obs.topCandidates(3).map{["text":$0.string,"confidence":$0.confidence]},
   "bbox_normalized_top_left":[lo+bb.minX*(hi-lo),1-bb.maxY,lo+bb.maxX*(hi-lo),1-bb.minY]]
 }
}
for number in 1...document.numberOfPages {
 try autoreleasepool {
  let printed=first+number-1, prefix=String(format:"part%02d-physical%03d-printed%03d",part,number,printed)
  let jsonURL=root.appendingPathComponent(prefix+".json")
  if FileManager.default.fileExists(atPath:jsonURL.path){return}
  let page=document.page(at:number)!, rect=page.getBoxRect(.mediaBox), scale=2.75
  let width=Int(ceil(rect.width*scale)),height=Int(ceil(rect.height*scale))
  let ctx=CGContext(data:nil,width:width,height:height,bitsPerComponent:8,bytesPerRow:width*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
  ctx.setFillColor(CGColor(gray:1,alpha:1));ctx.fill(CGRect(x:0,y:0,width:width,height:height));ctx.scaleBy(x:scale,y:scale);ctx.drawPDFPage(page)
  let image=ctx.makeImage()!,png=root.appendingPathComponent(prefix+".png")
  let dest=CGImageDestinationCreateWithURL(png as CFURL,"public.png" as CFString,1,nil)!
  CGImageDestinationAddImage(dest,image,nil);guard CGImageDestinationFinalize(dest) else {fatalError("PNG write")}
  var observations=try observe(image,"full",0,1)
  let expenditure=(48...119).contains(printed)||(140...149).contains(printed)||(170...179).contains(printed)||(196...199).contains(printed)
  if expenditure {
   for (column,lo,hi) in (printed%2==0 ? left : right) {observations += try observe(image,column,lo,hi)}
  }
  let object:[String:Any]=["engine":"macOS Vision VNRecognizeTextRequest accurate", "os_version":ProcessInfo.processInfo.operatingSystemVersionString,
   "recognition_languages":["ja-JP","en-US"],"uses_language_correction":false,"part":part,"physical_page":number,
   "expected_printed_page":printed,"origin_sha256":sha,"origin_url":spec["url"]!,"render_scale":scale,
   "page_width":rect.width,"page_height":rect.height,"pixel_width":width,"pixel_height":height,
   "rendered_image":png.path,"expenditure_column_pass":expenditure,"observations":observations]
  try JSONSerialization.data(withJSONObject:object,options:[.prettyPrinted,.sortedKeys]).write(to:jsonURL,options:.atomic)
  print("part\(part) physical\(number) printed\(printed) observations\(observations.count)")
  fflush(stdout)
 }
}
