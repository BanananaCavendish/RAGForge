/* ═══════════════════════════════════════════════════════════════
   RAGForge —— 前端逻辑(RAGFlow 风格多视图,零构建)
   后端 0 改动:17 个 API 端点、SSE 事件格式全部原样。
   区块:utils / state / views / auth / sessions / chat /
        citation / copy / knowledge / settings / confirm / boot
   ═══════════════════════════════════════════════════════════════ */

// ───────── utils ────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function toast(msg, isErr) {
  const t = document.createElement("div");
  t.className = "toast" + (isErr ? " err" : "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

function authHeaders(extra = {}) {
  const t = getToken();
  return t ? { ...extra, Authorization: "Bearer " + t } : extra;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: authHeaders(opts.headers || {}) });
  const isAuthRoute = path.startsWith("/api/auth/");
  // 鉴权接口的 401 = 用户名/密码错;普通接口的 401 = 令牌过期,清登录态回登录页
  if (res.status === 401 && !isAuthRoute) { clearAuth(); showLogin(); throw new Error("登录已过期,请重新登录"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (isAuthRoute && res.status === 401) throw new Error("用户名或密码错误");
    throw new Error(data.detail || ("HTTP " + res.status));
  }
  return data;
}

// ───────── state ────────────────────────────────────────────────
const TOKEN_KEY = "rag_token", USER_KEY = "rag_user";
const getToken = () => localStorage.getItem(TOKEN_KEY);
const setAuth = (token, user) => { localStorage.setItem(TOKEN_KEY, token); localStorage.setItem(USER_KEY, JSON.stringify(user)); };
const clearAuth = () => { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); };
const getCachedUser = () => { try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; } };

let currentUser = null;
let currentSessionId = null;
let sessions = [];
let curSettings = null;
let taskPolling = false;
let rebuildPolling = false;
let authMode = "login";
let citationHideTimer = null;

// ───────── views ────────────────────────────────────────────────
function showLogin() { $("loginView").hidden = false; $("appView").hidden = true; }
function showApp() { $("loginView").hidden = true; $("appView").hidden = false; }

function switchMainView(name) {
  $("chatView").hidden = name !== "chat";
  $("kbView").hidden = name !== "kb";
  $("railChat").classList.toggle("active", name === "chat");
  $("railKb").classList.toggle("active", name === "kb");
  if (name === "kb") loadDocs(); // 每次切入刷新文档列表,保证状态徽章/统计最新
}

// ───────── auth ─────────────────────────────────────────────────
async function init() {
  if (!getToken()) { showLogin(); return; }
  try {
    const me = await api("/api/auth/me");
    localStorage.setItem(USER_KEY, JSON.stringify(me));
    enterApp(me);
  } catch { showLogin(); }
}

function enterApp(user) {
  currentUser = user;
  showApp();
  const avatar = $("railUser");
  avatar.textContent = (user.username || "U").slice(0, 1).toUpperCase();
  avatar.title = (user.role === "admin" ? "管理员" : "用户") + " · " + user.username;
  // 模型设置 / 重建索引仅管理员可见
  $("railSettings").hidden = user.role !== "admin";
  switchMainView("chat");
  loadSessions();
  loadDocs();
}

function logout() { clearAuth(); showLogin(); }

async function submitAuth() {
  const username = $("authUser").value.trim();
  const password = $("authPass").value;
  if (!username || !password) { toast("请输入用户名和密码", true); return; }
  const path = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
  try {
    const data = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    setAuth(data.token, data.user);
    toast(authMode === "login" ? "登录成功 ✅" : "注册成功,首个用户为管理员 ✅");
    enterApp(data.user);
  } catch (e) { toast(e.message, true); }
}

// ───────── sessions ─────────────────────────────────────────────
async function loadSessions() {
  sessions = await api("/api/sessions");
  if (!sessions.length) {
    sessions = [await api("/api/sessions", { method: "POST" })];
  }
  if (!currentSessionId || !sessions.some((s) => s.id === currentSessionId)) {
    currentSessionId = sessions[0].id;
  }
  renderSessions();
  loadMessages(currentSessionId);
}

