// 태그 편집기: 고른 태그 칩, 자주 쓰는 태그 누르기, 새 태그 만들기
// 같은 이름의 태그는 하나입니다. 이미 있는 이름을 입력하면 그 태그의 카테고리·색을 그대로 씁니다.
(function () {
  function keyOf(cat, name) { return cat + ':' + name; }

  function catColors(editor) {
    try { return JSON.parse(editor.dataset.catColors || '{}'); } catch (e) { return {}; }
  }
  // 만들어 둔 태그 목록(자주 쓰는 태그 버튼)에서 이름으로 찾기
  function knownTag(editor, name) {
    var buttons = editor.querySelectorAll('.suggest');
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].dataset.name === name) return buttons[i].dataset;
    }
    return null;
  }

  function selectedBox(editor) { return editor.querySelector('.tag-selected'); }
  function findByName(editor, name) {
    return Array.prototype.slice.call(selectedBox(editor).children).filter(function (c) { return c.dataset.name === name; })[0];
  }
  function refreshSuggestions(editor) {
    Array.prototype.forEach.call(editor.querySelectorAll('.suggest'), function (b) {
      b.classList.toggle('on', !!findByName(editor, b.dataset.name));
    });
  }

  function add(editor, cat, name) {
    name = (name || '').trim();
    if (!name || findByName(editor, name)) return;
    var known = knownTag(editor, name), color;
    if (known) { cat = known.cat; color = known.color; }
    else {
      cat = (cat || '').trim() || '문서종류';
      var map = catColors(editor);
      color = map[cat] !== undefined ? map[cat] : 9;
    }
    var chip = document.createElement('span');
    chip.className = 'tag-chip on tc' + color;
    chip.dataset.name = name;
    chip.title = cat;
    chip.appendChild(document.createTextNode(name + ' '));
    var remove = document.createElement('button');
    remove.type = 'button'; remove.className = 'tag-remove'; remove.setAttribute('aria-label', name + ' 태그 빼기');
    remove.textContent = '✕';
    chip.appendChild(remove);
    var hidden = document.createElement('input');
    hidden.type = 'hidden'; hidden.name = 'tags'; hidden.value = keyOf(cat, name);
    chip.appendChild(hidden);
    selectedBox(editor).appendChild(chip);
    refreshSuggestions(editor);
  }

  function removeName(editor, name) {
    var chip = findByName(editor, name);
    if (chip) chip.remove();
    refreshSuggestions(editor);
  }

  function reset(editor) {
    selectedBox(editor).innerHTML = '';
    var cat = editor.querySelector('.tag-cat'), name = editor.querySelector('.tag-name');
    if (cat) cat.value = '문서종류';
    if (name) name.value = '';
    refreshSuggestions(editor);
  }

  function set(editor, tags) {
    reset(editor);
    (tags || []).forEach(function (t) { add(editor, t.category, t.name); });
  }

  function addFromInputs(editor) {
    var cat = editor.querySelector('.tag-cat'), name = editor.querySelector('.tag-name');
    add(editor, cat.value, name.value);
    name.value = '';
    name.focus();
  }

  document.addEventListener('click', function (e) {
    var editor = e.target.closest('.tag-editor');
    if (!editor) return;
    var suggest = e.target.closest('.suggest');
    if (suggest) {
      if (findByName(editor, suggest.dataset.name)) removeName(editor, suggest.dataset.name);
      else add(editor, suggest.dataset.cat, suggest.dataset.name);
      return;
    }
    var remove = e.target.closest('.tag-remove');
    if (remove) { removeName(editor, remove.closest('.tag-chip').dataset.name); return; }
    if (e.target.closest('[data-tag-add]')) addFromInputs(editor);
  });

  document.addEventListener('keydown', function (e) {
    if (!e.target.matches || !e.target.matches('.tag-editor .tag-name, .tag-editor .tag-cat')) return;
    if (e.key === 'Enter' || (e.key === ',' && e.target.classList.contains('tag-name'))) {
      e.preventDefault();  // 입력 중 Enter 로 서류가 올라가지 않게 합니다
      addFromInputs(e.target.closest('.tag-editor'));
    }
  });

  window.TagEditor = { set: set, reset: reset, add: add };
})();
