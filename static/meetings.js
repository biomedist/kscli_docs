// 회의실적 화면: 출석 체크 → 총인원·참석수 자동 계산
(function () {
  // ----- 회의 입력 창 -----
  var dialog = document.getElementById('meeting-dialog');
  if (!dialog) return;
  var form = dialog.querySelector('form');
  var dataEl = document.getElementById('meeting-data');
  var attendance = dataEl ? JSON.parse(dataEl.textContent) : {};

  function boxes(name) {
    return Array.prototype.slice.call(form.querySelectorAll('input[name="' + name + '"]'));
  }
  function markDirty() { form.elements.attendance_dirty.value = '1'; }

  function recalc() {
    var exec = boxes('exec_present'), council = boxes('council_present');
    var presentCount = exec.concat(council).filter(function (c) { return c.checked; }).length;
    var councilAttended = council.some(function (c) { return c.checked; });
    form.elements.attendees.value = presentCount;
    form.elements.total_members.value = exec.length + (councilAttended ? council.length : 0);
  }

  form.addEventListener('change', function (e) {
    if (e.target.name === 'exec_present' || e.target.name === 'council_present') {
      markDirty();
      recalc();
    }
  });

  form.addEventListener('click', function (e) {
    var all = e.target.closest('[data-att-all]');
    var none = e.target.closest('[data-att-none]');
    if (!all && !none) return;
    boxes('exec_present').forEach(function (c) { c.checked = !!all; });
    markDirty();
    recalc();
  });

  dialog.addEventListener('dialog:opened', function (e) {
    form.elements.attendance_dirty.value = '0';
    var details = form.querySelector('details.council');
    if (details) details.open = false;
    if (e.detail.mode !== 'edit') return;
    var held = (e.detail.button.dataset.heldAt || '').split('T');
    form.elements.held_date.value = held[0] || '';
    TimeSelect.set(form, 'held', held[1] || '');
    var saved = attendance[e.detail.button.dataset.id] || { exec: [], council: [] };
    boxes('exec_present').forEach(function (c) { c.checked = saved.exec.indexOf(Number(c.value)) !== -1; });
    boxes('council_present').forEach(function (c) {
      c.checked = saved.council.indexOf(Number(c.value)) !== -1;
      if (c.checked && details) details.open = true;
    });
  });
})();