function renderSessions() {
  const box = $("sessionList");
  box.innerHTML = "";
  $("sessionEmptyState").hidden = sessions.length > 0;
  sessions.forEach((s) => {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === currentSessionId ? " active" : "");
    item.innerHTML = `<span class="name" title="${esc(s.title)}">${esc(s.title)}</span><button class="del" title="删除会话">✕</button>`;
    item.onclick = () => switchSession(s.id);
    item.querySelector(".del").onclick = async (ev) => {
      ev.stopPropagation();
      if (!(await confirmDialog("删除该会话？"))) return;
      await api("/api/sessions/" + s.id, { method: "DELETE" });
      if (currentSessionId === s.id) { currentSessionId = null; }
      loadSessions();
    };
    box.appendChild(item);
  });
}

function switchSession(id) {
  currentSessionId = id;
  renderSessions();
  loadMessages(id);
  $("chatSidebar").classList.remove("open"); // 窄屏抽屉选完收起
}

async function newSession() {
  const created = await api("/api/sessions", { method: "POST" });
  sessions.unshift(created);
  currentSessionId = created.id;
  renderSessions();
  loadMessages(created.id);
  $("chatSidebar").classList.remove("open");
}

// ───────── chat ─────────────────────────────────────────────────
const messagesEl = $("messages");
const inputEl = $("input");
const sendBtn = $("send");

function showThread() { messagesEl.hidden = false; $("emptyChatState").hidden = true; }
function showEmptyState() { messagesEl.hidden = true; $("emptyChatState").hidden = false; }

async function loadMessages(sessionId) {
  const data = await api(`/api/sessions/${sessionId}/messages`);
  messagesEl.innerHTML = "";
  const cur = sessions.find((s) => s.id === sessionId);
  $("chatTitle").textContent = cur ? cur.title : "对话助手";
  if (!data.messages.length) { showEmptyState(); return; }
  data.messages.forEach((m) => addMessage(m.role, m.content));
  showThread();
}

// 构建一条 assistant 消息骨架,返回可继续写内容的引用
function buildAssistantMessage() {
  const wrap = document.createElement("div");
  wrap.className = "msg assistant";
  const head = document.createElement("div");
  head.className = "msg-head";
  const roleLabel = document.createElement("span");
  roleLabel.className = "msg-role";
  roleLabel.textContent = "助手";
  const copyBtn = document.createElement("button");
  copyBtn.className = "copy-btn";
  copyBtn.textContent = "⧉";
  copyBtn.title = "复制回答";
  head.appendChild(roleLabel);
  head.appendChild(copyBtn);
  const content = document.createElement("div");
  content.className = "stream-content";
  const sources = document.createElement("div");
  sources.className = "sources";
  sources.hidden = true;
  wrap.appendChild(head);
  wrap.appendChild(content);
  wrap.appendChild(sources);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return { wrap, content, sources, copyBtn };
}

