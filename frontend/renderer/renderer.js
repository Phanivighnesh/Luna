const API = 'http://localhost:8000';
let conversationId = 'conv_' + Date.now();

// ---------- View switching ----------
function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}
function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  const btn = document.querySelector(`.nav-btn[data-tab="${name}"]`);
  if (btn) btn.classList.add('active');
  if (name === 'memory') loadMemory();
  if (name === 'privacy') loadActivity();
  if (name === 'schedule') loadSchedule();
}

// ---------- Local settings (backed by backend /memory) ----------
async function getMemoryValue(key, fallback = null) {
  const all = await (await fetch(`${API}/memory`)).json();
  const found = all.find(m => m.key === key);
  return found ? found.value : fallback;
}
async function setMemoryValue(key, value) {
  await fetch(`${API}/memory/${encodeURIComponent(key)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value: String(value) }),
  });
}

function applyTheme(theme) {
  document.body.classList.toggle('theme-light', theme === 'light');
}

// ---------- Backend connectivity check ----------
async function checkBackend() {
  const banner = document.getElementById('backend-error-banner');
  try {
    const res = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) throw new Error('Backend responded with error');
    banner.classList.add('hidden');
    return true;
  } catch (err) {
    banner.classList.remove('hidden');
    return false;
  }
}
document.getElementById('retry-connection-btn').addEventListener('click', async () => {
  const ok = await checkBackend();
  if (ok) initApp();
});

// ---------- Onboarding ----------
async function initApp() {
  const backendUp = await checkBackend();
  if (!backendUp) return; // banner is already visible; don't proceed with broken fetches

  try {
    const username = await getMemoryValue('user_name');
    if (username) {
      const assistantName = await getMemoryValue('assistant_name', 'Luna');
      const theme = await getMemoryValue('theme', 'dark');
      document.getElementById('brand-name').innerText = assistantName;
      applyTheme(theme);
      showView('view-app');
    } else {
      showView('view-onboarding');
    }
  } catch (err) {
    document.getElementById('backend-error-banner').classList.remove('hidden');
  }
}

document.getElementById('ob-continue').addEventListener('click', async () => {
  const username = document.getElementById('ob-username').value.trim() || 'Friend';
  const assistantName = document.getElementById('ob-assistantname').value.trim() || 'Luna';
  const theme = document.getElementById('ob-theme').value;

  try {
    await setMemoryValue('user_name', username);
    await setMemoryValue('assistant_name', assistantName);
    await setMemoryValue('theme', theme);

    document.getElementById('brand-name').innerText = assistantName;
    applyTheme(theme);
    showView('view-app');
    addMessage('assistant', `Hi ${username}, I'm ${assistantName}. Ask me anything, or try something like "open Notepad" or "find my resume".`);
  } catch (err) {
    document.getElementById('backend-error-banner').classList.remove('hidden');
  }
});

// ---------- Nav ----------
document.querySelectorAll('.nav-btn[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => showTab(btn.dataset.tab));
});
document.getElementById('new-chat-btn').addEventListener('click', () => {
  conversationId = 'conv_' + Date.now();
  document.getElementById('messages').innerHTML = '';
  showTab('chat');
});

// ---------- Chat ----------
function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.innerText = text;
  document.getElementById('messages').appendChild(div);
  document.getElementById('messages').scrollTop = 999999;
  return div;
}

async function sendMessage() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMessage('user', text);

  const res = await fetch(`${API}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text, conversation_id: conversationId }),
  });

  const contentType = res.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    const data = await res.json();
    if (data.type === 'action_pending') {
      confirmAction(data);
    } else if (data.type === 'action_result') {
      addMessage('assistant', data.result.message || 'No response text came back — check the backend terminal for errors.');
    }
    return;
  }

  // streaming plain-text response
  const assistantDiv = addMessage('assistant', '');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    assistantDiv.innerText += decoder.decode(value);
    document.getElementById('messages').scrollTop = 999999;
  }
}

document.getElementById('send-btn').addEventListener('click', sendMessage);
document.getElementById('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendMessage();
});

// ---------- Permission modal ----------
function confirmAction(pending) {
  const modal = document.getElementById('confirm-modal');
  document.getElementById('confirm-description').innerText = pending.description;
  modal.classList.remove('hidden');

  const allowBtn = document.getElementById('confirm-allow');
  const denyBtn = document.getElementById('confirm-deny');

  const cleanup = () => {
    modal.classList.add('hidden');
    allowBtn.onclick = null;
    denyBtn.onclick = null;
  };

  allowBtn.onclick = async () => {
    cleanup();
    addMessage('system', `Allowed: ${pending.description}`);
    try {
      const res = await fetch(`${API}/task/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: pending.action, argument: pending.argument, extra: pending.extra || null }),
      });
      const result = await res.json();
      addMessage('assistant', result.message || result.detail || 'No response text came back — check the backend terminal for errors.');
    } catch (err) {
      addMessage('system', `Couldn't reach the backend: ${err.message}`);
    }
  };

  denyBtn.onclick = () => {
    cleanup();
    addMessage('system', `Denied: ${pending.description}`);
  };
}

