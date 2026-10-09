import { timingSafeEqual } from 'node:crypto';

import { PRODUCT, YEAR } from './constants.js';
const SESSION_TTL = 8 * 60 * 60;
const encoder = new TextEncoder();
const timestamp = () => Math.floor(Date.now() / 1000);
const hex = bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
const random = () => hex(crypto.getRandomValues(new Uint8Array(32)));
const digest = async value => hex(await crypto.subtle.digest('SHA-256', encoder.encode(value)));

class ApiError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
const fail = (status, code) => { throw new ApiError(status, code); };
const same = (a, b) => {
  const left = encoder.encode(a || ''), right = encoder.encode(b || '');
  return left.length === right.length && timingSafeEqual(left, right);
};
function json(data, status = 200) {
  return Response.json(data, { status, headers: {
    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer', ...(status === 429 ? { 'Retry-After': '900' } : {})
  }});
}
async function body(request) {
  if (!(request.headers.get('Content-Type') || '').startsWith('application/json')) fail(415, 'json_required');
  if (Number(request.headers.get('Content-Length')) > 8192) fail(413, 'body_too_large');
  const reader = request.body?.getReader();
  if (!reader) fail(400, 'invalid_request');
  const chunks = []; let length = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    length += value.length;
    if (length > 8192) { await reader.cancel(); fail(413, 'body_too_large'); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  try {
    const value = JSON.parse(new TextDecoder().decode(bytes));
    if (!value || Array.isArray(value) || typeof value !== 'object') fail(400, 'invalid_request');
    return value;
  } catch { fail(400, 'invalid_request'); }
}
function binding(input) {
  if (input.product_id !== PRODUCT) fail(403, 'wrong_product');
  if (typeof input.installation_id !== 'string' || !/^[a-zA-Z0-9_-]{32,128}$/.test(input.installation_id)) fail(400, 'invalid_installation');
  let url;
  try { url = new URL(input.deployment_url); } catch { fail(400, 'invalid_deployment'); }
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') fail(400, 'invalid_deployment');
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname))) fail(400, 'invalid_deployment');
  return { deployment: url.origin, id: input.installation_id };
}
async function installation(input) {
  const value = binding(input);
  return { hash: await digest(`${PRODUCT}:installation:${value.id}:${value.deployment}`), url: value.deployment };
}
function credentials(input) {
  if (typeof input.username !== 'string' || typeof input.password !== 'string') fail(400, 'invalid_credentials');
  const username = input.username.trim().toLowerCase();
  if (!/^[a-z0-9_.-]{3,64}$/.test(username) || input.password.length < 12 || input.password.length > 128) fail(400, 'invalid_credentials');
  return { username, password: input.password };
}
async function passwordHash(password, salt, pepper) {
  const key = await crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', iterations: 100000, salt: encoder.encode(salt) }, key, 256);
  const hmac = await crypto.subtle.importKey('raw', encoder.encode(pepper), {name:'HMAC', hash:'SHA-256'}, false, ['sign']);
  return hex(await crypto.subtle.sign('HMAC', hmac, bits));
}
function publicLicense(row) {
  const now = timestamp();
  return { product_id: PRODUCT, license_id: row.id, label: row.label,
    status: row.status === 'revoked' ? 'revoked' : (row.expires_at !== null && row.expires_at <= now ? 'expired' : 'active'),
    activated_at: row.activated_at, expires_at: row.expires_at, server_time: now,
    deployment_url: row.deployment_url, owner_username: row.owner_username,
    can_start: row.status === 'active' && row.expires_at !== null && row.expires_at > now && row.installation_hash !== null };
}
async function rateLimit(db, key, limit, window = 900) {
  const now = timestamp();
  const row = await db.prepare(`INSERT INTO gostream_auth_buckets(bucket,window_started_at,attempts) VALUES(?,?,1)
    ON CONFLICT(bucket) DO UPDATE SET
      attempts=CASE WHEN window_started_at<=? THEN 1 ELSE attempts+1 END,
      window_started_at=CASE WHEN window_started_at<=? THEN excluded.window_started_at ELSE window_started_at END
    RETURNING attempts`).bind(await digest(key), now, now-window, now-window).first();
  if (row.attempts > limit) fail(429, 'rate_limited');
}
async function createSession(db, row) {
  const token = random(), now = timestamp();
  // Conditional INSERT prevents a concurrent reset/revoke from minting a usable old session.
  const result = await db.prepare(`INSERT INTO gostream_sessions(token_hash,license_id,revision,expires_at,created_at)
    SELECT ?,id,revision,?,? FROM gostream_licenses WHERE id=? AND revision=? AND installation_hash IS NOT NULL`)
    .bind(await digest(token), now+SESSION_TTL, now, row.id, row.revision).run();
  if (!result.meta.changes) fail(409, 'activation_changed');
  return { session_token: token, session_expires_at: now+SESSION_TTL, license: publicLicense(row) };
}
async function session(request, db, input) {
  const target = await installation(input);
  const token = (request.headers.get('Authorization') || '').replace(/^Bearer /, '');
  if (!/^[a-f0-9]{64}$/.test(token)) fail(401, 'login_required');
  const row = await db.prepare(`SELECT l.*,s.expires_at AS session_expires,s.revision AS session_revision
    FROM gostream_sessions s JOIN gostream_licenses l ON l.id=s.license_id
    WHERE s.token_hash=? AND l.product_id=?`).bind(await digest(token), PRODUCT).first();
  if (!row || row.session_expires <= timestamp() || row.session_revision !== row.revision ||
      row.installation_hash !== target.hash || row.deployment_url !== target.url) fail(401, 'login_required');
  return row;
}
async function activate(db, env, input) {
  const target = await installation(input), owner = credentials(input);
  if (typeof input.license_key !== 'string') fail(400, 'invalid_license');
  const code = input.license_key.trim().toUpperCase();
  if (!/^MGS-[A-F0-9]{64}$/.test(code)) fail(403, 'invalid_license');
  const row = await db.prepare('SELECT * FROM gostream_licenses WHERE code_hash=? AND product_id=?')
    .bind(await digest(`${PRODUCT}:license:${code}`), PRODUCT).first();
  if (!row) fail(403, 'invalid_license');
  if (row.status !== 'active') fail(403, 'license_revoked');
  if (row.expires_at !== null && row.expires_at <= timestamp()) fail(403, 'license_expired');
  if (row.password_hash && (row.owner_username !== owner.username ||
      !same(await passwordHash(owner.password, row.password_salt, env.AUTH_PEPPER), row.password_hash))) fail(401, 'invalid_credentials');
  if (row.installation_hash && row.installation_hash !== target.hash) fail(409, 'installation_in_use');
  if (row.installation_hash === target.hash && row.password_hash) return createSession(db, row);
  const salt = row.password_salt || random();
  const hash = row.password_hash || await passwordHash(owner.password, salt, env.AUTH_PEPPER);
  const now = timestamp();
  const updated = await db.prepare(`UPDATE gostream_licenses SET
    activated_at=COALESCE(activated_at,?),expires_at=COALESCE(expires_at,?),
    installation_hash=?,deployment_url=?,owner_username=?,password_salt=?,password_hash=?,revision=revision+1
    WHERE id=? AND product_id=? AND revision=? AND status='active'
      AND (expires_at IS NULL OR expires_at>?) AND installation_hash IS NULL
    RETURNING *`).bind(now,now+YEAR,target.hash,target.url,owner.username,salt,hash,row.id,PRODUCT,row.revision,now).first();
  if (!updated) fail(409, 'activation_changed');
  return createSession(db, updated);
}
async function login(db, env, input) {
  const target = await installation(input), owner = credentials(input);
  const row = await db.prepare('SELECT * FROM gostream_licenses WHERE installation_hash=? AND deployment_url=? AND product_id=?')
    .bind(target.hash,target.url,PRODUCT).first();
  // Expired/revoked owners can log in to stop an already-running stream.
  if (!row || !row.password_hash || row.owner_username !== owner.username ||
      !same(await passwordHash(owner.password,row.password_salt,env.AUTH_PEPPER),row.password_hash)) fail(401,'invalid_credentials');
  return createSession(db,row);
}
async function admin(request, db, env, path) {
  const provided = (request.headers.get('Authorization') || '').replace(/^Bearer /, '');
  if (!env.ADMIN_TOKEN || !same(await digest(provided),await digest(env.ADMIN_TOKEN))) fail(401,'admin_required');
  if (request.method === 'GET' && path === '/admin/licenses') {
    const data = await db.prepare(`SELECT id,product_id,label,status,created_at,activated_at,expires_at,deployment_url,owner_username
      FROM gostream_licenses WHERE product_id=? ORDER BY created_at DESC,id LIMIT 100`).bind(PRODUCT).all();
    return json({licenses:data.results});
  }
  if (request.method !== 'POST') fail(405,'method_not_allowed');
  const input = await body(request);
  if (input.product_id !== PRODUCT) fail(403,'wrong_product');
  if (path === '/admin/licenses') {
    if (typeof input.label !== 'string' || input.label.length > 160) fail(400,'invalid_label');
    const code = 'MGS-'+random().toUpperCase(), id = crypto.randomUUID();
    await db.prepare('INSERT INTO gostream_licenses(id,product_id,code_hash,label,created_at) VALUES(?,?,?,?,?)')
      .bind(id,PRODUCT,await digest(`${PRODUCT}:license:${code}`),input.label,timestamp()).run();
    return json({license_id:id,product_id:PRODUCT,license_key:code,duration_days:365,starts_on:'first_activation'},201);
  }
  if (path !== '/admin/action' || typeof input.license_id !== 'string') fail(404,'not_found');
  const id = input.license_id;
  let row;
  if (['revoke','restore'].includes(input.action)) {
    row = await db.prepare('UPDATE gostream_licenses SET status=?,revision=revision+1 WHERE id=? AND product_id=? RETURNING *')
      .bind(input.action === 'revoke' ? 'revoked' : 'active',id,PRODUCT).first();
  } else if (input.action === 'reset-installation' || input.action === 'reset-owner') {
    const ownerReset = input.action === 'reset-owner' ? ',owner_username=NULL,password_salt=NULL,password_hash=NULL' : '';
    row = await db.prepare(`UPDATE gostream_licenses SET installation_hash=NULL,deployment_url=NULL,revision=revision+1${ownerReset}
      WHERE id=? AND product_id=? RETURNING *`).bind(id,PRODUCT).first();
  } else if (input.action === 'extend') {
    if (!Number.isInteger(input.days) || input.days < 1 || input.days > 3650) fail(400,'invalid_days');
    row = await db.prepare(`UPDATE gostream_licenses SET expires_at=MAX(expires_at,?)+?
      WHERE id=? AND product_id=? AND activated_at IS NOT NULL RETURNING *`).bind(timestamp(),input.days*86400,id,PRODUCT).first();
  } else fail(400,'invalid_action');
  if (!row) fail(404,'license_not_found_or_not_activated');
  return json({license:publicLicense(row)});
}

