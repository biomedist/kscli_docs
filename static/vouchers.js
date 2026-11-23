// 지출결의: 결의서 만들기 화면의 선택 합계, 결의서 화면의 Ctrl+V 이미지 붙여넣기
(function () {
  // ----- 거래 고르기: 선택 건수·합계 -----
  var pick = document.getElementById('pick-form');
  if (pick) {
    var all = document.getElementById('pick-all');
    var boxes = function () { return Array.prototype.slice.call(pick.querySelectorAll('input[name=ids]')); };
    var refresh = function () {
      var on = boxes().filter(function (b) { return b.checked; });
      var sum = on.reduce(function (s, b) { return s + Number(b.dataset.amount || 0); }, 0);
      document.getElementById('pick-count').textContent = on.length;
      document.getElementById('pick-sum').textContent = sum.toLocaleString('ko-KR') + '원';
      document.getElementById('pick-go').disabled = on.length === 0;
      all.checked = on.length > 0 && on.length === boxes().length;
      all.indeterminate = on.length > 0 && on.length < boxes().length;
    };
    all.addEventListener('change', function () { boxes().forEach(function (b) { b.checked = all.checked; }); refresh(); });
    pick.addEventListener('change', function (e) { if (e.target.name === 'ids') refresh(); });
    refresh();
  }

  // ----- 증빙: Ctrl+V 로 붙여넣은 이미지를 바로 첨부 -----
  var evidence = document.querySelector('.evidence[data-upload-url]');
  if (!evidence) return;
  var zones = Array.prototype.slice.call(evidence.querySelectorAll('.paste-zone'));
  var status = document.getElementById('paste-status');
  var active = null;   // 마지막으로 클릭·선택한 칸. 없으면 영수증 칸으로 붙입니다.

  zones.forEach(function (z) {
    z.addEventListener('focus', function () { active = z; zones.forEach(function (o) { o.classList.toggle('on', o === z); }); });
    z.addEventListener('click', function (e) { if (!e.target.closest('button, a, input')) z.focus(); });
  });

  function stamp() {
    var d = new Date(), p = function (n) { return String(n).padStart(2, '0'); };
    return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '_' + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
  }

  document.addEventListener('paste', function (e) {
    if (e.target.closest && e.target.closest('input, textarea, select')) return;   // 글자 입력 중에는 건드리지 않음
    var items = (e.clipboardData && e.clipboardData.items) || [];
    var images = [];
    for (var i = 0; i < items.length; i++) {
      if (items[i].kind === 'file' && items[i].type.indexOf('image/') === 0) images.push(items[i].getAsFile());
    }
    if (!images.length) return;
    e.preventDefault();
    var zone = active || zones[zones.length - 1];
    var slot = zone.dataset.slot;
    var data = new FormData();
    data.append('slot', slot);
    images.forEach(function (blob, n) {
      var ext = (blob.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
      data.append('files', blob, (slot === 'form' ? '결의서_' : '영수증_') + stamp() + (n ? '_' + (n + 1) : '') + '.' + ext);
    });
    status.textContent = (slot === 'form' ? '결의서 이미지' : '영수증') + ' 칸에 ' + images.length + '장 올리는 중…';
    fetch(evidence.dataset.uploadUrl, { method: 'POST', body: data, credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); window.location.reload(); })
      .catch(function () { status.textContent = '올리지 못했습니다. 파일 형식(PNG·JPG)과 크기(50MB 이하)를 확인하고 다시 시도해 주세요.'; });
  });
})();