function addMessage(role, text, sources) {
  if (role === "assistant") {
    const { content, sources: srcBox, copyBtn } = buildAssistantMessage();
    content.textContent = text;
    copyBtn.onclick = () => copyMessage(text, copyBtn);
    if (sources && sources.length) {
      renderSources(srcBox, sources);
      srcBox.hidden = false;
    }
    return content;
  }
  const div = document.createElement("div");
  div.className = "msg user";
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

// 把 sources(片段级)按 file_idx 分组,key 即文件编号。
// 后端每个片段带 file_idx;旧数据缺省时退回按来源文件名去重编号。
function buildFileGroups(sources) {
  const groups = new Map();
  const byName = new Map();
  sources.forEach((s, i) => {
    let key = s.file_idx != null ? s.file_idx : null;
    if (key == null) {
      if (!byName.has(s.source)) byName.set(s.source, groups.size + 1);
      key = byName.get(s.source);
    }
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  });
  return groups;
}

function renderSources(box, sources) {
  box.innerHTML = "<div class='sources-title'>📎 引用来源</div>";
  for (const [fi, items] of buildFileGroups(sources)) {
    const first = items[0];
    const path = first.retrieved_by ? " · " + first.retrieved_by.join("+") : "";
    const chunks = items.map((s) => s.chunk_index).filter((x) => x != null);
    const chunkInfo = chunks.length ? ` · 片段 ${chunks.join(",")}` : "";
    const rrf = Math.max(...items.map((s) => s.rrf_score).filter((x) => x != null), -Infinity);
    const rerank = Math.max(...items.map((s) => s.rerank_score).filter((x) => x != null), -Infinity);
    let badges = "";
    if (Number.isFinite(rrf)) badges += ` <b class="score" title="RRF 融合分数">rrf ${rrf}</b>`;
    if (Number.isFinite(rerank)) badges += ` <b class="score" title="重排分数">rerank ${rerank}</b>`;
    const row = document.createElement("div");
    row.className = "src";
    row.innerHTML = `<span class="idx">[${fi}]</span><span class="file">${esc(first.source)}${esc(chunkInfo)}${path}${badges}</span>`;
    box.appendChild(row);
  }
}

// 健壮 SSE 解析:兼容 "data:" / "data: "、多行、坏事件跳过、残块缓冲。
// onEvent(null) 表示收到 [DONE]。
function splitSSE(buffer, onEvent) {
  let idx;
  while ((idx = buffer.indexOf("\n\n")) >= 0) {
    const block = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 2);
    for (const line of block.split("\n")) {
      if (!line.startsWith("data")) continue; // 忽略 event/id/retry/注释行
      const payload = line.replace(/^data\s*:\s?/, "").trim();
      if (payload === "[DONE]") { onEvent(null); continue; }
      try { onEvent(JSON.parse(payload)); } catch { /* 跳过坏事件,不中断流 */ }
    }
  }
  return buffer;
}

async function send() {
  const question = inputEl.value.trim();
  if (!question || sendBtn.disabled) return;
  await sendQuestion(question);
}