export default {
  async fetch(request, env) {
    try {
      const path = new URL(request.url).pathname;
      if (request.method === 'GET' && path === '/health') return json({service:'Masyas Go Stream licensing',product_id:PRODUCT});
      if (!env.AUTH_PEPPER || !env.ADMIN_TOKEN) fail(503,'service_not_ready');
      const db = env.DB.withSession ? env.DB.withSession('first-primary') : env.DB;
      if (path.startsWith('/admin/')) return await admin(request,db,env,path);
      if (!['/v1/activate','/v1/login','/v1/check','/v1/logout','/v1/release'].includes(path)) fail(404,'not_found');
      if (request.method !== 'POST') fail(405,'method_not_allowed');
      const input = await body(request);
      binding(input);
      if (path === '/v1/activate' || path === '/v1/login') {
        await rateLimit(db,'ip:'+(request.headers.get('CF-Connecting-IP') || 'unknown'),60);
        await rateLimit(db,'install:'+input.installation_id,30);
        return json(await (path === '/v1/activate' ? activate(db,env,input) : login(db,env,input)));
      }
      const row = await session(request,db,input);
      if (path === '/v1/check') return json({license:publicLicense(row)});
      if (path === '/v1/logout') {
        const token = request.headers.get('Authorization').slice(7);
        await db.prepare('DELETE FROM gostream_sessions WHERE token_hash=?').bind(await digest(token)).run();
        return json({ok:true});
      }
      await db.prepare(`UPDATE gostream_licenses SET installation_hash=NULL,deployment_url=NULL,revision=revision+1
        WHERE id=? AND product_id=? AND revision=?`).bind(row.id,PRODUCT,row.revision).run();
      return json({ok:true});
    } catch (error) {
      if (error instanceof ApiError) return json({error:error.code},error.status);
      // Never log request bodies, credentials, token values, or SQL bind values.
      return json({error:'service_unavailable'},503);
    }
  },
  async scheduled(event,env,ctx) {
    const now=timestamp();
    ctx.waitUntil(env.DB.batch([
      env.DB.prepare('DELETE FROM gostream_sessions WHERE expires_at<=?').bind(now),
      env.DB.prepare('DELETE FROM gostream_auth_buckets WHERE window_started_at<?').bind(now-86400)
    ]));
  }
};
