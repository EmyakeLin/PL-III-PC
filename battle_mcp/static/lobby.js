const feedback = document.querySelector('#feedback');
const storageKey = 'pl3-lobby-rooms';
let opened = [];
try { opened = JSON.parse(sessionStorage.getItem(storageKey)) || []; } catch {}

function element(tag, text) {
  const item = document.createElement(tag);
  item.textContent = text;
  return item;
}

function remember() {
  try { sessionStorage.setItem(storageKey, JSON.stringify(opened)); } catch {}
  showRooms();
}

function showRooms() {
  const list = document.querySelector('#rooms');
  list.replaceChildren();
  document.querySelector('#recent').hidden = !opened.length;
  for (const room of opened) {
    const row = document.createElement('li');
    const link = element('a', room.label);
    link.href = room.play_url;
    const close = element('button', '关闭房间');
    close.addEventListener('click', async () => {
      if (!window.confirm('关闭此房间并结束其中的对局？')) return;
      close.disabled = true;
      try {
        const token = new URLSearchParams(link.hash.slice(1)).get('token');
        const res = await fetch('/api/rooms/' + room.id, {
          method: 'DELETE', headers: { Authorization: 'Bearer ' + token },
        });
        if (!res.ok && res.status !== 404) throw new Error((await res.json()).error);
        opened = opened.filter(item => item.id !== room.id);
        remember();
      } catch (error) {
        feedback.textContent = error.message;
        close.disabled = false;
      }
    });
    row.append(link, close);
    list.append(row);
  }
}

function modePanel(mode) {
  const panel = document.createElement('section');
  panel.append(element('h2', mode.name));
  if (!mode.available) {
    const status = element('span', '暂未开放');
    status.className = 'muted';
    panel.append(status);
    return panel;
  }
  const form = document.createElement('form');
  const label = element('label', mode.id === 'regular' ? '对战方式' : '挑战对手');
  const select = document.createElement('select');
  for (const choice of mode.variants) select.add(new Option(choice.name, choice.id));
  const create = element('button', '创建房间');
  create.className = 'primary';
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (create.disabled) return;
    create.disabled = select.disabled = true;
    feedback.textContent = '正在创建房间…';
    try {
      const res = await fetch('/api/rooms', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: mode.id, variant: select.value }),
      });
      const room = await res.json();
      if (!res.ok) throw new Error(room.error);
      opened.unshift({ ...room, label: mode.name + ' · ' + select.selectedOptions[0].text });
      remember();
      feedback.textContent = '';
      location.assign(room.play_url);
    } catch (error) {
      feedback.textContent = error.message;
    } finally {
      create.disabled = select.disabled = false;
    }
  });
  label.append(select);
  form.append(label, create);
  panel.append(form);
  return panel;
}

showRooms();
try {
  const response = await fetch('/api/modes');
  if (!response.ok) throw new Error('无法读取对战模式，请刷新大厅。');
  const modes = await response.json();
  document.querySelector('#modes').append(...modes.map(modePanel));
  feedback.textContent = '';
} catch (error) {
  feedback.textContent = error.message;
}