async function sendQuestion(question) {
  if (!currentSessionId) { toast("请先创建会话", true); return; }
  inputEl.value = "";
  inputEl.style.height = "auto";
  showThread();
  addMessage("user", question);
  sendBtn.disabled = true;

  const { content, sources, copyBtn } = buildAssistantMessage();
  const cursor = document.createElement("span");
  cursor.className = "stream-cursor";
  content.appendChild(cursor);
  let full = "";
  let finished = false;

  const removeCursor = () => { if (cursor.isConnected) cursor.remove(); };
  const paint = (text) => { content.textContent = text; content.appendChild(cursor); };
  const finish = (answer, srcs) => {
    if (finished) return;
    finished = true;
    full = answer;
    content.textContent = full;
    removeCursor();
    if (srcs && srcs.length) {
      renderSources(sources, srcs);
      sources.hidden = false;
      renderCitationMarkers(content, srcs);
    }
    copyBtn.onclick = () => copyMessage(full, copyBtn);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  };
  const scroll = () => { messagesEl.scrollTop = messagesEl.scrollHeight; };

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ question, session_id: currentSessionId }),
    });
    // 流式走直连 fetch,绕过 api() 的 401 拦截,这里必须自己处理
    if (res.status === 401) { clearAuth(); showLogin(); throw new Error("登录已过期,请重新登录"); }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || ("HTTP " + res.status)); // 409/429/403 的 detail 直接展示
    }
    if (!res.body) throw new Error("空响应");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = splitSSE(buffer, (ev) => {
        if (ev === null) { removeCursor(); }
        else if (ev.type === "token") { full += ev.text; paint(full); scroll(); }
        else if (ev.type === "answer") { finish(ev.answer, ev.sources); }
        else if (ev.type === "done") { finish(ev.answer, ev.sources); }
        else if (ev.type === "error") { throw new Error(ev.message); }
      });
      scroll();
    }
    // 会话标题/时间可能变化(首条消息定为标题),刷新列表
    refreshSessionList();
  } catch (err) {
    content.textContent = "⚠️ 出错了：" + err.message;
    removeCursor();
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

async function refreshSessionList() {
  try {
    sessions = await api("/api/sessions");
    renderSessions();
  } catch { /* 列表刷新失败不阻断对话 */ }
}

// ───────── 引用悬浮气泡(RAGFlow [n] popover)────────────────────
// [n] 现在对应「文件编号」:同一文件的所有片段合并为一个编号。
function renderCitationMarkers(contentEl, sources) {
  if (!sources || !sources.length) return;
  const groups = buildFileGroups(sources);
  const text = contentEl.textContent;
  const re = /\[(\d{1,3})\]/g;
  const frag = document.createDocumentFragment();
  let m, last = 0, found = false;
  while ((m = re.exec(text))) {
    const idx = parseInt(m[1], 10);
    const items = groups.get(idx);
    if (!items) continue;
    found = true;
    frag.appendChild(document.createTextNode(text.slice(last, m.index)));
    const span = document.createElement("span");
    span.className = "cite";
    span.dataset.idx = idx;
    span.textContent = m[0];
    span.title = items[0].source;
    span.addEventListener("mouseenter", () => showCitation(span, items, idx));
    span.addEventListener("mouseleave", scheduleHideCitation);
    frag.appendChild(span);
    last = m.index + m[0].length;
  }
  if (!found) return;
  frag.appendChild(document.createTextNode(text.slice(last)));
  contentEl.textContent = "";
  contentEl.appendChild(frag);
}

function showCitation(span, group, fileIdx) {
  cancelHideCitation();
  const pop = $("citationPopover");
  const first = group[0];
  const score =
    first.rerank_score != null ? `· rerank ${first.rerank_score}`
    : first.rrf_score != null ? `· rrf ${first.rrf_score}`
    : "";
  const count = group.length > 1 ? ` · ${group.length} 段` : "";
  const excerpt = first.text
    ? `<div class="pop-excerpt">${esc(first.text.slice(0, 120))}${first.text.length > 120 ? "…" : ""}</div>`
    : "";
  pop.innerHTML = `<div class="pop-file">[${fileIdx}] ${esc(first.source)}<span class="pop-score">${esc(score + count)}</span></div>${excerpt}`;
  pop.hidden = false;
  const rect = span.getBoundingClientRect();
  const pr = pop.getBoundingClientRect();
  let top = rect.top - pr.height - 8;
  let left = rect.left;
  if (top < 8) top = rect.bottom + 8;
  if (left + pr.width > window.innerWidth - 8) left = Math.max(8, window.innerWidth - pr.width - 8);
  pop.style.top = top + "px";
  pop.style.left = left + "px";
  pop.onmouseenter = cancelHideCitation;
  pop.onmouseleave = scheduleHideCitation;
}

function scheduleHideCitation() {
  clearTimeout(citationHideTimer);
  citationHideTimer = setTimeout(() => { $("citationPopover").hidden = true; }, 180);
}
function cancelHideCitation() { clearTimeout(citationHideTimer); }

// ───────── 复制 ─────────────────────────────────────────────────
function copyMessage(text, btn) {
  const fallback = () => {
    // 非安全上下文或异步剪贴板被拒时,回退到 selection + execCommand
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    document.body.removeChild(ta);
    if (ok) toast("已复制 ✅"); else toast("复制失败", true);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(() => toast("已复制 ✅"), fallback);
  } else {
    fallback();
  }
}

// ───────── knowledge ────────────────────────────────────────────
const ALLOWED_EXT = ["pdf", "docx", "html", "htm", "md", "txt"];

async function loadDocs() {
  try {
    const data = await api("/api/documents");
    renderDocs(data.documents || []);
  } catch (e) {
    $("docList").innerHTML = '<div class="empty">' + esc(e.message) + "</div>";
  }
}

// 从任务列表派生 doc_id → status;摄取中/失败的文档在列表里标出来
function buildStatusMap(tasks) {
  const m = new Map();
  (tasks || []).forEach((t) => {
    if (t.doc_id) m.set(t.doc_id, t.status);
    else if ((t.status === "pending" || t.status === "running") && t.filename)
      m.set("__f:" + t.filename, t.status); // 未定 doc_id 的进行中任务,按文件名匹配
  });
  return m;
}

function statusBadge(status) {
  const cls = { done: "ready", running: "parsing", pending: "parsing", failed: "failed" }[status] || "ready";
  const labels = { ready: "已就绪", parsing: "解析中", failed: "解析失败" };
  return `<span class="badge ${cls}">${labels[cls]}</span>`;
}

async function renderDocs(docs) {
  const box = $("docList");
  $("kbEmptyState").hidden = docs.length > 0;
  const totalChunks = docs.reduce((s, d) => s + (d.num_chunks || 0), 0);
  $("kbSub").textContent = `${docs.length} 个文档 · ${totalChunks} 个片段`;
  box.innerHTML = "";
  if (!docs.length) return;

  // 拉一次任务列表,合并状态徽章
  let statusByDoc = new Map();
  try { statusByDoc = buildStatusMap((await api("/api/documents/tasks")).tasks); }
  catch { /* 拿不到任务列表不阻断 */ }

  // 按上传者分组:语料库文档 / 某用户上传
  const groups = new Map();
  docs.forEach((d) => {
    const key = d.owner ? "@" + d.owner : "#corpus";
    if (!groups.has(key)) groups.set(key, { label: d.owner ? "@ " + d.owner : "📚 知识库语料", docs: [] });
    groups.get(key).docs.push(d);
  });

  const table = document.createElement("table");
  table.className = "doc-table";
  table.innerHTML = `<thead><tr>
    <th>文件名</th><th>格式</th><th class="num">片段数</th><th>状态</th><th class="num">操作</th>
  </tr></thead>`;
  const tbody = document.createElement("tbody");

  groups.forEach((g) => {
    const gr = document.createElement("tr");
    gr.className = "doc-group";
    gr.innerHTML = `<td colspan="5">${esc(g.label)}</td>`;
    tbody.appendChild(gr);

    g.docs.forEach((d) => {
      const tr = document.createElement("tr");
      const st = statusByDoc.get(d.doc_id) || statusByDoc.get("__f:" + d.filename) || "ready";
      const canDelete = currentUser && (currentUser.role === "admin" || d.uploaded_by === currentUser.id);
      tr.innerHTML = `
        <td class="doc-name" title="点击预览 ${esc(d.filename)}">${esc(d.filename)}</td>
        <td><span class="fmt">${esc(d.fmt)}</span></td>
        <td class="num">${d.num_chunks}</td>
        <td>${statusBadge(st)}</td>
        <td class="num actions">
          <button class="pv" title="预览">👁</button>
          ${canDelete ? '<button class="rm" title="删除">🗑</button>' : ""}
        </td>`;
      tr.querySelector(".doc-name").onclick = () => previewDoc(d.doc_id);
      tr.querySelector(".pv").onclick = () => previewDoc(d.doc_id);
      const rm = tr.querySelector(".rm");
      if (rm) rm.onclick = async () => {
        if (!(await confirmDialog(`删除文档「${d.filename}」？该操作会同步重建检索索引。`))) return;
        try { await api(`/api/documents/${d.doc_id}`, { method: "DELETE" }); toast("已删除"); loadDocs(); }
        catch (e) { toast(e.message, true); }
      };
      tbody.appendChild(tr);
    });
  });

  table.appendChild(tbody);
  box.appendChild(table);
}

// 文档预览(读取 data/texts 的前几个 chunk,不依赖原始文件)
async function previewDoc(docId) {
  try {
    const data = await api(`/api/documents/${docId}/preview`);
    $("previewTitle").textContent = data.filename;
    $("previewBody").innerHTML = "";
    data.chunks.forEach((c) => {
      const p = document.createElement("pre");
      p.className = "preview-chunk";
      p.textContent = `[片段 ${c.index + 1}]\n${c.text}`;
      $("previewBody").appendChild(p);
    });
    $("previewModal").hidden = false;
  } catch (e) { toast(e.message, true); }
}

// 上传:批量 → 逐个发请求 → 后台摄取 → 轮询任务进度
async function uploadFiles(files) {
  let ok = 0;
  for (const f of files) {
    const ext = (f.name.split(".").pop() || "").toLowerCase();
    if (!ALLOWED_EXT.includes(ext)) { toast(`不支持的文件类型: ${f.name}`, true); continue; }
    const fd = new FormData();
    fd.append("file", f);
    try {
      await api("/api/documents", { method: "POST", body: fd });
      ok++;
    } catch (err) { toast(`上传失败 ${f.name}: ${err.message}`, true); }
  }
  if (ok) { toast(`${ok} 个文件已提交摄取,后台处理中…`); pollTasks(); }
  else loadDocs();
}

function setupDropzone() {
  const dz = $("dropzone");
  let dragDepth = 0;
  dz.addEventListener("click", () => $("uploadInput").click());
  dz.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; dz.classList.add("dragover"); });
  dz.addEventListener("dragover", (e) => e.preventDefault());
  dz.addEventListener("dragleave", (e) => {
    e.preventDefault();
    dragDepth--;
    if (dragDepth <= 0) { dragDepth = 0; dz.classList.remove("dragover"); }
  });
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    dz.classList.remove("dragover");
    const files = [...(e.dataTransfer?.files || [])];
    if (files.length) uploadFiles(files);
  });
}

