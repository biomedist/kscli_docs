// 첨부파일 보기 창: PDF·이미지·DOCX 는 화면에서 바로, 그 밖의 형식은 다운로드 안내
(function () {
  var viewer = document.getElementById('viewer');
  if (!viewer) return;
  var body = viewer.querySelector('.viewer-body');
  var nameEl = viewer.querySelector('.viewer-name');
  var posEl = viewer.querySelector('.viewer-pos');
  var dl = viewer.querySelector('[data-dl]');
  var prev = viewer.querySelector('[data-prev]');
  var next = viewer.querySelector('[data-next]');
  var items = [], index = 0;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  function ensureDocx() {  // DOCX 보기 도구는 처음 필요할 때만 불러옵니다
    if (window.docx) return Promise.resolve();
    return loadScript(viewer.dataset.jszip).then(function () { return loadScript(viewer.dataset.docx); });
  }
  function message(text) {
    body.innerHTML = '';
    var p = document.createElement('p');
    p.className = 'viewer-msg';
    p.textContent = text;
    body.appendChild(p);
  }

  function show(i) {
    index = i;
    var btn = items[i], d = btn.dataset;
    nameEl.textContent = d.name;
    dl.href = d.download;
    posEl.textContent = items.length > 1 ? (i + 1) + ' / ' + items.length : '';
    prev.hidden = next.hidden = items.length < 2;
    prev.disabled = i === 0;
    next.disabled = i === items.length - 1;
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
      message('문서를 불러오는 중입니다…');
      ensureDocx()
        .then(function () { return fetch(d.url); })
        .then(function (r) { return r.arrayBuffer(); })
        .then(function (buf) {
          if (items[index] !== btn) return;  // 그 사이 다른 파일로 넘어갔으면 무시
          body.innerHTML = '';
          var host = document.createElement('div');
          host.className = 'docx-host';
          body.appendChild(host);
          return window.docx.renderAsync(buf, host);
        })
        .catch(function () {
          if (items[index] === btn) message('문서를 화면에 표시하지 못했습니다. 위의 [다운로드]로 열어 주세요.');
        });
    } else {
      message('이 형식(' + d.name.split('.').pop().toUpperCase() + ')은 화면에서 바로 볼 수 없습니다. 위의 [다운로드]를 눌러 열어 주세요.');
    }
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
