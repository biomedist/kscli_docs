// 시·분 선택 칸에 'HH:MM' 값을 넣어 주는 공통 도구
(function () {
  function setSelect(select, value) {
    Array.prototype.slice.call(select.querySelectorAll('option[data-extra]')).forEach(function (o) { o.remove(); });
    select.value = value;
    if (select.value !== value) {  // 예전에 입력한 값이 목록에 없으면(예: 12분) 그대로 보존합니다
      var option = document.createElement('option');
      option.value = value; option.textContent = value; option.setAttribute('data-extra', '1');
      select.appendChild(option);
      select.value = value;
    }
  }
  window.TimeSelect = {
    set: function (form, prefix, value) {
      var h = form.elements[prefix + '_h'], m = form.elements[prefix + '_m'];
      if (!h || !m) return;
      h.value = ''; m.value = '';
      var parts = (value || '').split(':');
      if (parts.length < 2 || !parts[0]) return;
      setSelect(h, ('0' + parts[0]).slice(-2));
      setSelect(m, ('0' + parts[1]).slice(-2));
    }
  };
})();
