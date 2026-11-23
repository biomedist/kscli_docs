// 사업실적 입력 창: [행사 불러오기] — 교육·학술대회·워크숍에 입력한 일시·장소·참석 인원을 채워 줍니다.
(function () {
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-event-load]');
    if (!btn) return;
    var box = btn.closest('[data-event-pick]');
    var option = box.querySelector('select').selectedOptions[0];
    if (!option || !option.value) { box.querySelector('select').focus(); return; }
    var form = btn.closest('form');
    var name = form.elements.name, result = form.elements.result;
    if (!name.value.trim()) name.value = option.dataset.name;            // 사업목표가 비어 있으면 행사명으로
    var text = option.dataset.text;
    if (result.value.indexOf(text) === -1) {                             // 이미 불러왔으면 중복해서 넣지 않음
      result.value = result.value.trim() ? result.value.replace(/\s+$/, '') + '\n\n' + text : text;
    }
    result.focus();
    result.setSelectionRange(result.value.length, result.value.length);
  });
})();