async function pollTasks() {
  if (taskPolling) return;
  taskPolling = true;
  let busy = true;
  while (busy) {
    let tasks = [];
    try {
      tasks = (await api("/api/documents/tasks")).tasks;
    } catch { break; }
    renderTasks(tasks);
    busy = tasks.some((t) => t.status === "pending" || t.status === "running");
    if (busy) await new Promise((r) => setTimeout(r, 1500));
  }
  taskPolling = false;
  loadDocs(); // 摄取完成后刷新文档列表(状态徽章/统计)
  toast("摄取完成 ✅");
}

function renderTasks(tasks) {
  const panel = $("taskList");
  const list = tasks.slice(0, 5);
  panel.hidden = list.length === 0;
  panel.innerHTML = "";
  if (!list.length) return;
  const title = document.createElement("div");
  title.className = "task-title";
  title.textContent = "⏳ 摄取进度";
  panel.appendChild(title);
  list.forEach((t) => {
    const item = document.createElement("div");
    item.className = "task-item";
    const label = t.status === "failed" ? (t.error || "失败") : t.filename;
    item.innerHTML = `<span class="st ${esc(t.status)}">${esc(t.status)}</span><span class="tf" title="${esc(label)}">${esc(label)}</span>`;
    panel.appendChild(item);
  });
}