// ---------- Schedule tab ----------
async function loadSchedule() {
  const list = document.getElementById('schedule-list');
  list.innerHTML = 'Loading...';
  const items = await (await fetch(`${API}/schedule`)).json();
  list.innerHTML = '';
  if (items.length === 0) {
    list.innerHTML = '<p class="hint">Nothing scheduled yet. Add something above, or just tell Luna "schedule X at 5pm" in chat.</p>';
    return;
  }
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'memory-item';
    const when = new Date(item.due_at).toLocaleString();
    row.innerHTML = `<span><b>${item.title}</b> — ${when}</span>`;
    const doneBtn = document.createElement('button');
    doneBtn.innerText = 'Mark Done';
    doneBtn.onclick = async () => {
      await fetch(`${API}/schedule/${item.id}/done`, { method: 'POST' });
      loadSchedule();
    };
    row.appendChild(doneBtn);
    list.appendChild(row);
  });
}

document.getElementById('sched-add-btn').addEventListener('click', async () => {
  const title = document.getElementById('sched-title').value.trim();
  const time = document.getElementById('sched-time').value.trim();
  if (!title || !time) { alert('Enter both a task and a time.'); return; }

  // Reuses the same confirm flow as chat-driven scheduling.
  const res = await fetch(`${API}/task/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'schedule_task', argument: title, extra: time }),
  });
  const result = await res.json();
  alert(result.message);
  document.getElementById('sched-title').value = '';
  document.getElementById('sched-time').value = '';
  loadSchedule();
});

// ---------- Memory dashboard ----------
async function loadMemory() {
  const list = document.getElementById('memory-list');
  list.innerHTML = 'Loading...';
  const items = await (await fetch(`${API}/memory`)).json();
  list.innerHTML = '';
  if (items.length === 0) {
    list.innerHTML = '<p class="hint">Nothing stored yet.</p>';
    return;
  }
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'memory-item';
    row.innerHTML = `<span><b>${item.key}</b>: ${item.value}</span>`;
    const delBtn = document.createElement('button');
    delBtn.innerText = 'Remove';
    delBtn.onclick = async () => {
      await fetch(`${API}/memory/${encodeURIComponent(item.key)}`, { method: 'DELETE' });
      loadMemory();
    };
    row.appendChild(delBtn);
    list.appendChild(row);
  });
}

// ---------- Privacy dashboard ----------
async function loadActivity() {
  const list = document.getElementById('activity-list');
  list.innerHTML = 'Loading...';
  const items = await (await fetch(`${API}/activity`)).json();
  list.innerHTML = '';
  if (items.length === 0) {
    list.innerHTML = '<p class="hint">No activity yet.</p>';
    return;
  }
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'activity-item';
    row.innerHTML = `<span>${item.ts} — <b>${item.action}</b> ${item.detail || ''}</span>`;
    list.appendChild(row);
  });
}

document.getElementById('delete-all-btn').addEventListener('click', async () => {
  if (!confirm('This deletes all memory, conversations, and activity logs. Continue?')) return;
  await fetch(`${API}/memory`, { method: 'DELETE' });
  loadMemory();
  loadActivity();
  alert('All data deleted.');
});

// ---------- Settings ----------
document.getElementById('test-email-btn').addEventListener('click', async () => {
  const btn = document.getElementById('test-email-btn');
  btn.disabled = true;
  btn.innerText = 'Sending...';
  try {
    const res = await fetch(`${API}/settings/test-email`, { method: 'POST' });
    const result = await res.json();
    alert(result.message);
  } catch (err) {
    alert(`Couldn't reach the backend: ${err.message}`);
  }
  btn.disabled = false;
  btn.innerText = 'Send Test Email';
});

document.getElementById('settings-save-btn').addEventListener('click', async () => {
  const assistantName = document.getElementById('settings-assistantname').value.trim() || 'Luna';
  const theme = document.getElementById('settings-theme').value;
  const length = document.getElementById('settings-length').value;
  const smtpEmail = document.getElementById('settings-smtp-email').value.trim();
  const smtpPassword = document.getElementById('settings-smtp-password').value.trim();
  const notifyEmail = document.getElementById('settings-notify-email').value.trim();

  await setMemoryValue('assistant_name', assistantName);
  await setMemoryValue('theme', theme);
  await setMemoryValue('response_length', length);
  if (smtpEmail) await setMemoryValue('smtp_email', smtpEmail);
  if (smtpPassword) await setMemoryValue('smtp_app_password', smtpPassword);
  if (notifyEmail) await setMemoryValue('notify_email', notifyEmail);

  document.getElementById('brand-name').innerText = assistantName;
  applyTheme(theme);
  alert('Settings saved.');
});

async function loadSettingsTab() {
  document.getElementById('settings-assistantname').value = await getMemoryValue('assistant_name', 'Luna');
  document.getElementById('settings-theme').value = await getMemoryValue('theme', 'dark');
  document.getElementById('settings-length').value = await getMemoryValue('response_length', 'normal');
  document.getElementById('settings-smtp-email').value = await getMemoryValue('smtp_email', '');
  document.getElementById('settings-notify-email').value = await getMemoryValue('notify_email', '');
  // App password intentionally left blank on load — don't echo secrets back into a visible field.
}
document.querySelector('.nav-btn[data-tab="settings"]').addEventListener('click', loadSettingsTab);

// ---------- Boot ----------
initApp();
