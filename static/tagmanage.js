// 태그 관리: 수정 창의 색 고르기
(function () {
  var dialog = document.getElementById('tag-dialog');
  if (!dialog) return;
  var form = dialog.querySelector('form');
  var hidden = form.elements.color;
  var swatches = Array.prototype.slice.call(dialog.querySelectorAll('[data-color-pick]'));
  var defaultButton = dialog.querySelector('[data-color-default]');

  function show() {
    swatches.forEach(function (s) { s.classList.toggle('current', s.dataset.colorPick === hidden.value); });
    defaultButton.classList.toggle('primary', hidden.value === '');
  }
  dialog.addEventListener('dialog:opened', function () { show(); });   // 수정 창이 열릴 때 현재 색 표시
  dialog.addEventListener('click', function (e) {
    var pick = e.target.closest('[data-color-pick]');
    if (pick) { hidden.value = pick.dataset.colorPick; show(); return; }
    if (e.target.closest('[data-color-default]')) { hidden.value = ''; show(); }
  });
})();
