// 예산·결산 화면: 거래 선택(일괄 처리 막대), 통장 바꾸기, 예산과목 추가 창
(function () {
  // ----- 거래 선택 -----
  var form = document.getElementById('tx-form');
  var all = document.getElementById('check-all');
  if (all) {
    var scope = form || all.closest('form') || document;
    var boxes = function () { return Array.prototype.slice.call(scope.querySelectorAll('input[type=checkbox][name=ids], input[type=checkbox][name=pair]')); };
    var bar = document.getElementById('bulk-bar');
    var count = document.getElementById('selected-count');
    function refresh() {
      var checked = boxes().filter(function (b) { return b.checked; }).length;
      if (count) count.textContent = checked;
      if (bar) bar.hidden = checked === 0;
      all.checked = checked > 0 && checked === boxes().length;
      all.indeterminate = checked > 0 && checked < boxes().length;
    }
    all.addEventListener('change', function () { boxes().forEach(function (b) { b.checked = all.checked; }); refresh(); });
    scope.addEventListener('change', function (e) { if (e.target.matches('input[name=ids], input[name=pair]')) refresh(); });
    refresh();
    // 예산과목을 고르지 않고 [분류 지정]을 누르면 막습니다
    if (form) form.addEventListener('submit', function (e) {
      var submitter = e.submitter;
      if (submitter && submitter.value === 'category' && !form.elements.category_id.value) {
        e.preventDefault();
        alert('예산과목을 먼저 선택해 주세요.');
      }
    });
  }

  // ----- 엑셀 확인 화면: 통장을 바꾸면 건너뛸 거래 수를 다시 계산 -----
  var pick = document.getElementById('account-pick');
  if (pick) pick.addEventListener('change', function () {
    if (pick.value) window.location.href = pick.dataset.previewUrl + '?account=' + encodeURIComponent(pick.value);
  });

  // ----- 예산과목 추가·수정 창 -----
  var dialog = document.getElementById('cat-dialog');
  if (dialog) {
    var catForm = dialog.querySelector('form');
    dialog.addEventListener('dialog:opened', function (e) {
      var button = e.detail.button;
      if (e.detail.mode === 'add') {
        catForm.elements.parent_id.value = button.dataset.parentId || '';
        catForm.elements.kind.value = button.dataset.kind || '';
      }
    });
  }

  // ----- 거래내역: 예산과목 칸을 눌렀을 때 뜨는 창 -----
  var txDialog = document.getElementById('tx-cat-dialog');
  if (txDialog) {
    txDialog.addEventListener('dialog:opened', function (e) {
      var what = txDialog.querySelector('.pick-what');
      if (what) what.textContent = e.detail.button.dataset.desc || '(내용 없음)';
    });
  }
})();
