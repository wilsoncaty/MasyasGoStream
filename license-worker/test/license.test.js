import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import worker from '../src/index.js';
import { PRODUCT, YEAR } from '../src/constants.js';

class D1 {
  constructor() { this.db = new DatabaseSync(':memory:'); this.db.exec(readFileSync(new URL('../schema.sql',import.meta.url),'utf8')); }
  withSession() { return this; }
  prepare(sql) {
    const database=this.db;
    return { bind(...args) {
      return {
        async first() { return database.prepare(sql).get(...args) || null; },
        async all() { return {results:database.prepare(sql).all(...args)}; },
        async run() { const result=database.prepare(sql).run(...args); return {meta:{changes:Number(result.changes)}}; }
      };
    }};
  }
}
function setup(t) {
  const db=new D1(); t.after(()=>db.db.close());
  const env={DB:db,ADMIN_TOKEN:'test-admin-token',AUTH_PEPPER:'test-pepper-secret'};
  async function api(path,input,token,method='POST') {
    const request=new Request('https://license.test'+path,{method,headers:{'Content-Type':'application/json',...(token ? {Authorization:'Bearer '+token}:{})},...(method==='POST'?{body:JSON.stringify(input)}:{})});
    const response=await worker.fetch(request,env);
    return {status:response.status,...await response.json()};
  }
  const binding={product_id:PRODUCT,installation_id:'a'.repeat(48),deployment_url:'https://one.streamlit.app'};
  const owner={username:'owner',password:'a-long-owner-password'};
  async function issue() {
    const result=await api('/admin/licenses',{product_id:PRODUCT,label:'test'},env.ADMIN_TOKEN);
    assert.equal(result.status,201); return result;
  }
  return {api,db,env,binding,owner,issue};
}

