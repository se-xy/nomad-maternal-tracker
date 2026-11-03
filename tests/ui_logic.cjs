// Browser-independent checks of the actual dashboard functions. These do not replace visual QA.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
let source=fs.readFileSync('dashboard/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
source=source.slice(0,source.lastIndexOf('loadRegion().then(refresh)'));
const elements={};const get=id=>elements[id] ||= {textContent:'',innerHTML:'',className:'',addEventListener(){}};
const context=vm.createContext({URLSearchParams,AbortSignal,location:{search:''},document:{getElementById:get},L:{map:()=>({on(){},fitBounds(){}}),tileLayer:()=>({addTo(){}}),layerGroup:()=>({addTo(){return {}}})},setTimeout:()=>1,fetch:async()=>({ok:false}),console});
vm.runInContext(source,context);
(async()=>{
 assert.equal(vm.runInContext('normalise({priority:"4",lost:"t",lat:null}).priority',context),4);
 assert.equal(vm.runInContext('normalise({lost:"false"}).lost',context),false);
 vm.runInContext('render=()=>{}; fitAll=()=>{};',context);
 await vm.runInContext('refresh()',context);
 assert.equal(get('source').textContent,'Offline');assert.match(get('connection').innerHTML,/unavailable/);
 context.fetch=async()=>({ok:true,json:async()=>[{alias:'M-001',device_id:'NMT-001',priority:4,lat:3,lon:38,lost:true}]});
 await vm.runInContext('refresh()',context);assert.match(get('source').textContent,/Connected/);
 context.fetch=async()=>{throw new Error('disconnected')};await vm.runInContext('refresh()',context);
 assert.equal(vm.runInContext('rows.length',context),1);assert.match(get('connection').innerHTML,/last successful/);
 vm.runInContext('query="m-001"',context);assert.equal(vm.runInContext('rows.filter(matches).length',context),1);
 vm.runInContext('query="unknown"',context);assert.equal(vm.runInContext('rows.filter(matches).length',context),0);
 assert.equal(vm.runInContext('esc("<script>")',context),'&lt;script&gt;');
 console.log('Dashboard coercion, search, escaping, outage and recovery logic passed');
})().catch(e=>{console.error(e);process.exit(1)});
