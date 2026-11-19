"use strict";
const {test}=require("node:test");
const assert=require("node:assert/strict");
const svg=require("../ui/note-svg.js");
test("exports primitives and escapes untrusted labels",()=>{
  const items=[{kind:"callout",x:.2,y:.2,number:1,label:'<script>alert("x")</script>'},
    {kind:"graph",x:.1,y:.1,width:.4,height:.4,expression:"x<2",segments:[[[0,0],[1,1]]]},
    {kind:"geometry",x:.1,y:.1,width:.8,height:.8,objects:[
      {kind:"point",x:.2,y:.3,label:"A"}, {kind:"segment",x1:.1,y1:.2,x2:.8,y2:.9,label:"L"},
      {kind:"circle",cx:.5,cy:.5,radius:.2,label:"C"}, {kind:"polygon",points:[[.1,.1],[.7,.1],[.4,.8]],label:"P"}],
      constraints:[{kind:"horizontal",objects:[1]}]}];
  const out=svg.build(items,[{color:"#55d6ff",size:4,points:[{x:0,y:0},{x:1,y:1}]}],1000,500);
  assert.match(out,/^<svg /); assert.match(out,/<polyline/); assert.match(out,/<ellipse/);
  assert.match(out,/<polygon/); assert.match(out,/↔/); assert.match(out,/&lt;script&gt;/);
  assert.doesNotMatch(out,/<script|<image|foreignObject|onload=/);
});
test("rejects invalid dimensions and skips malformed points",()=>{
  assert.throws(()=>svg.build([],[],0,100));
  const out=svg.build([{kind:"pin",x:NaN,y:.2}],[],100,100);
  assert.doesNotMatch(out,/<circle/);
});
test("SVG has accessible metadata, subdued grid, and well-formed text",()=>{
  const items=[{kind:"graph",x:0,y:0,width:.8,height:.8,expression:"\ud800x",segments:[]}];
  const out=svg.build(items,[],500,400);
  assert.match(out,/<title id="note-title">/);
  assert.match(out,/<desc id="note-description">1 visual items and 0 drawing strokes\.<\/desc>/);
  assert.match(out,/stroke-opacity="0.3"/);
  assert.ok(!out.includes("\ud800"));
});
test("describes geometry objects without trusting labels as markup",()=>{
  const text=svg.describe([{kind:"geometry",objects:[{kind:"point",label:"A"},{kind:"segment",label:"AB"}]}],[{}]);
  assert.match(text,/point A, segment AB/);
  assert.match(text,/Drawing strokes: 1/);
});
