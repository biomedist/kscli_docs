// 행정지도감사 첫 화면: 잠긴 카드를 누르면 비밀번호 입력 창(팝업)을 띄웁니다.
(function () {
  var dialog = document.getElementById('unlock-dialog');
  if (!dialog) return;
  document.addEventListener('click', function (e) {
    var card = e.target.closest('a[data-locked]');
    if (!card) return;
    e.preventDefault();
    dialog.querySelector('input[name=next]').value = new URL(card.href).pathname;
    var input = dialog.querySelector('input[name=password]');
    input.value = '';
    dialog.showModal();
    input.focus();
  });
})();
