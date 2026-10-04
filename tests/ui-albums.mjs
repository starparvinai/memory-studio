import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

test('testing Immich saves entered connection before loading albums', async () => {
  const html = readFileSync(new URL('../src/memory_studio/static/index.html', import.meta.url), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
  assert.ok(script);
  const nodes = new Map();
  const element = (id) => {
    if (!nodes.has(id)) nodes.set(id, { value: '', hidden: true, innerHTML: '', style: {}, scrollIntoView() {} });
    return nodes.get(id);
  };
  const calls = [];
  let saved = false;
  let postBody;
  let checked = [];
  const response = (status, body) => ({ ok: status < 400, json: async () => body });
  const fetch = async (path, options = {}) => {
    calls.push(`${options.method ?? 'GET'} ${path}`);
    if (path === '/api/settings' && options.method === 'PUT') {
      const body = JSON.parse(options.body);
      saved = body.immich_url === 'https://photos.example' && body.immich_api_key === 'test-key';
      return response(200, {});
    }
    if (path === '/api/settings') return response(200, { immich_url: '', vision_provider: 'ollama', ollama_url: '', ollama_model: '', openrouter_model: '' });
    if (path === '/api/projects' && options.method === 'POST') { postBody = JSON.parse(options.body); return response(200, { id: 'project-1' }); }
    if (path === '/api/projects') return response(200, []);
    if (path === '/api/albums') return saved ? response(200, [{ id: 'album-1', albumName: 'Family', assetCount: 20 }, { id: 'album-2', albumName: 'Holiday', assetCount: 15 }]) : response(502, { detail: 'Set your Immich URL and API key in Settings.' });
    if (path === '/api/projects/project-1') return response(200, { id: 'project-1', title: 'First year', status: 'ready', birth_date: '2025-01-01', cards: [], warnings: [] });
    throw Error(`Unexpected request: ${path}`);
  };
  vm.runInNewContext(script, {
    document: { getElementById: element, addEventListener() {}, querySelectorAll: () => checked.map(value => ({ value })) },
    fetch, location: { hash: '' }, setTimeout() {}, clearTimeout() {}, history: { replaceState() {} },
  });
  await new Promise((resolve) => setImmediate(resolve));
  element('immich-url').value = 'https://photos.example';
  element('immich-key').value = 'test-key';
  await element('load-albums').onclick();
  assert.equal(saved, true);
  assert.deepEqual(calls.slice(-2), ['PUT /api/settings', 'GET /api/albums']);
  assert.match(element('albums').innerHTML, /Family/);
  assert.match(element('albums').innerHTML, /Holiday/);
  assert.equal((element('albums').innerHTML.match(/type="checkbox"/g) ?? []).length, 2);
  checked = ['album-1', 'album-2'];
  element('birth-date').value = '2025-01-01';
  await element('create-form').onsubmit({ preventDefault() {}, submitter: { disabled: false } });
  assert.deepEqual(postBody.album_ids, checked);
});
