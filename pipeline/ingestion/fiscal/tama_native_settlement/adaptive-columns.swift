import Foundation
import CoreGraphics
import ImageIO
import Vision
let spec=try JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))) as! [String:Any]
let jsonURL=URL(fileURLWithPath:CommandLine.arguments[2])
let source=CGImageSourceCreateWithURL(URL(fileURLWithPath:spec["rendered_image"] as! String) as CFURL,nil)!
let image=CGImageSourceCreateImageAtIndex(source,0,nil)!
let printed=spec["expected_printed_page"] as! Int
let ws=spec["observations"] as! [[String:Any]]
let isLeft=printed%2==0
let anchor=isLeft ? "款" : "支出済額"
var header=ws.filter{ w in
 let b=w["bbox_normalized_top_left"] as! [Double]
 return w["column"] as! String == "full" && w["text"] as! String == anchor && (b[1]+b[3])/2>0.13 && (b[1]+b[3])/2<0.21
}
var reference = isLeft ? 0.095 : 0.375
if header.count != 1 {
 let fixes=try JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[3]))) as! [[String:Any]]
 if let fix=fixes.first(where:{$0["printed_page"] as! Int == printed}) {header=[fix["raw_observation"] as! [String:Any]];reference=fix["reference_center"] as! Double}
}
guard header.count==1 else {fatalError("Missing unique native header \(anchor) page\(printed)")}
let bb=header[0]["bbox_normalized_top_left"] as! [Double]
let shift=(bb[0]+bb[2])/2-reference
let left:[(String,Double,Double)] = [("kan",0.044,0.145),("kou",0.145,0.245),("moku",0.245,0.344),("initial_budget",0.344,0.452),("supplementary_delta",0.452,0.56),("carried_budget",0.56,0.665),("reserve_and_transfer_delta",0.665,0.771),("current_budget",0.771,0.888)]
let right:[(String,Double,Double)] = [("setsu",0.09,0.216),("budget_current",0.216,0.322),("executed",0.322,0.432),("carryover",0.432,0.55),("unused",0.55,0.653),("remarks",0.653,0.93)]
var output:[[String:Any]]=[]
for (column,baseLo,baseHi) in (isLeft ? left : right) {
 let lo=baseLo+shift,hi=baseHi+shift
 let cropped=image.cropping(to:CGRect(x:lo*Double(image.width),y:0,width:(hi-lo)*Double(image.width),height:Double(image.height)))!
 let request=VNRecognizeTextRequest();request.recognitionLevel = .accurate;request.recognitionLanguages=["ja-JP","en-US"];request.usesLanguageCorrection=false;request.minimumTextHeight=0.002
 try VNImageRequestHandler(cgImage:cropped).perform([request])
 for (index,obs) in (request.results ?? []).enumerated() {
  guard let c=obs.topCandidates(3).first else{continue};let b=obs.boundingBox
  output.append(["column":column,"observation_index":index+1,"text":c.string,"confidence":c.confidence,
   "alternatives":obs.topCandidates(3).map{["text":$0.string,"confidence":$0.confidence]},
   "bbox_normalized_top_left":[lo+b.minX*(hi-lo),1-b.maxY,lo+b.maxX*(hi-lo),1-b.minY]])
 }
}
let result:[String:Any]=["original_page_json":CommandLine.arguments[1],"printed_page":printed,"physical_page":spec["physical_page"]!,"part":spec["part"]!,"origin_sha256":spec["origin_sha256"]!,"header_evidence":header[0],"horizontal_shift":shift,"observations":output,"uses_language_correction":false]
try FileManager.default.createDirectory(at:jsonURL.deletingLastPathComponent(),withIntermediateDirectories:true)
try JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys]).write(to:jsonURL,options:.atomic)