// ───────── settings(仅管理员)──────────────────────────────────
const EMB_LABELS = { api: "阿里百炼 (DashScope)", local: "本地 BGE (离线)" };
const RERANK_LABELS = { api: "阿里百炼 (DashScope)", local: "本地 BGE (离线)" };

function fillSelect(sel, labels) {
  sel.innerHTML = "";
  Object.entries(labels).forEach(([v, label]) => {
    const o = document.createElement("option");
    o.value = v; o.textContent = label;
    sel.appendChild(o);
  });
}

function fillDatalist(id, models) {
  const dl = $(id);
  dl.innerHTML = "";
  (models || []).forEach((m) => {
    const o = document.createElement("option");
    o.value = m;
    dl.appendChild(o);
  });
}

function setKeyField(prefix, sec) {
  const input = $(prefix + "ApiKey");
  input.value = "";
  input.placeholder = sec.has_key ? ("已配置 " + sec.api_key + " · 留空保持不变") : "未配置 API Key";
}

async function loadSettingsForm() {
  try { curSettings = await api("/api/settings"); }
  catch (e) { toast("设置加载失败：" + e.message, true); return; }
  const s = curSettings;

  fillSelect($("llmProvider"), Object.fromEntries(s.options.llm_providers.map((p) => [p.id, p.label])));
  $("llmProvider").value = s.llm.provider;
  $("llmModel").value = s.llm.model;
  $("llmBaseUrl").value = s.llm.base_url;
  $("llmTemperature").value = s.llm.temperature;
  setKeyField("llm", s.llm);
  fillDatalist("llmModels", (s.options.llm_providers.find((p) => p.id === s.llm.provider) || {}).models);
  onLlmProviderChange();

  fillSelect($("embProvider"), EMB_LABELS);
  $("embProvider").value = s.embedding.provider;
  $("embModel").value = s.embedding.model;
  $("embBaseUrl").value = s.embedding.base_url;
  setKeyField("emb", s.embedding);
  fillDatalist("embModels", s.options.embedding_models[s.embedding.provider] || []);
  onEmbProviderChange();

  $("rerankEnabled").checked = s.rerank.enabled;
  fillSelect($("rerankProvider"), RERANK_LABELS);
  $("rerankProvider").value = s.rerank.provider;
  $("rerankModel").value = s.rerank.model;
  $("rerankBaseUrl").value = s.rerank.base_url;
  setKeyField("rerank", s.rerank);
  fillDatalist("rerankModels", s.options.rerank_models[s.rerank.provider] || []);
  onRerankProviderChange();

  renderReindexBanner(s);
}

