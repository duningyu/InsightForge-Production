import http from "node:http";

const BASE = process.argv[2] || "http://127.0.0.1:18001";
const PORT = Number(process.argv[3] || 9227);
const WAIT = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function getJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let text = "";
      res.on("data", (chunk) => { text += chunk; });
      res.on("end", () => { try { resolve(JSON.parse(text)); } catch (err) { reject(err); } });
    }).on("error", reject);
  });
}

async function main() {
  let version;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try { version = await getJson(`http://127.0.0.1:${PORT}/json/version`); break; }
    catch { await WAIT(200); }
  }
  if (!version) throw new Error("CDP endpoint unavailable");

  const targets = await getJson(`http://127.0.0.1:${PORT}/json/list`);
  const page = targets.find((target) => target.type === "page" && target.webSocketDebuggerUrl);
  if (!page) throw new Error("CDP page target unavailable");
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let nextId = 0;
  const pending = new Map();
  const events = [];
  socket.onmessage = (message) => {
    const packet = JSON.parse(message.data);
    if (packet.id && pending.has(packet.id)) { pending.get(packet.id)(packet); pending.delete(packet.id); }
    else events.push(packet);
  };
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, (packet) => packet.error ? reject(new Error(JSON.stringify(packet.error))) : resolve(packet.result));
    socket.send(JSON.stringify({ id, method, params }));
  });

  await call("Network.enable", { maxTotalBufferSize: 50 * 1024 * 1024, maxResourceBufferSize: 5 * 1024 * 1024 });
  await call("Page.enable");
  await call("Runtime.enable");
  await call("Page.navigate", { url: `${BASE}/` });
  await WAIT(2500);

  const click = async (label) => {
    const expression = `(() => { const nodes = [...document.querySelectorAll('button,a')]; const node = nodes.find((item) => item.innerText.trim() === ${JSON.stringify(label)} || item.getAttribute('aria-label') === ${JSON.stringify(label)}); if (node) { node.click(); return true; } return false; })()`;
    return (await call("Runtime.evaluate", { expression, returnByValue: true })).result.value;
  };
  const clicks = [];
  for (const label of ["继续当前项目", "文档", "Documents", "历史", "History"]) {
    try { clicks.push({ label, clicked: await click(label) }); } catch (error) { clicks.push({ label, error: String(error) }); }
    await WAIT(700);
  }

  const fetchExpression = `(async () => { const result = {}; const paths = ['/api/health', '/api/projects', '/api/projects/history', '/api/beta/consent']; for (const path of paths) { const response = await fetch(path, { cache: 'no-store' }); result[path] = { status: response.status, headers: Object.fromEntries(response.headers.entries()), body: await response.text() }; } const projects = JSON.parse(result['/api/projects'].body); const id = projects[0]?.id; if (id) { for (const suffix of ['', '/snapshot', '/claims', '/sources', '/documents', '/solutions/generate']) { const path = '/api/projects/' + id + suffix; const response = await fetch(path, { method: suffix === '/solutions/generate' ? 'POST' : 'GET', cache: 'no-store' }); result[path] = { status: response.status, headers: Object.fromEntries(response.headers.entries()), body: await response.text() }; } } return result; })()`;
  const fetched = (await call("Runtime.evaluate", { expression: fetchExpression, awaitPromise: true, returnByValue: true })).result.value;
  await WAIT(1200);

  const requests = new Map();
  const responses = new Map();
  for (const event of events) {
    if (event.method === "Network.requestWillBeSent") requests.set(event.params.requestId, { url: event.params.request.url, method: event.params.request.method, headers: event.params.request.headers, body: event.params.request.postData || null, type: event.params.type });
    if (event.method === "Network.responseReceived") responses.set(event.params.requestId, { url: event.params.response.url, status: event.params.response.status, headers: event.params.response.headers, mime: event.params.response.mimeType, type: event.params.type });
  }
  const captured = [];
  for (const [requestId, response] of responses) {
    try { captured.push({ requestId, ...response, ...(await call("Network.getResponseBody", { requestId })) }); }
    catch (error) { captured.push({ requestId, ...response, bodyCaptureError: String(error) }); }
  }
  const document = (await call("Runtime.evaluate", { expression: "document.documentElement.outerHTML", returnByValue: true })).result.value;
  const serialized = JSON.stringify({ clicks, fetched, requests: [...requests.values()], responses: captured, document });
  const needles = ["TEST_SECRET_QWEN_9F4C", "TEST_SECRET_KIMI_9F4C", "TEST_SECRET_DEEPSEEK_9F4C", "TEST_SECRET_GLM_9F4C", "Authorization", "Bearer", "api_key", "credential", "reasoning_content", "raw provider response"];
  const needleCounts = Object.fromEntries(needles.map((needle) => [needle, (serialized.match(new RegExp(needle.replace(/[.*+?^${}()|[\\]\\]/g, "\\\\$&"), "gi")) || []).length]));
  const canaryMatches = needles.slice(0, 4).reduce((total, needle) => total + needleCounts[needle], 0);
  const credentialValueMatches = (serialized.match(/Bearer\\s+[A-Za-z0-9._-]{20,}/gi) || []).length;
  const required429 = Object.values(fetched).some((value) => value.status === 429) || captured.some((value) => value.status === 429);
  const rateLimitResponse = captured.find((item) => item.status === 429);
  const summary = { target: BASE, browser: "Chrome CDP", clicks, request_count: requests.size, response_count: responses.size, response_body_captured: captured.filter((item) => typeof item.body === "string").length, response_body_capture_failures: captured.filter((item) => item.bodyCaptureError).length, document_captured: typeof document === "string" && document.length > 0, required_fetches: Object.fromEntries(Object.entries(fetched).map(([path, value]) => [path, { status: value.status, body_length: value.body?.length ?? null, headers_captured: !!value.headers }])), rate_limit_429_captured: required429, rate_limit_response: rateLimitResponse ? { url: rateLimitResponse.url, status: rateLimitResponse.status, headers: rateLimitResponse.headers, body: rateLimitResponse.body } : null, needle_counts: needleCounts, canary_match_count: canaryMatches, credential_value_match_count: credentialValueMatches, browser_network_secret_exposure: canaryMatches + credentialValueMatches };
  console.log(JSON.stringify(summary, null, 2));
  socket.close();
  if (summary.response_body_capture_failures || !summary.document_captured || !summary.rate_limit_429_captured || summary.browser_network_secret_exposure > 0) process.exitCode = 2;
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
