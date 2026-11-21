
(async () => {
  'use strict';
  const D = window.MobileWorkspaceHost;
  await window.MobileWorkspaceHost.extensions["mobile-workspace"].ready;
  const byId = id => document.getElementById(id);
  const overlay = byId('mobile-overlay');
  const promptPanel = byId('mobile-prompt');
  const paramsPanel = byId('mobile-params');
  const hiresDivider = document.createElement('hr');
  hiresDivider.className = 'mobile-hires-divider';
  const promptSubtitle = byId('mobile-prompt-subtitle');
  const upper = byId('mobile-upper');
  const topScroll = overlay.querySelector('.mobile-settings-scroll');
  const base = byId('tabs');
  const canvas = byId('mobile-canvas');
  const layout = byId('mobile-layout');
  const divider = byId('mobile-divider');
  const picker = byId('mobile-panel-picker');
  const panelBody = byId('mobile-panel-body');
  const mode = byId('mobile-mode');
  const bar = byId('mobile-bar');
  const toggleBar = byId('mobile-toggle-bar');
  const tabs = [...overlay.querySelectorAll('.mobile-tab-row [role="tab"]:not([disabled])')];
  const storedView = D.storage.get('mobile-layout', {});
  const view = { split: .5, locked: false, barHidden: false, tab: 'prompt', panels: {}, showStyles: false, generateButton: 'disabled', promptExtras: false, negative: false, enableHiresPrompt: false, hiresInParams: false, hiresPrompt: false, loraMin: -1, loraMax: 1, ...D.defaults['mobile-layout'], ...storedView };
  const minUiScale = 80;
  const maxUiScale = 120;
  const uiScaleStep = 5;
  const normalizeUiScale = value => Number.isFinite(value)
    ? Math.min(maxUiScale, Math.max(minUiScale, Math.round(value / uiScaleStep) * uiScaleStep))
    : D.defaults['mobile-layout'].uiScale;
  view.uiScale = normalizeUiScale(view.uiScale);
  if (view.tab === 'settings') view.tab = 'panels';
  const showStyles = byId('mobile-show-styles');
  const generateButton = byId('mobile-generate-button');
  const promptExtras = byId('mobile-prompt-extras');
  const settingsFile = byId('mobile-settings-file');
  const negativeToggle = byId('mobile-negative-toggle');
  const hiresToggle = byId('mobile-hires-toggle');
  const clonePrompt = byId('mobile-clone-prompt');
  const generationActions = byId('mobile-generation-actions');
  const enableHiresPrompt = byId('mobile-enable-hires-prompt');
  const hiresInParams = byId('mobile-hires-in-params');
  const scaleDown = byId('mobile-scale-down');
  const scaleUp = byId('mobile-scale-up');
  const scaleOutput = byId('mobile-ui-scale');
  const loraMin = byId('mobile-lora-min');
  const loraMax = byId('mobile-lora-max');
  const loraList = byId('mobile-lora-list');
  const loraHost = byId('mobile-lora-browser');
  const moved = [];
  let panelChoices = [];
  let gesture = null;
  let lastTap = null;
  let switching = false;
  let promptSubtitleFrame = 0;
  let mountedMode;
  let nativeVisibility;

  const save = () => D.storage.set('mobile-layout', view);
  const nativeTab = () => window.get_uiCurrentTabContent()?.id.slice(4) || mode.value || 'txt2img';
  const clamp = value => Math.min(.76, Math.max(.24, value));

  const launch = document.createElement('button');
  launch.type = 'button';
  launch.id = 'mobile-launch';
  launch.className = 'gradio-button';
  launch.textContent = 'Open mobile workspace';
  launch.setAttribute('aria-haspopup', 'dialog');
  launch.setAttribute('aria-controls', overlay.id);
  byId('quicksettings').after(launch);
  const dockerPanel = D.createDockPanel();
  panelBody.append(dockerPanel);

  function place(node, target) {
    if (!node || moved.some(item => item.node === node)) return;
    const marker = document.createComment('mobile workspace');
    node.before(marker);
    moved.push({ node, marker, hidden: node.hidden });
    target.append(node);
  }

  function restoreControls() {
    hiresDivider.remove();
    for (const { node, marker, hidden } of moved.reverse()) {
      marker.replaceWith(node);
      node.hidden = hidden;
      node.classList.remove('fm-expanded-panel');
      node.classList.remove('prompt-box', 'fm-native-hires', 'fm-dynamic-panel', 'fm-lora-page');
    }
    moved.length = 0;
    mountedMode = undefined;
  }

  function selectPanel(id, remember = true) {
    const choice = panelChoices.find(panel => panel.id === id) || panelChoices[0];
    if (!choice) return;
    picker.value = choice.id;
    for (const panel of panelChoices) panel.node.hidden = panel !== choice;

    if (remember) {
      view.panels[mode.value] = choice.id;
      save();
    }
    D.emit('update');
  }

  function promptId(tab, hires, negative) {
    if (hires && tab === 'txt2img') return negative ? 'hires_neg_prompt' : 'hires_prompt';
    if (hires && tab === 'img2img') return negative ? 'img2img_hr_neg_prompt' : 'img2img_hr_prompt';
    return tab + (negative ? '_neg_prompt' : '_prompt');
  }

  function mountControls() {
    const tab = nativeTab();
    mode.value = tab;
    mountedMode = tab;
    const controls = byId(tab + '_settings');
    const fields = document.createElement('div');
    fields.className = 'prompt-fields';
    const promptRow = document.createElement('div');
    promptRow.className = 'prompt-row';
    promptRow.append(clonePrompt, fields);
    promptPanel.replaceChildren(promptRow);
    for (const id of [tab + '_prompt', tab + '_neg_prompt',
      ...(tab === 'txt2img' ? ['hires_prompt', 'hires_neg_prompt'] : ['img2img_hr_prompt', 'img2img_hr_neg_prompt'])]) {
      const node = byId(id);
      if (!node) continue;
      place(node, fields);
      node.classList.add('prompt-box');
    }
    const extras = document.createElement('div');
    extras.className = 'generate-box';
    promptRow.append(extras);
    for (const [id, className] of [[tab + '_tools', 'prompt-tools'], [tab + '_styles', 'styles-row']]) {
      const node = byId(id);
      if (node) {
        place(node, extras);
        node.classList.add(className);
      }
    }
    for (const action of ['generate', 'interrupt', 'interrupting', 'skip']) {
      place(byId(tab + '_' + action), generationActions);
    }

    const model = byId('quicksettings');
    place(model, panelBody);
    panelChoices = [{ node: model, label: 'Model', id: 'model' }];
    const hires = byId(tab === 'img2img' ? 'img2img_hires_fix_extension' : 'txt2img_hr');
    const addPanel = (node, label, id) => {
      place(node, panelBody);
      node.classList.add('fm-dynamic-panel', 'fm-expanded-panel');
      panelChoices.push({ node, label, id });
    };
    if (controls) {
      const accordions = [...controls.querySelectorAll('.gradio-accordion')]
        .filter(node => !node.parentElement.closest('.gradio-accordion'));
      for (const node of accordions) {
        if (!node.isConnected) continue;
        if (node === hires) continue;
        const label = node.querySelector(':scope > .label-wrap')?.textContent.trim() || node.id || 'Extension';
        if (node.classList.contains('fdm-manager-accordion') || /^Docker Manager\b/i.test(label)) {
          place(node, byId('tab_' + tab));
          if (node.id && view.panels[tab] === node.id) view.panels[tab] = 'docker';
          continue;
        }
        addPanel(node, label, node.id || 'panel-' + panelChoices.length);
      }
      // Keep img2img's upload, sketch and inpaint components with their native tab controls.
      for (const node of [...controls.children]) {
        // Gradio positions the column's status tracker against its native parent.
        // Its idle state uses opacity, so a display check alone also moves it.
        if (node.matches('.wrap.default, .wrap.center')) continue;
        if (node !== hires && !node.hidden && getComputedStyle(node).display !== 'none') place(node, paramsPanel);
      }
    }
    if (hires) {
      if (view.hiresInParams) {
        place(hires, paramsPanel);
        // It may have travelled inside a parameter wrapper; append it last.
        paramsPanel.append(hiresDivider, hires);
        hires.hidden = false;
        hires.classList.add('fm-expanded-panel');
      } else if (!moved.some(item => item.node === hires)) addPanel(hires, 'Hires Fix', 'hires');
    }
    // Keep the real extra-tabs ancestor: Forge's folder/search handlers query
    // cards beneath #<mode>_extra_tabs. Its toolbar was moved into the tab-nav
    // by setupExtraNetworksForTab, so moving only the card page loses navigation.
    const lora = byId(tab + '_lora');
    const extraTabs = byId(tab + '_extra_tabs');
    if (lora) {
      // Native selected_gallery_index() requires a laid-out gallery. Leave
      // outputs in the native generation tab, outside the hidden LoRAs panel,
      // so the gallery and Hires Fix docks still select the correct image.
      const outputs = byId(tab + '_gallery_container');
      if (extraTabs && outputs && extraTabs.contains(outputs)) place(outputs, byId('tab_' + tab));
      if (extraTabs) place(extraTabs, loraHost);
      place(lora, extraTabs || loraHost);
      lora.classList.add('fm-lora-page');
      if (!lora.querySelector('.card')) byId(tab + '_lora_extra_refresh_internal')?.click();
    }
    dockerPanel.hidden = false;
    panelChoices.push({ node: dockerPanel, label: 'Docker Manager', id: 'docker' });
    panelChoices.push({ node: byId('mobile-settings'), label: 'Settings', id: 'settings' });
    D.syncDockerPanel(tab);
    renderPromptSide();
    picker.replaceChildren(...panelChoices.map(panel => new Option(panel.label, panel.id)));
    selectPanel(view.panels[tab] || 'hires', false);
  }

  function selectTab(name, focus = false) {
    if (!tabs.some(tab => tab.id === 'mobile-tab-' + name)) name = 'prompt';
    view.tab = name;
    overlay.dataset.activeTab = name;
    save();
    for (const tab of tabs) {
      const selected = tab.id === 'mobile-tab-' + name;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      byId(tab.getAttribute('aria-controls')).hidden = !selected;
      if (selected && focus) tab.focus();
    }
    topScroll.scrollTop = 0;
    fitPromptFields();
    if (name !== 'prompt') promptSubtitle.hidden = true;
    schedulePromptSubtitle();
    if (name === 'loras') renderLoras();
    if (name === 'iib') D.openIIB?.().catch(error => console.warn(error));

    D.emit('update');
  }

  function fitMobileViewport() {
    const viewport = window.visualViewport;
    const editing = !overlay.hidden && !promptPanel.hidden
      && promptPanel.contains(document.activeElement)
      && document.activeElement.matches('.prompt-box textarea')
      && (navigator.maxTouchPoints > 0 || matchMedia('(pointer: coarse)').matches);
    // Reserve the editor on focus, before the keyboard animates. Safari may
    // report a page scale other than one throughout the entire session.
    overlay.toggleAttribute('data-prompt-keyboard', editing);
    const measure = viewport?.height > 0 && (editing || viewport.scale === 1);
    for (const [property, value] of [
      ['height', measure && viewport.height], ['top', measure && viewport.offsetTop],
      ['width', editing && measure && viewport.width], ['left', editing && measure && viewport.offsetLeft]
    ]) {
      const key = '--mobile-viewport-' + property;
      if (value === false || value == null) overlay.style.removeProperty(key);
      else overlay.style.setProperty(key, Math.max(0, value) + 'px');
    }
  }

  function renderSplit() {
    layout.style.setProperty('--lower-share', String(1 - view.split));
    const percent = Math.round(view.split * 100);
    const status = view.locked ? 'locked' : 'unlocked';
    divider.dataset.locked = String(view.locked);
    divider.setAttribute('aria-valuenow', String(percent));
    divider.setAttribute('aria-valuetext', percent + '% top, ' + status);
    divider.title = view.locked ? 'Double-tap to unlock split' : 'Double-tap to lock split';
  }

  const galleryDockSelector = '.fdm-dock-shell:is([data-dock-id="gallery"], [data-dock-id="full-gallery-preview"])';

  function fitGalleryTrack() {
    let height = 0;
    for (const dock of canvas.querySelectorAll(galleryDockSelector)) {
      const dockHeight = dock.getBoundingClientRect().height;
      if (dockHeight > 0) height = Math.max(height, Math.ceil(dockHeight) + 10);
    }
    layout.style.setProperty('--mobile-gallery-height', height + 'px');
  }

  const galleryResizeObserver = new ResizeObserver(fitGalleryTrack);

  function renderDocks() {
    canvas.querySelector('.mobile-empty').hidden = Boolean(canvas.querySelector('.fdm-dock-shell'));
    galleryResizeObserver.disconnect();
    for (const dock of canvas.querySelectorAll(galleryDockSelector)) {
      galleryResizeObserver.observe(dock, { box: 'border-box' });
    }
    fitGalleryTrack();
  }

  function fitPromptFields() {
    if (overlay.hidden || promptPanel.hidden) return;
    const scrollStyle = getComputedStyle(topScroll);
    const available = topScroll.clientHeight
      - (parseFloat(scrollStyle.paddingTop) || 0) - (parseFloat(scrollStyle.paddingBottom) || 0);
    const zoom = view.uiScale / 100;
    for (const field of promptPanel.querySelectorAll('.prompt-box:not([hidden]) textarea')) {
      const original = { height: field.style.height, minHeight: field.style.minHeight, flex: field.style.flex };
      // Measure natural content and surrounding controls without a previous
      // minimum feeding back into the next resize. All dimensions below are
      // CSS pixels, including at the default 85% upper-workspace scale.
      field.style.height = '0px';
      field.style.minHeight = '0px';
      field.style.flex = 'none';
      const styles = getComputedStyle(field);
      const border = styles.boxSizing === 'border-box'
        ? (parseFloat(styles.borderTopWidth) || 0) + (parseFloat(styles.borderBottomWidth) || 0)
        : -(parseFloat(styles.paddingTop) || 0) - (parseFloat(styles.paddingBottom) || 0);
      const contentHeight = field.scrollHeight + border;
      const surrounding = Math.max(0, (promptPanel.getBoundingClientRect().height
        - field.getBoundingClientRect().height) / zoom);
      for (const [property, value] of Object.entries(original)) field.style[property] = value;
      const height = Math.ceil(Math.max(52, contentHeight, available - surrounding));
      field.style.setProperty('--mobile-prompt-height', height + 'px');
    }
    schedulePromptSubtitle();
  }

  let committingLoraWeight = false;

  function renderLoras() {
    if (committingLoraWeight) return;
    const tab = mode.value;
    const enabled = D.loras.read(tab);
    loraList.replaceChildren();
    for (const [name, weight] of enabled) {
      const { label: title } = D.loras.catalog.get(name) || { label: name };
      const row = document.createElement('div');
      row.className = 'mobile-lora-row';
      const image = document.createElement('img');
      const preview = D.loras.preview(name);
      if (preview) image.src = preview;
      else image.hidden = true;
      image.alt = '';
      const label = document.createElement('label');
      label.textContent = title;
      const slider = document.createElement('input');
      slider.type = 'range';
      slider.min = view.loraMin;
      slider.max = view.loraMax;
      slider.step = 'any';
      slider.value = weight;
      label.append(slider);
      const output = document.createElement('output');
      output.value = weight;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'gradio-button';
      remove.textContent = '×';
      remove.setAttribute('aria-label', 'Remove ' + title);
      const sliderWeight = () => Number(slider.valueAsNumber.toFixed(2));
      slider.addEventListener('input', () => {
        output.value = sliderWeight();
      });
      slider.addEventListener('change', () => {
        const next = D.loras.read(tab);
        const value = Math.max(view.loraMin, Math.min(view.loraMax, sliderWeight()));
        if (!next.has(name) || next.get(name) === value) return;
        next.set(name, value);
        slider.value = value;
        output.value = value;
        committingLoraWeight = true;
        try {
          D.loras.write(tab, next);
        } finally {
          committingLoraWeight = false;
        }
      });
      remove.addEventListener('click', () => {
        const next = D.loras.read(tab);
        next.delete(name);
        D.loras.write(tab, next);
      });
      row.append(image, label, output, remove);
      loraList.append(row);
    }
  }

  function positionPromptSubtitle() {
    const field = promptPanel.querySelector('.prompt-box:not([hidden]) textarea');
    if (overlay.hidden || promptPanel.hidden || !field) {
      promptSubtitle.hidden = true;
      return;
    }
    const box = field.getBoundingClientRect();
    const viewport = topScroll.getBoundingClientRect();
    const visibleTop = Math.max(box.top, viewport.top);
    const visibleBottom = Math.min(box.bottom, viewport.bottom);
    const visibleLeft = Math.max(box.left, viewport.left);
    const visibleRight = Math.min(box.right, viewport.right);
    const inset = 7;
    promptSubtitle.hidden = false;
    const { offsetWidth: width, offsetHeight: height } = promptSubtitle;
    if (visibleBottom - visibleTop < height + inset * 2 || visibleRight - visibleLeft < width + inset * 2) {
      promptSubtitle.hidden = true;
      return;
    }
    const cornerVisible = box.bottom - inset <= viewport.bottom && box.right - inset <= viewport.right;
    const left = cornerVisible ? box.right - inset - width : (visibleLeft + visibleRight - width) / 2;
    const top = cornerVisible ? box.bottom - inset - height : visibleTop + inset;
    const origin = upper.getBoundingClientRect();
    promptSubtitle.style.left = left - origin.left + 'px';
    promptSubtitle.style.top = top - origin.top + 'px';
  }

  function schedulePromptSubtitle() {
    if (promptSubtitleFrame) return;
    promptSubtitleFrame = requestAnimationFrame(() => {
      promptSubtitleFrame = 0;
      positionPromptSubtitle();
    });
  }

  const tokenObserver = new MutationObserver(renderPromptValidity);
  let syntaxTimer;
  let syntaxVersion = 0;

  function promptCounter() {
    const tab = mode.value;
    const hires = !clonePrompt.hidden;
    const side = view.negative ? 'negative_token_counter' : 'token_counter';
    const box = byId(promptId(tab, hires, view.negative));
    return box?.querySelector('.token-counter') || (hires
      ? byId(tab + '_hr_' + side) || (tab === 'txt2img' && byId('hr_' + side))
      : byId(tab + '_' + side));
  }

  function renderPromptValidity() {
    const counter = promptCounter();
    if (!counter) return;
    promptSubtitle.classList.toggle('fm-prompt-error', counter.matches('.error')
      || Boolean(counter.querySelector('.error')) || /\berror\b/i.test(counter.textContent));
  }

  function validateHiresPrompt() {
    clearTimeout(syntaxTimer);
    const version = ++syntaxVersion;
    if (clonePrompt.hidden || promptCounter()) return;
    const tab = mode.value;
    const field = byId(promptId(tab, true, view.negative))?.querySelector('textarea');
    if (!field) return;
    const prompt = promptId(tab, false, view.negative);
    const text = field.value;
    const stepField = byId(tab === 'img2img' ? 'img2img_hires_fix_steps' : 'txt2img_hires_steps');
    const steps = Number(stepField?.querySelector('input[type="number"]')?.value);
    syntaxTimer = setTimeout(async () => {
      try {
        const response = await fetch('/_forge_mobile/prompt-validity', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt, text, steps }),
        });
        if (!response.ok) return;
        const { invalid } = await response.json();
        if (version === syntaxVersion && field.value === text && invalid !== null) {
          promptSubtitle.classList.toggle('fm-prompt-error', invalid === true);
        }
      } catch { /* Forge may be reconnecting. */ }
    }, 320);
  }

  function watchPromptValidity() {
    tokenObserver.disconnect();
    const counter = promptCounter();
    promptSubtitle.classList.remove('fm-prompt-error');
    if (counter) {
      tokenObserver.observe(counter, { attributes: true, childList: true, characterData: true, subtree: true });
      renderPromptValidity();
    }
    validateHiresPrompt();
  }

  function renderPromptSide() {
    const hasHiresPrompts = Boolean(byId(promptId(mode.value, true, false)) && byId(promptId(mode.value, true, true)));
    hiresToggle.disabled = !hasHiresPrompts;
    const hires = hasHiresPrompts && view.enableHiresPrompt && view.hiresPrompt;
    for (const box of promptPanel.querySelectorAll('.prompt-box')) {
      box.hidden = box.id !== promptId(mode.value, hires, view.negative);
    }
    negativeToggle.setAttribute('aria-pressed', String(view.negative));
    negativeToggle.firstChild.textContent = view.negative ? 'Positive' : 'Negative';
    hiresToggle.hidden = !view.enableHiresPrompt;
    clonePrompt.hidden = !hires;
    hiresToggle.textContent = hires ? 'Hires Fix' : 'Normal';
    hiresToggle.setAttribute('aria-pressed', String(Boolean(hires)));
    promptSubtitle.textContent = (hires ? 'Hires Fix ' : '') + (view.negative ? 'negative prompt' : 'positive prompt');
    if (!hires) promptSubtitle.textContent = view.negative ? 'Negative prompt' : 'Positive prompt';
    watchPromptValidity();
    fitPromptFields();
    schedulePromptSubtitle();
  }

  function renderUiScale() {
    upper.style.setProperty('--mobile-ui-zoom', String(view.uiScale / 100));
    upper.style.setProperty('--mobile-ui-inverse', String(100 / view.uiScale));
    scaleOutput.value = view.uiScale + '%';
    scaleDown.disabled = view.uiScale <= minUiScale;
    scaleUp.disabled = view.uiScale >= maxUiScale;
    requestAnimationFrame(fitPromptFields);
    schedulePromptSubtitle();
  }

  function renderOptions() {
    renderUiScale();
    showStyles.checked = view.showStyles;
    generateButton.value = view.generateButton;
    promptExtras.checked = view.promptExtras;
    enableHiresPrompt.checked = view.enableHiresPrompt;
    hiresInParams.checked = view.hiresInParams;
    loraMin.value = view.loraMin;
    loraMax.value = view.loraMax;
    overlay.dataset.showStyles = String(view.showStyles);
    overlay.dataset.generateButton = view.generateButton;
    overlay.dataset.promptExtras = String(view.promptExtras);
  }

  function renderBar() {
    bar.dataset.collapsed = String(view.barHidden);
    bar.toggleAttribute('inert', view.barHidden);
    const action = view.barHidden ? 'Show' : 'Hide';
    toggleBar.textContent = action;
    toggleBar.setAttribute('aria-label', action + ' top bar');
    toggleBar.setAttribute('aria-expanded', String(!view.barHidden));
  }

  function setBarHidden(hidden) {
    view.barHidden = hidden;
    renderBar();
    save();
  }

  async function open() {
    if (switching || !overlay.hidden) return;
    const content = byId('mobile-upper-content');
    if (!content || getComputedStyle(content).getPropertyValue('--mobile-workspace-layout').trim() !== 'scaled') {
      D.notify('Mobile workspace stylesheet did not load. Reload the Forge Mobile page.');
      return;
    }
    if (!byId('txt2img_generate') || !byId('img2img_generate')) {
      D.notify('Forge is loading its controls. Try again in a moment.');
      return;
    }
    switching = true;
    try {
      const tab = nativeTab();
      if (tab !== 'txt2img' && tab !== 'img2img') D.selectTab('txt2img');
      mode.value = nativeTab();
      if (view.tab === 'hires') {
        view.panels[mode.value] = 'hires';
        view.tab = 'panels';
      }
      if (view.tab === 'model') {
        view.panels[mode.value] = 'model';
        view.tab = 'panels';
      }
      mountControls();
      fitMobileViewport();
      overlay.hidden = false;
      const tutorialClear = byId('tutorial-clear');
      if (tutorialClear) overlay.append(tutorialClear);
      nativeVisibility = base.style.visibility;
      base.style.setProperty('visibility', 'hidden');
      document.body.classList.add('mobile-active');
      renderSplit();
      selectTab(view.tab);
      await window.ForgeMobileDockManager?.setWorkspace(canvas);
      D.syncDockerPanel(mode.value);
      (view.barHidden ? toggleBar : byId('mobile-exit')).focus();
    } finally {
      switching = false;
    }
  }

  async function close() {
    if (switching || overlay.hidden) return;
    switching = true;
    try {
      D.closeIIBMenu?.();
      const tutorialClear = byId('tutorial-clear');
      if (tutorialClear) document.body.append(tutorialClear);
      restoreControls();
      await window.ForgeMobileDockManager?.setWorkspace(null);
      overlay.hidden = true;
      base.style.visibility = nativeVisibility || '';
      document.body.classList.remove('mobile-active');
      launch.focus();
    } finally {
      switching = false;
    }
  }

  async function exportSettings() {
    const settings = {};
    for (const key of D.settingsKeys) {
      const value = D.storage.get(key);
      if (value !== null) settings[key] = value;
    }
    await window.forgeMobileFlushFields?.();
    const controlsResponse = await fetch(D.prefix + '/controls', { cache: 'no-store' });
    if (!controlsResponse.ok) throw new Error('Could not export Forge settings');
    settings.controls = await controlsResponse.json();
    settings['mobile-layout'] = view;
    const activeDocks = window.ForgeMobileDockManager?.getLayoutSnapshot();
    if (activeDocks) settings['mobile-docks'] = activeDocks;
    const data = JSON.stringify({ format: 'forge-neo-settings', version: 1, settings }, null, 2);
    const url = URL.createObjectURL(new Blob([data + '\n'], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'forge-neo-settings.json';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function importSettings(event) {
    const [file] = event.target.files;
    event.target.value = '';
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      D.notify('This settings file is too large.');
      return;
    }
    try {
      const { format, version, settings } = JSON.parse(await file.text());
      const record = value => value && typeof value === 'object' && !Array.isArray(value);
      if (format !== 'forge-neo-settings' || version !== 1 || !record(settings)) throw new Error();
      const layout = settings['mobile-layout'];
      if (!record(layout) || !record(layout.panels) || !Number.isFinite(layout.split)
          || layout.split < .24 || layout.split > .76
          || !Number.isFinite(layout.loraMin) || !Number.isFinite(layout.loraMax)
          || layout.loraMin >= layout.loraMax) throw new Error();
      const allowed = {};
      for (const key of D.settingsKeys) {
        if (!Object.hasOwn(settings, key)) continue;
        if (!record(settings[key])) throw new Error();
        if ((key === 'docks' || key === 'mobile-docks')
            && (!Array.isArray(settings[key].docks) || !settings[key].docks.every(record))) throw new Error();
        allowed[key] = settings[key];
      }
      if (!Object.entries(allowed).every(([key, value]) => D.storage.set(key, value))) {
        D.notify('Browser storage is unavailable. Settings could not be imported.');
        return;
      }
      if (allowed.controls) {
        const response = await fetch(D.prefix + '/controls', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(allowed.controls)
        });
        if (!response.ok) throw new Error('Could not import Forge controls');
      }
      await D.flush();
      window.location.reload();
    } catch {
      D.notify('Choose a valid Forge Neo settings JSON file.');
    }
  }

  for (const [button, change] of [[scaleDown, -uiScaleStep], [scaleUp, uiScaleStep]]) {
    button.addEventListener('click', () => {
      view.uiScale = normalizeUiScale(view.uiScale + change);
      renderUiScale();
      save();
    });
  }

  byId('mobile-save-settings').addEventListener('click', () => exportSettings().catch(error => D.notify(error.message)));
  byId('mobile-load-settings').addEventListener('click', () => settingsFile.click());
  settingsFile.addEventListener('change', importSettings);
  byId('mobile-prompt-done').addEventListener('click', () => {
    if (promptPanel.contains(document.activeElement)) document.activeElement.blur();
    fitMobileViewport();
  });
  promptPanel.addEventListener('input', validateHiresPrompt);
  promptPanel.addEventListener('focusin', fitMobileViewport);
  promptPanel.addEventListener('focusout', () => queueMicrotask(fitMobileViewport));
  window.visualViewport?.addEventListener('resize', fitMobileViewport);
  window.visualViewport?.addEventListener('scroll', fitMobileViewport);
  window.addEventListener('resize', fitMobileViewport);
  window.addEventListener('pageshow', fitMobileViewport);
  launch.addEventListener('click', open);
  byId('mobile-exit').addEventListener('click', close);
  D.showIIBDestination = () => {
    if (overlay.hidden) return;
    view.negative = false;
    view.hiresPrompt = false;
    renderPromptSide();
    selectTab('prompt');
  };
  toggleBar.addEventListener('click', () => setBarHidden(!view.barHidden));
  mode.addEventListener('change', () => {
    const next = mode.value;
    restoreControls();
    D.selectTab(next);
    mountControls();
    selectTab(view.tab);
  });
  window.onUiTabChange(() => {
    if (overlay.hidden || !mountedMode || switching) return;
    const tab = nativeTab();
    if (tab === mountedMode) return;
    if (tab !== 'txt2img' && tab !== 'img2img') {
      close();
      return;
    }
    restoreControls();
    mountControls();
    selectTab(view.tab);
  });
  for (const [index, tab] of tabs.entries()) {
    const name = tab.id.slice('mobile-tab-'.length);
    tab.addEventListener('click', () => {
      if (!overlay.hidden && !tab.disabled && view.tab !== name) selectTab(name);
    });
    tab.addEventListener('keydown', event => {
      const next = { ArrowLeft: (index + tabs.length - 1) % tabs.length, ArrowRight: (index + 1) % tabs.length, Home: 0, End: tabs.length - 1 }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      selectTab(tabs[next].id.slice(11), true);
    });
  }
  picker.addEventListener('change', () => selectPanel(picker.value));
  negativeToggle.addEventListener('click', () => {
    view.negative = !view.negative;
    renderPromptSide();
    selectTab('prompt');
  });
  clonePrompt.addEventListener('click', () => {
    const tab = mode.value;
    const regular = byId(promptId(tab, false, view.negative))?.querySelector('textarea');
    if (regular) D.setValue(promptId(tab, true, view.negative), regular.value);
  });
  hiresToggle.addEventListener('click', () => {
    view.hiresPrompt = !view.hiresPrompt;
    renderPromptSide();
    save();
  });
  loraHost.addEventListener('loraschange', renderLoras);
  promptPanel.addEventListener('input', () => { if (view.tab === 'loras') renderLoras(); });
  loraHost.addEventListener('click', () => setTimeout(renderLoras, 0));
  for (const input of [loraMin, loraMax]) {
    input.addEventListener('input', () => {
      loraMin.setCustomValidity('');
      loraMax.setCustomValidity('');
    });
    input.addEventListener('change', () => {
      const min = loraMin.valueAsNumber;
      const max = loraMax.valueAsNumber;
      if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) {
        input.setCustomValidity('Enter a minimum below the maximum.');
        input.reportValidity();
        input.setCustomValidity('');
        renderOptions();
        return;
      }
      view.loraMin = min;
      view.loraMax = max;
      for (const tab of ['txt2img', 'img2img']) {
        const enabled = D.loras.read(tab);
        let changed = false;
        for (const [name, weight] of enabled) {
          const value = Math.max(min, Math.min(max, weight));
          if (value === weight) continue;
          enabled.set(name, value);
          changed = true;
        }
        if (changed) D.loras.write(tab, enabled);
      }
      save();
    });
  }
  hiresInParams.addEventListener('change', () => {
    view.hiresInParams = hiresInParams.checked;
    restoreControls();
    mountControls();
    save();
  });
  for (const control of [showStyles, generateButton, promptExtras, enableHiresPrompt]) {
    control.addEventListener('change', () => {
      view.showStyles = showStyles.checked;
      view.generateButton = generateButton.value;
      view.promptExtras = promptExtras.checked;
      view.enableHiresPrompt = enableHiresPrompt.checked;
      if (!view.enableHiresPrompt) view.hiresPrompt = false;
      renderOptions();
      renderPromptSide();
      save();
    });
  }
  overlay.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !event.defaultPrevented) close();
    if (event.key !== 'Tab') return;
    const focusables = [...overlay.querySelectorAll('button, input, textarea, select, [tabindex]')]
      .filter(el => el.tabIndex >= 0 && !el.disabled && !el.closest('[inert]') && el.getClientRects().length);
    if (!focusables.length) return;
    const first = focusables[0], last = focusables.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  function toggleSplitLock() {
    view.locked = !view.locked;
    lastTap = null;
    renderSplit();
    save();
  }

  divider.addEventListener('pointerdown', event => {
    if (event.button !== 0 || gesture) return;
    const availableHeight = Math.max(1, layout.clientHeight - divider.offsetHeight);
    const visibleSplit = upper.getBoundingClientRect().height / availableHeight;
    gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, split: visibleSplit, start: event.timeStamp, moved: false };
    divider.setPointerCapture(event.pointerId);
  });
  divider.addEventListener('pointermove', event => {
    if (gesture?.id !== event.pointerId) return;
    const dy = event.clientY - gesture.y;
    if (Math.hypot(event.clientX - gesture.x, dy) > 5) gesture.moved = true;
    if (view.locked || !gesture.moved) return;
    window.ForgeMobileDockManager?.anchorWorkspace();
    view.split = clamp(gesture.split + dy / Math.max(1, layout.clientHeight - divider.offsetHeight));
    renderSplit();
  });
  function endDividerGesture(event) {
    if (gesture?.id !== event.pointerId) return;
    const { moved, start, x, y } = gesture;
    gesture = null;
    const isTap = event.type === 'pointerup' && !moved && event.timeStamp - start < 350
      && Math.hypot(event.clientX - x, event.clientY - y) <= 5;
    if (!isTap) {
      lastTap = null;
      save();
      return;
    }
    if (lastTap && event.timeStamp - lastTap.time <= 350 && Math.hypot(x - lastTap.x, y - lastTap.y) <= 28) {
      toggleSplitLock();
    } else {
      lastTap = { time: event.timeStamp, x, y };
    }
  }
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    divider.addEventListener(type, endDividerGesture);
  }
  divider.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (!event.repeat) toggleSplitLock();
      return;
    }
    if (view.locked) return;
    const next = { ArrowUp: view.split - .04, ArrowDown: view.split + .04, Home: .24, End: .76 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    window.ForgeMobileDockManager?.anchorWorkspace();
    view.split = clamp(next);
    renderSplit();
    save();
  });
  new MutationObserver(renderDocks).observe(canvas, { childList: true });
  promptPanel.addEventListener('input', fitPromptFields);
  new ResizeObserver(fitPromptFields).observe(topScroll);
  document.fonts?.ready.then(fitPromptFields);
  topScroll.addEventListener('scroll', schedulePromptSubtitle, { passive: true });
  promptPanel.addEventListener('input', schedulePromptSubtitle);
  const promptSubtitleObserver = new ResizeObserver(schedulePromptSubtitle);
  promptSubtitleObserver.observe(topScroll);
  new ResizeObserver(() => {
    upper.style.setProperty('--mobile-scrollbar-width', (topScroll.offsetWidth - topScroll.clientWidth) + 'px');
  }).observe(topScroll);
  promptSubtitleObserver.observe(promptPanel);
  const dockResizeObserver = new ResizeObserver(() => window.ForgeMobileDockManager?.repositionWorkspace());
  dockResizeObserver.observe(canvas);
  dockResizeObserver.observe(canvas.parentElement);
  renderOptions();
  renderPromptSide();
  renderBar();
  renderSplit();
  renderDocks();
  D.mobile = { open, close, showTab: selectTab, isOpen: () => !overlay.hidden };
  D.extensions["mobile-workspace"].mounted = true;
  document.dispatchEvent(new Event('forge-mobile-ready'));
})().catch(error => {
  console.error("Mobile workspace could not attach", error);
  window.MobileWorkspaceHost.notify("Mobile workspace could not attach to this Forge layout. See the browser console.");
});