function onLlmProviderChange() {
  const p = (curSettings?.options.llm_providers || []).find((x) => x.id === $("llmProvider").value);
  if (p) {
    if (p.base_url) $("llmBaseUrl").value = p.base_url;
    fillDatalist("llmModels", p.models);
  }
}

function onEmbProviderChange() {
  const prov = $("embProvider").value;
  fillDatalist("embModels", (curSettings?.options.embedding_models[prov] || []));
  const local = prov === "local";
  $("embBaseUrl").closest("label").hidden = local;
  $("embApiKey").closest("label").hidden = local;
}

function onRerankProviderChange() {
  const prov = $("rerankProvider").value;
  fillDatalist("rerankModels", (curSettings?.options.rerank_models[prov] || []));
  const local = prov === "local";
  $("rerankBaseUrl").closest("label").hidden = local;
  $("rerankApiKey").closest("label").hidden = local;
}

function collectLLM() {
  const p = {
    provider: $("llmProvider").value,
    base_url: $("llmBaseUrl").value.trim(),
    model: $("llmModel").value.trim(),
    temperature: parseFloat($("llmTemperature").value) || 0.3,
  };
  const key = $("llmApiKey").value.trim();
  if (key) p.api_key = key;
  return p;
}
function collectEmb() {
  const p = { provider: $("embProvider").value, base_url: $("embBaseUrl").value.trim(), model: $("embModel").value.trim() };
  const key = $("embApiKey").value.trim();
  if (key) p.api_key = key;
  return p;
}
function collectRerank() {
  const p = { enabled: $("rerankEnabled").checked, provider: $("rerankProvider").value, base_url: $("rerankBaseUrl").value.trim(), model: $("rerankModel").value.trim() };
  const key = $("rerankApiKey").value.trim();
  if (key) p.api_key = key;
  return p;
}

