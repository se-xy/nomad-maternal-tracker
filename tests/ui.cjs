const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true});fs.mkdirSync('test-artifacts',{recursive:true});
 try {
 for(const [name,width,height] of [['desktop',1440,1100],['mobile',390,844]]){
 const page=await browser.newPage({viewport:{width,height}});const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://localhost:8765/dashboard/?demo=1');
 await page.locator('#list li[data-a]').first().waitFor();
 assert.equal(await page.locator('#list li[data-a]').count(),30);
 assert.equal(await page.locator('#metrics .metric').count(),4);
 await page.locator('#search').fill('M-001');assert.equal(await page.locator('#list li[data-a]').count(),1);
 await page.locator('#search').fill('no-such-mother');assert.match(await page.locator('#list').innerText(),/No records match/);
 await page.locator('#search').fill('');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.screenshot({path:`test-artifacts/${name}.png`,fullPage:true});
 assert.deepEqual(errors,[]);
 await page.close();
 }
 const page=await browser.newPage();let fail=true;
 await page.route('**/api/latest',r=>fail?r.fulfill({status:503,body:'offline'}):r.fulfill({json:JSON.parse(fs.readFileSync('dashboard/demo-data.json','utf8'))}));
 await page.goto('http://localhost:8765/dashboard/');await page.getByText('Offline',{exact:true}).waitFor();assert.equal(await page.locator('#list li[data-a]').count(),0);
 fail=false;await page.locator('#list li[data-a]').first().waitFor({timeout:20000});
 fail=true;await page.getByText('Offline',{exact:true}).waitFor({timeout:20000});assert.equal(await page.locator('#list li[data-a]').count(),30);
 assert.match(await page.locator('#connection').innerText(),/last successful/);
 await page.close();console.log('Desktop, mobile, search, overflow, and API recovery checks passed');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
