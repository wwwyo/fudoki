import Foundation
import PDFKit
let doc = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1]))!
let detail:[(String,Double,Double)] = [("hierarchy",0,90.5),("initial",91,169.5),("amendment",170,238.5),("prior",239,305.0),("transfer",306,366.0),("total",367,445.0),("setsu",446,500.5),("setsu_total",501,572.0),("executed",637,713.0),("carry",714,790.0),("unused",791,866.0),("remarks",867,1104.0),("remarks_amount",1105,1175.0)]
let summary:[(String,Double,Double)] = [("hierarchy",0,107),("initial",108,192),("amendment",193,278),("prior",279,363),("transfer",364,447),("total",448,545),("executed",650,732),("carry_continuing",733,814),("carry_authorized",815,895),("carry_accident",896,976),("unused",977,1058),("remarks",1059,1191)]
let summaryPage = CommandLine.arguments.count > 3 ? Int(CommandLine.arguments[3])! : 3
let detailStart = CommandLine.arguments.count > 4 ? Int(CommandLine.arguments[4])! : 65
let detailEnd = CommandLine.arguments.count > 5 ? Int(CommandLine.arguments[5])! : 147
let contextPage = CommandLine.arguments.count > 6 ? Int(CommandLine.arguments[6])! : 1
let contextTitle=doc.page(at:contextPage-1)?.string ?? ""
var result:[[String:Any]]=[]
for n in [summaryPage] + Array(detailStart...detailEnd) {
 let p=doc.page(at:n-1)!, box=p.bounds(for:.mediaBox)
 var columns:[String:Any]=[:]
 for (name,left,right) in (n==summaryPage ? summary:detail) {
  let area=CGRect(x:left,y:0,width:right-left,height:box.height)
  columns[name]=(p.selection(for:area)?.selectionsByLine() ?? []).map { s -> (text:String,x:CGFloat,y:CGFloat,bottom:CGFloat) in
   let b=s.bounds(for:p)
   return (s.string ?? "",b.minX,box.height-b.maxY,box.height-b.minY)
  }.sorted { $0.y<$1.y }.map { ["text":$0.text,"x":$0.x,"y":$0.y,"bottom":$0.bottom] as [String:Any] }
 }
 result.append(["page":n,"width":box.width,"height":box.height,"columns":columns,"text":p.string ?? "","context_title":contextTitle])
}
try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys]).write(to:URL(fileURLWithPath:CommandLine.arguments[2]))