async function saveSettings() {
  const body = { llm: collectLLM(), embedding: collectEmb(), rerank: collectRerank() };
  $("settingsSave").disabled = true;
  try {
    curSettings = await api("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    await loadSettingsForm();
    toast("配置已保存 ✅");
  } catch (e) { toast("保存失败：" + e.message, true); }
  finally { $("settingsSave").disabled = false; }
}

async function testSection(section) {
  const el = $(section + "TestResult");
  el.textContent = "测试中…";
  el.className = "test-result";
  const payload = {};
  if (section === "llm") payload.llm = collectLLM();
  if (section === "embedding") payload.embedding = collectEmb();
  if (section === "rerank") payload.rerank = collectRerank();
  try {
    const res = await api("/api/settings/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const r = res[section];
    const mark = r.ok === null ? "⏸ " : r.ok ? "✅ " : "❌ ";
    el.textContent = mark + (r.message || "未知结果");
    el.className = "test-result " + (r.ok ? "ok" : r.ok === null ? "" : "bad");
  } catch (e) {
    el.textContent = "❌ 测试失败：" + e.message;
    el.className = "test-result bad";
  }
}

function renderReindexBanner(s) {
  const banner = $("reindexBanner");
  if (s.rebuilding) {
    banner.hidden = false;
    $("rebuildProgressWrap").hidden = false;
    $("rebuildProgressBar").style.width = (s.progress || 0) + "%";
    $("rebuildProgressText").textContent = (s.progress || 0) + "%";
    $("rebuildBtn").disabled = true;
    $("rebuildState").textContent = "正在重建…";
    if (!rebuildPolling) { rebuildPolling = true; pollRebuild(); }
  } else if (s.needs_reindex) {
    banner.hidden = false;
    $("rebuildProgressWrap").hidden = true;
    $("rebuildBtn").disabled = false;
    $("rebuildState").textContent = s.last_rebuild_error ? ("上次失败：" + s.last_rebuild_error) : "";
  } else {
    banner.hidden = true;
  }
}

async function rebuildIndex() {
  if (!(await confirmDialog("将用当前嵌入模型重新编码全部文档并重建索引。确认继续？"))) return;
  $("rebuildBtn").disabled = true;
  try {
    await api("/api/settings/reindex", { method: "POST" });
    renderReindexBanner(curSettings);
  } catch (e) {
    toast("重建启动失败：" + e.message, true);
    $("rebuildBtn").disabled = false;
  }
}

async function pollRebuild() {
  if (!rebuildPolling) return;
  try { curSettings = await api("/api/settings"); }
  catch { setTimeout(pollRebuild, 1200); return; }
  renderReindexBanner(curSettings);
  if (curSettings.rebuilding) setTimeout(pollRebuild, 600);
  else {
    rebuildPolling = false;
    if (curSettings.last_rebuild_error) toast("重建失败：" + curSettings.last_rebuild_error, true);
    else toast("索引重建完成 ✅");
    await loadSettingsForm();
  }
}

// ───────── confirm(替代原生 confirm)────────────────────────────
function confirmDialog(message) {
  return new Promise((resolve) => {
    const okBtn = $("confirmOk"), cancelBtn = $("confirmCancel");
    const modal = $("confirmModal");
    $("confirmText").textContent = message;
    modal.hidden = false;
    const cleanup = () => {
      modal.hidden = true;
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      modal.removeEventListener("click", onMask);
      document.removeEventListener("keydown", onKey);
    };
    const onOk = () => { cleanup(); resolve(true); };
    const onCancel = () => { cleanup(); resolve(false); };
    const onMask = (e) => { if (e.target === modal) { cleanup(); resolve(false); } };
    const onKey = (e) => { if (e.key === "Escape") { cleanup(); resolve(false); } };
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    modal.addEventListener("click", onMask);
    document.addEventListener("keydown", onKey);
  });
}

// ───────── boot ─────────────────────────────────────────────────
function bindEvents() {
  // rail
  $("railChat").onclick = () => switchMainView("chat");
  $("railKb").onclick = () => switchMainView("kb");
  $("railSettings").onclick = () => { $("settingsModal").hidden = false; loadSettingsForm(); };
  $("railLogout").onclick = logout;

  // auth
  $("authSubmit").onclick = submitAuth;
  $("authToggle").onclick = () => {
    authMode = authMode === "login" ? "register" : "login";
    $("authSubmit").textContent = authMode === "login" ? "登 录" : "注 册";
    $("authToggle").textContent = authMode === "login" ? "没有账号？注册一个" : "已有账号？去登录";
  };
  $("authPass").addEventListener("keydown", (e) => { if (e.key === "Enter") submitAuth(); });

  // chat
  $("newSessionBtn").onclick = newSession;
  $("chatListToggle").onclick = () => $("chatSidebar").classList.toggle("open");
  $("send").onclick = send;
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  inputEl.addEventListener("input", () => {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
  });

  // knowledge
  $("uploadBtn").onclick = () => $("uploadInput").click();
  $("uploadInput").onchange = (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    if (files.length) uploadFiles(files);
  };
  setupDropzone();

  // settings modal
  $("settingsClose").onclick = () => $("settingsModal").hidden = true;
  $("settingsCancel").onclick = () => $("settingsModal").hidden = true;
  $("settingsModal").addEventListener("click", (e) => { if (e.target === $("settingsModal")) $("settingsModal").hidden = true; });
  $("settingsSave").onclick = saveSettings;
  $("rebuildBtn").onclick = rebuildIndex;
  document.querySelectorAll("[data-test]").forEach((btn) => {
    btn.onclick = () => testSection(btn.dataset.test);
  });
  $("llmProvider").onchange = onLlmProviderChange;
  $("embProvider").onchange = onEmbProviderChange;
  $("rerankProvider").onchange = onRerankProviderChange;

  // preview modal
  $("previewClose").onclick = () => $("previewModal").hidden = true;
  $("previewModal").addEventListener("click", (e) => { if (e.target === $("previewModal")) $("previewModal").hidden = true; });

  // Esc 关弹窗(设置 / 预览)
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("settingsModal").hidden) $("settingsModal").hidden = true;
    else if (!$("previewModal").hidden) $("previewModal").hidden = true;
  });
}

bindEvents();
init();
