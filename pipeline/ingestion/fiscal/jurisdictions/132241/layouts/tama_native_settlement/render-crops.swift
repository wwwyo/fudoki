import Foundation
import CoreGraphics
import ImageIO
let spec=try JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))) as! [[String:Any]]
let cellWidth=CommandLine.arguments.count>3 ? Int(CommandLine.arguments[3])! : 1200,cellHeight=CommandLine.arguments.count>4 ? Int(CommandLine.arguments[4])! : 200
let columns=CommandLine.arguments.count>5 ? Int(CommandLine.arguments[5])! : 1, rows=(spec.count+(CommandLine.arguments.count>5 ? Int(CommandLine.arguments[5])! : 1)-1)/(CommandLine.arguments.count>5 ? Int(CommandLine.arguments[5])! : 1)
let ctx=CGContext(data:nil,width:cellWidth*columns,height:cellHeight*rows,bitsPerComponent:8,bytesPerRow:cellWidth*columns*4,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.setFillColor(CGColor(gray:1,alpha:1));ctx.fill(CGRect(x:0,y:0,width:cellWidth*columns,height:cellHeight*rows))
for (i,s) in spec.enumerated(){
 let source=CGImageSourceCreateWithURL(URL(fileURLWithPath:s["image"] as! String) as CFURL,nil)!,im=CGImageSourceCreateImageAtIndex(source,0,nil)!,b=s["bbox"] as! [Double]
 let crop=im.cropping(to:CGRect(x:b[0]*Double(im.width),y:b[1]*Double(im.height),width:(b[2]-b[0])*Double(im.width),height:(b[3]-b[1])*Double(im.height)))!
 let scale=min(Double(cellWidth)/Double(crop.width),Double(cellHeight)/Double(crop.height));let w=Double(crop.width)*scale,h=Double(crop.height)*scale
 ctx.draw(crop,in:CGRect(x:Double(i%columns*cellWidth),y:Double((rows-i/columns-1)*cellHeight)+(Double(cellHeight)-h)/2,width:w,height:h))
}
let dest=CGImageDestinationCreateWithURL(URL(fileURLWithPath:CommandLine.arguments[2]) as CFURL,"public.png" as CFString,1,nil)!
CGImageDestinationAddImage(dest,ctx.makeImage()!,nil);CGImageDestinationFinalize(dest)
