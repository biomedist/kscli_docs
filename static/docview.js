// 기타서류 열기 화면: 미리보기, 창 열기, 인쇄, 닫기
(function () {
  var preview = document.getElementById('preview');
  if (preview && window.renderPreview) {
    window.renderPreview(preview, preview.dataset, { jszip: preview.dataset.jszip, docx: preview.dataset.docx });
  }

  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-open-dialog]');
    if (opener) { document.getElementById(opener.dataset.openDialog).showModal(); return; }

    var tags = e.target.closest('[data-open-tags]');
    if (tags) {
      var dialog = document.getElementById('tags-dialog');
      TagEditor.set(dialog.querySelector('.tag-editor'), JSON.parse(tags.dataset.tags || '[]'));
      dialog.showModal();
      return;
    }

    if (e.target.closest('[data-print]')) {
      if (preview && preview.dataset.kind === 'pdf') {   // PDF 는 새 창에서 인쇄합니다
        var win = window.open(preview.dataset.url, '_blank');
        if (win) win.addEventListener('load', function () { try { win.print(); } catch (err) { /* 직접 인쇄 */ } });
      } else {
        window.print();
      }
      return;
    }

    var back = e.target.closest('[data-back]');
    if (back && history.length > 1 && document.referrer.indexOf('/audit/documents') !== -1) {
      e.preventDefault();   // 검색 조건이 유지된 목록으로 돌아갑니다
      history.back();
    }
  });
})();
