// 찬조금 세부 화면: [복사] 버튼 (같은 일자·구분·사용내역으로 다음 찬조금 입력)
(function () {
  var dialog = document.getElementById('donation-dialog');
  if (!dialog) return;
  var form = dialog.querySelector('form');
  document.addEventListener('click', function (e) {
    var copy = e.target.closest('[data-copy-donation]');
    if (!copy) return;
    document.querySelector('[data-open-add="donation-dialog"]').click();   // 빈 입력 창을 열고 일부만 채웁니다
    form.elements.donated_on.value = copy.dataset.donatedOn || '';
    form.elements.kind.value = copy.dataset.kind || form.elements.kind.value;
    form.elements.usage.value = copy.dataset.usage || '';
    form.elements.note.value = copy.dataset.note || '';
    form.elements.donor.focus();
  });
})();