test('365 days from first activation, multiple browsers and stable restart identity',async t=>{
  const {api,db,binding,owner,issue}=setup(t), key=await issue();
  assert.equal(db.db.prepare('SELECT activated_at FROM gostream_licenses').get().activated_at,null);
  const first=await api('/v1/activate',{...binding,...owner,license_key:key.license_key});
  assert.equal(first.status,200); assert.equal(first.license.expires_at-first.license.activated_at,YEAR);
  const browser2=await api('/v1/login',{...binding,...owner});
  assert.equal(browser2.status,200); assert.notEqual(browser2.session_token,first.session_token);
  for (const token of [first.session_token,browser2.session_token]) {
    assert.equal((await api('/v1/check',binding,token)).license.can_start,true);
  }
  const repeated=await api('/v1/activate',{...binding,...owner,license_key:key.license_key});
  assert.equal(repeated.license.expires_at,first.license.expires_at);
  assert.equal((await api('/v1/check',binding,first.session_token)).status,200);
  assert.equal(db.db.prepare('SELECT COUNT(*) AS n FROM gostream_licenses WHERE installation_hash IS NOT NULL').get().n,1);
});
test('other products, invalid keys and wrong deployment are rejected',async t=>{
  const {api,binding,owner,issue}=setup(t), key=await issue();
  assert.equal((await api('/v1/activate',{...binding,...owner,product_id:'other-product',license_key:key.license_key})).error,'wrong_product');
  assert.equal((await api('/v1/activate',{...binding,...owner,license_key:'OLD-PRODUCT-LICENSE'})).error,'invalid_license');
  const auth=await api('/v1/activate',{...binding,...owner,license_key:key.license_key});
  const other={...binding,installation_id:'b'.repeat(48),deployment_url:'https://two.streamlit.app'};
  assert.equal((await api('/v1/activate',{...other,...owner,license_key:key.license_key})).error,'installation_in_use');
  assert.equal((await api('/v1/check',other,auth.session_token)).status,401);
  assert.equal((await api('/v1/check',{...binding,deployment_url:other.deployment_url},auth.session_token)).status,401);
});
test('concurrent activation cannot claim two deployments',async t=>{
  const {api,binding,owner,issue,db}=setup(t),key=await issue();
  const results=await Promise.all(['a','b'].map(id=>api('/v1/activate',{...binding,...owner,installation_id:id.repeat(48),license_key:key.license_key})));
  assert.equal(results.filter(r=>r.status===200).length,1);
  assert.equal(db.db.prepare('SELECT COUNT(*) AS n FROM gostream_licenses WHERE activated_at IS NOT NULL').get().n,1);
});
test('expiry denies starts but owner still logs in; reset never restarts the year',async t=>{
  const {api,db,binding,owner,issue,env}=setup(t),key=await issue();
  const auth=await api('/v1/activate',{...binding,...owner,license_key:key.license_key});
  await api('/admin/action',{product_id:PRODUCT,license_id:key.license_id,action:'reset-installation'},env.ADMIN_TOKEN);
  assert.equal((await api('/v1/check',binding,auth.session_token)).status,401);
  const next={...binding,installation_id:'b'.repeat(48)};
  const rebound=await api('/v1/activate',{...next,...owner,license_key:key.license_key});
  assert.equal(rebound.license.expires_at,auth.license.expires_at);
  db.db.prepare('UPDATE gostream_licenses SET expires_at=?').run(Math.floor(Date.now()/1000)-1);
  const expired=await api('/v1/login',{...next,...owner});
  assert.equal(expired.status,200); assert.equal(expired.license.status,'expired');
  assert.equal(expired.license.can_start,false);
  assert.equal((await api('/v1/check',next,expired.session_token)).license.can_start,false);
  assert.equal((await api('/v1/activate',{...next,...owner,license_key:key.license_key})).error,'license_expired');
});
test('revocation and logout invalidate sessions; wrong password has no access',async t=>{
  const {api,binding,owner,issue,env}=setup(t),key=await issue();
  let auth=await api('/v1/activate',{...binding,...owner,license_key:key.license_key});
  assert.equal((await api('/v1/login',{...binding,...owner,password:'another-wrong-password'})).status,401);
  await api('/v1/logout',binding,auth.session_token);
  assert.equal((await api('/v1/check',binding,auth.session_token)).status,401);
  auth=await api('/v1/login',{...binding,...owner});
  assert.equal((await api('/admin/action',{product_id:PRODUCT,license_id:key.license_id,action:'revoke'},'bad')).status,401);
  await api('/admin/action',{product_id:PRODUCT,license_id:key.license_id,action:'revoke'},env.ADMIN_TOKEN);
  assert.equal((await api('/v1/check',binding,auth.session_token)).status,401);
  const revoked=await api('/v1/login',{...binding,...owner});
  assert.equal(revoked.license.can_start,false);
});
test('owner release and administrator renewal preserve activation date',async t=>{
  const {api,binding,owner,issue,env}=setup(t),key=await issue();
  const auth=await api('/v1/activate',{...binding,...owner,license_key:key.license_key});
  assert.equal((await api('/v1/release',binding,auth.session_token)).status,200);
  const next={...binding,installation_id:'c'.repeat(48)};
  const moved=await api('/v1/activate',{...next,...owner,license_key:key.license_key});
  assert.equal(moved.license.expires_at,auth.license.expires_at);
  const extended=await api('/admin/action',{product_id:PRODUCT,license_id:key.license_id,action:'extend',days:365},env.ADMIN_TOKEN);
  assert.equal(extended.license.expires_at,auth.license.expires_at+YEAR);
  assert.equal(extended.license.activated_at,auth.license.activated_at);
});
test('passwords and raw license codes are not stored; auth attempts are bounded',async t=>{
  const {api,db,binding,owner,issue}=setup(t),key=await issue();
  await api('/v1/activate',{...binding,...owner,license_key:key.license_key});
  const rows=JSON.stringify(db.db.prepare('SELECT * FROM gostream_licenses').all());
  assert.ok(!rows.includes(key.license_key)); assert.ok(!rows.includes(owner.password));
  let last;
  for(let i=0;i<31;i++) last=await api('/v1/login',{...binding,username:'not-owner',password:'not-the-owner-password'});
  assert.equal(last.status,429);
});
