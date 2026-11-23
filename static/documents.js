// 기타서류 목록: 태그 필터 창, 서류 추가 창의 태그 편집기 초기화
(function () {
  var filter = document.getElementById('tagfilter');
  if (filter) {
    var openButton = document.querySelector('[data-open-tagfilter]');
    var tabs = Array.prototype.slice.call(filter.querySelectorAll('[data-cat-tab]'));
    var panels = Array.prototype.slice.call(filter.querySelectorAll('[data-cat-panel]'));
    var search = filter.querySelector('#tag-search');

    function showTab(name) {
      tabs.forEach(function (t) { t.classList.toggle('active', t.dataset.catTab === name); });
      panels.forEach(function (p) { p.hidden = p.dataset.catPanel !== name; });
    }
    function filterChips(text) {
      text = text.trim().toLowerCase();
      Array.prototype.forEach.call(filter.querySelectorAll('.tag-pick'), function (label) {
        label.hidden = !!text && label.textContent.toLowerCase().indexOf(text) === -1;
      });
    }

    openButton.addEventListener('click', function () { filter.showModal(); search.focus(); });
    tabs.forEach(function (t) {
      t.addEventListener('click', function () { search.value = ''; filterChips(''); showTab(t.dataset.catTab); });
    });
    search.addEventListener('input', function () {
      if (search.value) showTab('__all');   // 검색할 때는 모든 태그에서 찾습니다
      filterChips(search.value);
    });
    search.addEventListener('keydown', function (e) { if (e.key === 'Enter') e.preventDefault(); });

    // 같은 태그가 '전체'와 카테고리 칸에 함께 있으므로 체크 상태를 맞춥니다
    filter.addEventListener('change', function (e) {
      if (e.target.name !== 'tag') return;
      Array.prototype.forEach.call(filter.querySelectorAll('input[name=tag]'), function (box) {
        if (box.value === e.target.value) box.checked = e.target.checked;
      });
    });
    filter.querySelector('[data-tf-reset]').addEventListener('click', function () {
      Array.prototype.forEach.call(filter.querySelectorAll('input[name=tag]'), function (box) { box.checked = false; });
    });
  }

  var addDialog = document.getElementById('doc-dialog');
  if (addDialog) {
    addDialog.addEventListener('dialog:opened', function () {
      // 올린 해(올해)를 연도 태그로 미리 넣어 둡니다. ✕ 로 빼거나 다른 연도 태그로 바꿀 수 있습니다.
      var year = addDialog.dataset.defaultYear;
      TagEditor.set(addDialog.querySelector('.tag-editor'), year ? [{ category: '연도', name: year }] : []);
    });
  }
})();
