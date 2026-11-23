// 추가/수정 창(dialog) 공통 동작. 다른 화면에서도 같은 방식으로 재사용합니다.
(function () {
  function camel(name) {
    return name.replace(/_([a-z])/g, function (_, c) { return c.toUpperCase(); });
  }

  function openAdd(dialog, button) {
    var form = dialog.querySelector('form');
    var tab = form.elements.tab ? form.elements.tab.value : null;
    form.reset();
    if (tab !== null) form.elements.tab.value = tab;
    form.action = (button && button.dataset.addUrl) || dialog.dataset.addUrl;
    dialog.querySelector('.dialog-title').textContent = (button && button.dataset.addTitle) || dialog.dataset.addTitle;
    if (form.elements.generation && dialog.dataset.nextGeneration) {
      form.elements.generation.value = dialog.dataset.nextGeneration;
    }
    dialog.dispatchEvent(new CustomEvent('dialog:opened', { detail: { mode: 'add', button: button } }));
    dialog.showModal();
    var first = form.querySelector('input:not([type=hidden]):not([value])') || form.querySelector('input:not([type=hidden])');
    if (first) first.focus();
  }

  function openEdit(dialog, button) {
    var form = dialog.querySelector('form');
    form.reset();
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name || el.name === 'tab') return;
      var value = button.dataset[camel(el.name)];
      if (value !== undefined) el.value = value;
    });
    form.action = dialog.dataset.editUrl.replace('/0/', '/' + button.dataset.id + '/');
    dialog.querySelector('.dialog-title').textContent = dialog.dataset.editTitle;
    dialog.dispatchEvent(new CustomEvent('dialog:opened', { detail: { mode: 'edit', button: button } }));
    dialog.showModal();
  }

  document.addEventListener('click', function (e) {
    var add = e.target.closest('[data-open-add]');
    if (add) { openAdd(document.getElementById(add.dataset.openAdd), add); return; }
    var edit = e.target.closest('[data-open-edit]');
    if (edit) { openEdit(document.getElementById(edit.dataset.openEdit), edit); return; }
    if (e.target.closest('[data-close]')) { e.target.closest('dialog').close(); return; }
    if (e.target.tagName === 'DIALOG') e.target.close();  // 바깥 영역 클릭
  });

  // 삭제 확인
  document.addEventListener('submit', function (e) {
    var message = e.target.dataset.confirm;
    if (message && !window.confirm(message)) e.preventDefault();
  });
})();
