// 행사실적 화면: 시·분 채우기, 행사 줄 클릭 이동, 프로그램 [복사]
(function () {
  var eventDialog = document.getElementById('event-dialog');
  var programDialog = document.getElementById('program-dialog');

  // 행사 입력 창: 구분 버튼으로 거른 상태면 그 구분을 미리 선택, 수정이면 시간 채우기
  if (eventDialog) {
    var eventForm = eventDialog.querySelector('form');
    eventDialog.addEventListener('dialog:opened', function (e) {
      TimeSelect.set(eventForm, 'start', '');
      TimeSelect.set(eventForm, 'end', '');
      if (e.detail.mode === 'add' && eventDialog.dataset.defaultKind) {
        eventForm.elements.kind.value = eventDialog.dataset.defaultKind;
      }
      if (e.detail.mode === 'edit') {
        TimeSelect.set(eventForm, 'start', e.detail.button.dataset.startTime);
        TimeSelect.set(eventForm, 'end', e.detail.button.dataset.endTime);
      }
    });
  }

  // 프로그램 입력 창
  if (programDialog) {
    var programForm = programDialog.querySelector('form');
    programDialog.addEventListener('dialog:opened', function (e) {
      TimeSelect.set(programForm, 'start', '');
      TimeSelect.set(programForm, 'end', '');
      if (e.detail.mode === 'edit') {
        TimeSelect.set(programForm, 'start', e.detail.button.dataset.startTime);
        TimeSelect.set(programForm, 'end', e.detail.button.dataset.endTime);
      }
    });
  }

  document.addEventListener('click', function (e) {
    // [복사]: 같은 줄의 강의명·강연자·소속을 가져오고, 시작 시간은 원본의 종료 시간으로
    var copy = e.target.closest('[data-copy]');
    if (copy && programDialog) {
      document.querySelector('[data-open-add="program-dialog"]').click();
      programForm.elements.title.value = copy.dataset.title || '';
      programForm.elements.speaker.value = copy.dataset.speaker || '';
      programForm.elements.affiliation.value = copy.dataset.affiliation || '';
      TimeSelect.set(programForm, 'start', copy.dataset.nextStart || '');
      programForm.elements.title.focus();
      programForm.elements.title.select();
      return;
    }
    // 행사 줄을 누르면 프로그램표로 이동 (버튼·링크·입력창을 누른 경우는 제외)
    var row = e.target.closest('tr[data-href]');
    if (row && !e.target.closest('a, button, form, input, label')) {
      window.location.href = row.dataset.href;
    }
  });
})();
