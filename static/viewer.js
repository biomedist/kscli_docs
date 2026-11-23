// 첨부파일 미리보기: PDF·이미지·DOCX 는 화면에서 바로, 그 밖의 형식은 다운로드 안내
(function () {
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  function ensureDocx(vendor) {  // DOCX 보기 도구는 처음 필요할 때만 불러옵니다
    if (window.docx) return Promise.resolve();
    return loadScript(vendor.jszip).then(function () { return loadScript(vendor.docx); });
  }
  function message(body, text) {
    body.innerHTML = '';
    var p = document.createElement('p');
    p.className = 'viewer-msg';
    p.textContent = text;
    body.appendChild(p);
  }

  // body: 보여줄 칸, d: {kind, url, name}, vendor: {jszip, docx}, stillCurrent: 아직 이 파일을 보고 있는지 확인하는 함수
  function renderPreview(body, d, vendor, stillCurrent) {
    body.innerHTML = '';
    if (d.kind === 'pdf') {
      var frame = document.createElement('iframe');
      frame.src = d.url; frame.title = d.name;
      body.appendChild(frame);
    } else if (d.kind === 'image') {
      var img = document.createElement('img');
      img.src = d.url; img.alt = d.name;
      body.appendChild(img);
    } else if (d.kind === 'docx') {
      message(body, '문서를 불러오는 중입니다…');
      ensureDocx(vendor)
        .then(function () { return fetch(d.url); })
        .then(function (r) { return r.arrayBuffer(); })
        .then(function (buf) {
          if (stillCurrent && !stillCurrent()) return;
          body.innerHTML = '';
          var host = document.createElement('div');
          host.className = 'docx-host';
          body.appendChild(host);
          return window.docx.renderAsync(buf, host);
        })
        .catch(function () {
          if (!stillCurrent || stillCurrent()) message(body, '문서를 화면에 표시하지 못했습니다. [다운로드]로 열어 주세요.');
        });
    } else {
      message(body, '이 형식(' + (d.name || '').split('.').pop().toUpperCase() + ')은 화면에서 바로 볼 수 없습니다. [다운로드]를 눌러 열어 주세요.');
    }
  }
  window.renderPreview = renderPreview;

  var viewer = document.getElementById('viewer');
  if (!viewer) return;
  var body = viewer.querySelector('.viewer-body');
  var nameEl = viewer.querySelector('.viewer-name');
  var posEl = viewer.querySelector('.viewer-pos');
  var dl = viewer.querySelector('[data-dl]');
  var prev = viewer.querySelector('[data-prev]');
  var next = viewer.querySelector('[data-next]');
  var vendor = { jszip: viewer.dataset.jszip, docx: viewer.dataset.docx };
  var items = [], index = 0;

  function show(i) {
    index = i;
    var btn = items[i];
    nameEl.textContent = btn.dataset.name;
    dl.href = btn.dataset.download;
    posEl.textContent = items.length > 1 ? (i + 1) + ' / ' + items.length : '';
    prev.hidden = next.hidden = items.length < 2;
    prev.disabled = i === 0;
    next.disabled = i === items.length - 1;
    renderPreview(body, btn.dataset, vendor, function () { return items[index] === btn; });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-view]');
    if (!btn) return;
    items = Array.prototype.slice.call(
      document.querySelectorAll('[data-view][data-group="' + btn.dataset.group + '"]'));
    show(items.indexOf(btn));
    viewer.showModal();
  });
  prev.addEventListener('click', function () { if (index > 0) show(index - 1); });
  next.addEventListener('click', function () { if (index < items.length - 1) show(index + 1); });
  viewer.addEventListener('close', function () { body.innerHTML = ''; items = []; });
})();
