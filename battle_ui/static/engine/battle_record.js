export function bindBattleRecord(transport) {
  const template = document.getElementById('battle-record-template');
  const dialog = template.content.firstElementChild.cloneNode(true);
  const field = dialog.querySelector('textarea');
  const copy = dialog.querySelector('#copy-battle-record');
  const status = dialog.querySelector('[role="status"]');
  let pendingRecord = null;

  // Keep native text selection, scrolling, and Escape inside the dialog.
  for (const type of ['keydown', 'wheel', 'contextmenu']) {
    dialog.addEventListener(type, event => event.stopPropagation());
  }
  dialog.addEventListener('close', () => {
    if (!dialog.open) {
      dialog.remove();
      pendingRecord = null;
    }
  });

  copy.addEventListener('click', async () => {
    const record = pendingRecord;
    copy.disabled = true;
    try {
      await navigator.clipboard.writeText(field.value);
      if (dialog.open && pendingRecord === record) status.textContent = '已复制全文。';
    } catch {
      if (dialog.open && pendingRecord === record) {
        field.focus();
        field.select();
        status.textContent = '已选中全文，可用系统复制。';
      }
    } finally {
      if (dialog.open && pendingRecord === record) copy.disabled = false;
    }
  });

  return async () => {
    if (dialog.open) return;
    field.value = '';
    copy.disabled = true;
    status.textContent = '正在读取战报…';
    document.body.append(dialog);
    dialog.showModal();

    const record = transport.fetchBattleRecord();
    pendingRecord = record;
    try {
      const text = await record;
      if (!dialog.open || pendingRecord !== record) return;
      field.value = text;
      field.scrollTop = 0;
      copy.disabled = false;
      status.textContent = '';
    } catch {
      if (dialog.open && pendingRecord === record) {
        status.textContent = '战报读取失败，请关闭后重试。';
      }
    }
  };
}
