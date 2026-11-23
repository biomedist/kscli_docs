// 파일 첨부 공통 동작: [+ 첨부]를 누르면 파일 선택, 고르면 바로 업로드
(function () {
  document.addEventListener('click', function (e) {
    var pick = e.target.closest('[data-pick]');
    if (pick) pick.closest('form').querySelector('input[type=file]').click();
  });
  document.addEventListener('change', function (e) {
    if (e.target.matches('.attach-form input[type=file]') && e.target.files.length) {
      e.target.closest('form').submit();
    }
  });
})();
