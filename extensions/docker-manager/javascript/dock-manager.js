(() => {
    "use strict";

    const EXT = "forge-dock-manager";
    const SHELL_CLASS = "fdm-dock-shell";
    const EDGE_GAP = 10;
    const TAP_WINDOW = 330;

    const registry = new Map();
    const modules = new Map();
    const instances = new Map();
    const moduleLoads = new Map();
    const loadedModuleFingerprints = new Map();
    const lifecycleSubscribers = new Set();
    const instanceOrdinals = new Map();

    // Python reads debug.json and exposes these values with the registry.
    // Production behavior remains one instance per dock unless this flag is enabled.
    const debugFlags = {
        allowMultipleInstances: false,
    };

    const THEME_VARIABLES = [
        "--body-text-color",
        "--body-text-color-subdued",
        "--background-fill-primary",
        "--background-fill-secondary",
        "--block-background-fill",
        "--block-border-color",
        "--block-shadow",
        "--border-color-primary",
        "--border-color-accent",
        "--input-border-color-focus",
        "--button-border-width",
        "--button-primary-background-fill",
        "--button-primary-background-fill-hover",
        "--button-primary-border-color",
        "--button-primary-border-color-hover",
        "--button-primary-text-color",
        "--button-primary-text-color-hover",
        "--button-primary-border-radius",
        "--button-primary-shadow",
        "--button-secondary-background-fill",
        "--button-secondary-background-fill-hover",
        "--button-secondary-border-color",
        "--button-secondary-border-color-hover",
        "--button-secondary-text-color",
        "--button-secondary-text-color-hover",
        "--button-secondary-border-radius",
        "--button-secondary-shadow",
        "--button-medium-text-size",
        "--button-medium-text-weight",
        "--radius-sm",
        "--radius-md",
        "--radius-lg",
    ];

    let registryRead = false;
    let registrySignature = "";
    let listenersInstalled = false;
    let docksLocked = false;
    let stateRestored = false;
    let restoringState = false;
    let saveTimer = null;
    let saveInFlight = false;
    let pendingSerializedState = null;
    let lastSerializedState = "";
    let safeInsets = { top: 0, right: 0, bottom: 0, left: 0 };

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function storageGet(key) {
        try {
            return localStorage.getItem(key);
        } catch (_error) {
            return null;
        }
    }

    function storageSet(key, value) {
        try {
            localStorage.setItem(key, value);
        } catch (_error) {
            // Storage can be unavailable in restrictive/private browser modes.
        }
    }

    function getRoot() {
        try {
            return typeof gradioApp === "function" ? gradioApp() : document;
        } catch (_error) {
            return document;
        }
    }

    function getById(id) {
        const root = getRoot();
        if (typeof root.getElementById === "function") return root.getElementById(id);
        return document.getElementById(id);
    }

    function isDisplayed(element) {
        return Boolean(element) && getComputedStyle(element).display !== "none";
    }

    function currentGenerationTab() {
        try {
            if (typeof get_uiCurrentTabContent === "function") {
                const tab = get_uiCurrentTabContent();
                if (tab?.id === "tab_txt2img") return "txt2img";
                if (tab?.id === "tab_img2img") return "img2img";
            }
        } catch (_error) {
            // Fall through to direct visibility checks.
        }

        const txt = getById("tab_txt2img");
        const img = getById("tab_img2img");
        if (txt && isDisplayed(txt)) return "txt2img";
        if (img && isDisplayed(img)) return "img2img";
        return null;
    }

    function nativeDockSelectForCurrentTab() {
        const tabName = currentGenerationTab();
        if (tabName) {
            const select = document.getElementById(`${tabName}_fdm_dock_native`);
            if (select) return select;
        }

        const selects = [...document.querySelectorAll(".fdm-native-dock-select")];
        return selects.find((select) => isDisplayed(select)) || selects[0] || null;
    }

    function nativeWidthSelectForCurrentTab() {
        const tabName = currentGenerationTab();
        if (tabName) {
            const select = document.getElementById(`${tabName}_fdm_width_native`);
            if (select) return select;
        }

        const selects = [...document.querySelectorAll(".fdm-native-width-select")];
        return selects.find((select) => isDisplayed(select)) || selects[0] || null;
    }

    function syncNativeDockSelects() {
        const docks = [...registry.values()];
        const validIds = new Set(docks.map((dock) => dock.id));

        for (const select of document.querySelectorAll(".fdm-native-dock-select")) {
            const previous = select.value;
            select.replaceChildren();

            for (const dock of docks) {
                const option = document.createElement("option");
                option.value = dock.id;
                option.textContent = dock.name || dock.id;
                select.appendChild(option);
            }

            if (validIds.has(previous)) select.value = previous;
            else if (docks.length) select.value = docks[0].id;

            select.disabled = docks.length === 0;
        }
    }

    function readRegistry() {
        const nodes = [...document.querySelectorAll("[data-fdm-registry]")];
        if (!nodes.length) return;

        let selected = null;
        let selectedRevision = -1;

        for (const node of nodes) {
            try {
                const raw = node.dataset.fdmRegistry || "{}";
                const parsed = JSON.parse(raw);
                const revision = Number(parsed?.revision) || 0;
                if (!selected || revision >= selectedRevision) {
                    selected = { raw, parsed };
                    selectedRevision = revision;
                }
            } catch (error) {
                console.warn(`[${EXT}] Ignoring invalid dock registry payload`, error);
            }
        }

        if (!selected) return;
        if (registryRead && selected.raw === registrySignature) return;

        try {
            const parsed = selected.parsed;
            const docks = Array.isArray(parsed) ? parsed : (Array.isArray(parsed?.docks) ? parsed.docks : []);
            const debug = !Array.isArray(parsed) && parsed?.debug ? parsed.debug : {};

            registry.clear();
            for (const item of docks) {
                if (item?.id) registry.set(item.id, item);
            }

            debugFlags.allowMultipleInstances = debug?.allow_multiple_instances === true;
            registrySignature = selected.raw;
            registryRead = true;
            syncNativeDockSelects();
        } catch (error) {
            console.error(`[${EXT}] Unable to read dock registry`, error);
        }
    }

    function applyRegistryPayload(parsed) {
        const docks = Array.isArray(parsed) ? parsed : (Array.isArray(parsed?.docks) ? parsed.docks : []);
        const debug = !Array.isArray(parsed) && parsed?.debug ? parsed.debug : {};

        registry.clear();
        for (const item of docks) {
            if (item?.id) registry.set(item.id, item);
        }

        debugFlags.allowMultipleInstances = debug?.allow_multiple_instances === true;
        const raw = JSON.stringify(parsed || {});
        registrySignature = raw;
        registryRead = true;

        // Keep both Gradio copies of the registry current so later
        // onAfterUiUpdate callbacks cannot overwrite this hot-refreshed state.
        for (const node of document.querySelectorAll("[data-fdm-registry]")) {
            node.dataset.fdmRegistry = raw;
        }

        syncNativeDockSelects();
    }

    async function fetchFreshRegistry() {
        const response = await fetch("/forge-dock-manager/registry", {
            method: "GET",
            cache: "no-store",
            headers: { "Accept": "application/json" },
        });
        if (!response.ok) throw new Error(`Registry GET failed with HTTP ${response.status}`);
        return response.json();
    }

    function dockFingerprint(manifest) {
        if (!manifest) return "";
        return String(manifest.content_hash || manifest.version || "") + "|"
            + String(manifest.script_url || "") + "|"
            + String(manifest.style_url || "");
    }

    function cacheBustedUrl(url, manifest) {
        if (!url) return url;
        const token = encodeURIComponent(String(manifest?.content_hash || manifest?.version || Date.now()));
        const separator = url.includes("?") ? "&" : "?";
        return `${url}${separator}fdm=${token}`;
    }

    async function fetchSavedState() {
        const response = await fetch("/forge-dock-manager/state", {
            method: "GET",
            cache: "no-store",
            headers: { "Accept": "application/json" },
        });

        if (!response.ok) {
            throw new Error(`State GET failed with HTTP ${response.status}`);
        }

        const parsed = await response.json();
        return {
            version: Number.isFinite(parsed?.version) ? parsed.version : 2,
            locked: parsed?.locked === true,
            docks: Array.isArray(parsed?.docks) ? parsed.docks : [],
        };
    }

    function serializeState() {
        const docks = [...instances.values()]
            .sort((a, b) => (a.ordinal - b.ordinal) || a.instanceKey.localeCompare(b.instanceKey))
            .map((instance) => ({
                instance_id: instance.instanceKey,
                dock_id: instance.dockId,
                width: instance.widthMode,
                side: instance.widthMode === "full" ? "center" : (instance.position.side || "right"),
                y: clamp(instance.position.y, 0, 1),
                ordinal: instance.ordinal || 1,
                labels: instance.labelsVisible === true,
            }));

        return JSON.stringify({ version: 2, locked: docksLocked, docks });
    }

    async function postSerializedState(serialized) {
        const response = await fetch("/forge-dock-manager/state", {
            method: "POST",
            cache: "no-store",
            keepalive: true,
            headers: {
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            body: serialized,
        });

        if (!response.ok) {
            throw new Error(`State POST failed with HTTP ${response.status}`);
        }

        const result = await response.json();
        if (result?.ok !== true) throw new Error("State POST was not accepted by Forge");
    }

    function flushStateSave() {
        saveTimer = null;
        if (restoringState) return;

        const serialized = serializeState();
        if (serialized === lastSerializedState && !saveInFlight) return;

        if (saveInFlight) {
            pendingSerializedState = serialized;
            return;
        }

        saveInFlight = true;
        pendingSerializedState = null;

        postSerializedState(serialized)
            .then(() => {
                lastSerializedState = serialized;
            })
            .catch((error) => {
                console.error(`[${EXT}] Unable to save dock state`, error);
                pendingSerializedState = pendingSerializedState || serialized;
            })
            .finally(() => {
                saveInFlight = false;
                if (pendingSerializedState && pendingSerializedState !== lastSerializedState) {
                    pendingSerializedState = null;
                    // Re-serialize before retrying so the newest in-memory layout wins.
                    scheduleStateSave(0);
                }
            });
    }

    function scheduleStateSave(delay = 60) {
        if (restoringState) return;
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(flushStateSave, delay);
    }

    function ensureStyle(url, dockId, manifest = null) {
        if (!url) return;
        const id = `fdm-style-${dockId}`;
        if (document.getElementById(id)) return;

        const link = document.createElement("link");
        link.id = id;
        link.rel = "stylesheet";
        link.href = cacheBustedUrl(url, manifest);
        link.dataset.fdmDockStyle = dockId;
        document.head.appendChild(link);
    }

    function ensureScript(url, dockId, manifest = null) {
        if (modules.has(dockId)) return Promise.resolve(modules.get(dockId));
        if (moduleLoads.has(dockId)) return moduleLoads.get(dockId);

        const promise = new Promise((resolve, reject) => {
            const script = document.createElement("script");
            script.src = cacheBustedUrl(url, manifest);
            script.async = true;
            script.dataset.fdmDockScript = dockId;
            script.onload = () => {
                const definition = modules.get(dockId);
                if (definition) resolve(definition);
                else reject(new Error(`Dock '${dockId}' loaded but did not register itself`));
            };
            script.onerror = () => reject(new Error(`Unable to load dock script: ${url}`));
            document.head.appendChild(script);
        }).finally(() => moduleLoads.delete(dockId));

        moduleLoads.set(dockId, promise);
        return promise;
    }

    function unloadDockModule(dockId) {
        moduleLoads.delete(dockId);
        loadedModuleFingerprints.delete(dockId);
        modules.delete(dockId);

        for (const node of document.querySelectorAll("script[data-fdm-dock-script]")) {
            if (node.dataset.fdmDockScript === dockId) node.remove();
        }

        const style = document.getElementById(`fdm-style-${dockId}`);
        style?.remove();
        for (const node of document.querySelectorAll("link[data-fdm-dock-style]")) {
            if (node.dataset.fdmDockStyle === dockId) node.remove();
        }
    }

    async function loadDock(dockId) {
        readRegistry();
        const manifest = registry.get(dockId);
        if (!manifest) throw new Error(`Unknown dock '${dockId}'`);

        if (modules.has(dockId)) {
            if (!loadedModuleFingerprints.has(dockId)) {
                loadedModuleFingerprints.set(dockId, dockFingerprint(manifest));
            }
            return modules.get(dockId);
        }

        ensureStyle(manifest.style_url, dockId, manifest);
        const definition = await ensureScript(manifest.script_url, dockId, manifest);
        loadedModuleFingerprints.set(dockId, dockFingerprint(manifest));
        return definition;
    }

    function themeSource() {
        const root = getRoot();
        return root.querySelector?.(".gradio-container")
            || document.querySelector(".gradio-container")
            || null;
    }

    function syncTheme(instance) {
        if (!instance?.shell?.isConnected) return;
        const source = themeSource();
        if (!source) return;

        const computed = getComputedStyle(source);
        for (const variable of THEME_VARIABLES) {
            const value = computed.getPropertyValue(variable).trim();
            if (value) instance.shell.style.setProperty(variable, value);
            else instance.shell.style.removeProperty(variable);
        }
    }

    function viewportRect() {
        const vv = window.visualViewport;
        if (vv) {
            return {
                left: vv.offsetLeft || 0,
                top: vv.offsetTop || 0,
                width: vv.width || window.innerWidth,
                height: vv.height || window.innerHeight,
            };
        }

        return {
            left: 0,
            top: 0,
            width: window.innerWidth || document.documentElement.clientWidth,
            height: window.innerHeight || document.documentElement.clientHeight,
        };
    }

    function measureSafeArea() {
        if (!document.body) return;
        const probe = document.createElement("div");
        probe.setAttribute("aria-hidden", "true");
        probe.style.cssText = [
            "position:fixed",
            "visibility:hidden",
            "pointer-events:none",
            "top:0",
            "left:0",
            "padding-top:env(safe-area-inset-top, 0px)",
            "padding-right:env(safe-area-inset-right, 0px)",
            "padding-bottom:env(safe-area-inset-bottom, 0px)",
            "padding-left:env(safe-area-inset-left, 0px)",
        ].join(";");
        document.body.appendChild(probe);
        const style = getComputedStyle(probe);
        safeInsets = {
            top: Number.parseFloat(style.paddingTop) || 0,
            right: Number.parseFloat(style.paddingRight) || 0,
            bottom: Number.parseFloat(style.paddingBottom) || 0,
            left: Number.parseFloat(style.paddingLeft) || 0,
        };
        probe.remove();
    }

    function positionKey(instanceKey) {
        return `forge-dock-manager:${instanceKey}:position-v1`;
    }

    function readPosition(instanceKey, dockId, ordinal) {
        // Duplicate instances are a debug feature. Cascade their initial position
        // so they do not open perfectly on top of one another.
        const fallback = {
            side: ordinal % 2 === 0 ? "left" : "right",
            y: clamp(1 - Math.max(0, ordinal - 1) * 0.16, 0.12, 1),
        };
        const raw = storageGet(positionKey(instanceKey));
        if (!raw) return fallback;

        try {
            const parsed = JSON.parse(raw);
            return {
                side: parsed?.side === "left" ? "left" : "right",
                y: Number.isFinite(parsed?.y) ? clamp(parsed.y, 0, 1) : 1,
            };
        } catch (_error) {
            return fallback;
        }
    }

    function savePosition(instance) {
        storageSet(positionKey(instance.instanceKey), JSON.stringify(instance.position));
    }

    function geometry(instance) {
        const viewport = viewportRect();
        const horizontalGap = Math.max(EDGE_GAP, safeInsets.left + 6, safeInsets.right + 6);
        const topGap = Math.max(EDGE_GAP, safeInsets.top + 6);
        const bottomGap = Math.max(EDGE_GAP, safeInsets.bottom + 6);
        const usableWidth = Math.max(160, viewport.width - horizontalGap * 2);
        const width = instance.widthMode === "full"
            ? usableWidth
            : Math.max(150, (usableWidth - horizontalGap) / 2);

        const shellHeight = instance.shell.getBoundingClientRect().height || instance.shell.offsetHeight || 130;
        const minBottomEdge = Math.min(viewport.height - bottomGap, topGap + shellHeight);
        const maxBottomEdge = Math.max(minBottomEdge, viewport.height - bottomGap);

        return {
            viewport,
            horizontalGap,
            topGap,
            bottomGap,
            width,
            shellHeight,
            minBottomEdge,
            maxBottomEdge,
        };
    }

    function applyPosition(instance) {
        if (!instance?.shell?.isConnected || instance.drag) return;

        const g = geometry(instance);
        const shell = instance.shell;
        const y = clamp(instance.position.y, 0, 1);
        const bottomEdge = g.minBottomEdge + y * (g.maxBottomEdge - g.minBottomEdge);
        const bottom = Math.max(g.bottomGap, g.viewport.height - bottomEdge + g.viewport.top);

        shell.style.width = `${g.width}px`;
        shell.style.top = "auto";
        shell.style.bottom = `${bottom}px`;

        if (instance.widthMode === "full") {
            shell.style.left = `${g.viewport.left + (g.viewport.width - g.width) / 2}px`;
            shell.style.right = "auto";
            shell.dataset.side = "center";
            shell.style.transformOrigin = "bottom center";
        } else if (instance.position.side === "left") {
            shell.style.left = `${g.viewport.left + g.horizontalGap}px`;
            shell.style.right = "auto";
            shell.dataset.side = "left";
            shell.style.transformOrigin = "bottom left";
        } else {
            shell.style.left = "auto";
            shell.style.right = `${g.horizontalGap}px`;
            shell.dataset.side = "right";
            shell.style.transformOrigin = "bottom right";
        }
    }

    function queuePosition(instance) {
        if (!instance || instance.positionQueued) return;
        instance.positionQueued = true;
        requestAnimationFrame(() => {
            instance.positionQueued = false;
            requestAnimationFrame(() => applyPosition(instance));
        });
    }

    function lockCheckboxInputs() {
        const inputs = [];
        for (const tabName of ["txt2img", "img2img"]) {
            const root = getById(`${tabName}_fdm_lock_docks`) || document.getElementById(`${tabName}_fdm_lock_docks`);
            if (!root) continue;
            const input = root.matches?.('input[type="checkbox"]')
                ? root
                : root.querySelector?.('input[type="checkbox"]');
            if (input) inputs.push(input);
        }
        return inputs;
    }

    function syncLockCheckboxes() {
        for (const input of lockCheckboxInputs()) {
            if (input.checked === docksLocked) continue;
            const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "checked");
            if (descriptor?.set) descriptor.set.call(input, docksLocked);
            else input.checked = docksLocked;
        }
    }

    function applyDockLockToInstance(instance) {
        if (!instance?.shell) return;
        instance.shell.dataset.locked = docksLocked ? "true" : "false";
        instance.handle.setAttribute("aria-disabled", docksLocked ? "true" : "false");
        instance.handle.setAttribute(
            "aria-label",
            docksLocked
                ? "Dock position locked"
                : "Move dock. Double tap swaps sides in half width. Triple tap closes the dock.",
        );
        instance.handle.tabIndex = docksLocked ? -1 : 0;
        instance.handle.title = docksLocked
            ? "Docks locked"
            : "Drag to move · double tap to swap sides · triple tap to close";

        if (docksLocked && instance.drag) {
            try { instance.handle.releasePointerCapture?.(instance.drag.pointerId); } catch (_error) { /* noop */ }
            instance.drag = null;
            delete instance.shell.dataset.dragging;
        }
        queuePosition(instance);
    }

    function applyDockLockState() {
        for (const instance of instances.values()) applyDockLockToInstance(instance);
        syncLockCheckboxes();
    }

    function setDocksLocked(locked, options = {}) {
        const next = locked === true;
        if (docksLocked === next) {
            applyDockLockState();
            return;
        }
        docksLocked = next;
        applyDockLockState();
        if (options.persist !== false) scheduleStateSave(0);
    }

    function installLockCheckboxListeners() {
        for (const input of lockCheckboxInputs()) {
            if (input.dataset.fdmLockBound === "true") continue;
            input.dataset.fdmLockBound = "true";
            input.addEventListener("change", () => setDocksLocked(input.checked));
        }
        syncLockCheckboxes();
    }

    function closeDock(instanceKey, options = {}) {
        const instance = instances.get(instanceKey);
        if (!instance) return;

        if (instance.tapTimer) clearTimeout(instance.tapTimer);
        try {
            instance.definition.unmount?.(instance.content, instance.context);
        } catch (error) {
            console.warn(`[${EXT}] Dock '${instance.dockId}' unmount failed`, error);
        }
        for (const cleanup of instance.cleanups.splice(0)) {
            try { cleanup(); } catch (_error) { /* ignore isolated cleanup failures */ }
        }
        instance.shell.remove();
        instances.delete(instanceKey);
        if (options.persist !== false) scheduleStateSave();
    }

    function closeAllDocks(options = {}) {
        const keys = [...instances.keys()];
        for (const instanceKey of keys) {
            closeDock(instanceKey, { persist: false });
        }

        if (options.persist !== false) {
            scheduleStateSave(0);
        }
    }

    function processHandleTap(instance) {
        if (docksLocked) return;
        instance.tapCount += 1;

        if (instance.tapCount >= 3) {
            clearTimeout(instance.tapTimer);
            instance.tapTimer = null;
            instance.tapCount = 0;
            closeDock(instance.instanceKey);
            return;
        }

        clearTimeout(instance.tapTimer);
        instance.tapTimer = setTimeout(() => {
            if (instance.tapCount === 2 && instance.widthMode === "half") {
                instance.position.side = instance.position.side === "left" ? "right" : "left";
                savePosition(instance);
                queuePosition(instance);
                scheduleStateSave();
            }
            instance.tapCount = 0;
            instance.tapTimer = null;
        }, TAP_WINDOW);
    }

    function beginDrag(instance, event) {
        if (docksLocked || event.button > 0) return;
        event.preventDefault();

        const rect = instance.shell.getBoundingClientRect();
        instance.drag = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            offsetX: event.clientX - rect.left,
            offsetY: event.clientY - rect.top,
            moved: false,
        };

        instance.handle.setPointerCapture?.(event.pointerId);
        instance.shell.dataset.dragging = "true";
        instance.shell.style.left = `${rect.left}px`;
        instance.shell.style.right = "auto";
        instance.shell.style.top = `${rect.top}px`;
        instance.shell.style.bottom = "auto";
        instance.shell.style.transformOrigin = "top left";
    }

    function moveDrag(instance, event) {
        const drag = instance.drag;
        if (!drag || event.pointerId !== drag.pointerId) return;
        event.preventDefault();

        if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) > 5) drag.moved = true;

        const g = geometry(instance);
        const rect = instance.shell.getBoundingClientRect();
        const wantedTop = event.clientY - drag.offsetY;
        const minTop = g.viewport.top + g.topGap;
        const maxTop = g.viewport.top + g.viewport.height - g.bottomGap - rect.height;

        instance.shell.style.top = `${clamp(wantedTop, minTop, Math.max(minTop, maxTop))}px`;

        if (instance.widthMode === "full") {
            instance.shell.style.left = `${g.viewport.left + (g.viewport.width - g.width) / 2}px`;
        } else {
            const wantedLeft = event.clientX - drag.offsetX;
            const minLeft = g.viewport.left + g.horizontalGap;
            const maxLeft = g.viewport.left + g.viewport.width - g.horizontalGap - rect.width;
            instance.shell.style.left = `${clamp(wantedLeft, minLeft, Math.max(minLeft, maxLeft))}px`;
        }
    }

    function endDrag(instance, event, cancelled = false) {
        const drag = instance.drag;
        if (!drag || event.pointerId !== drag.pointerId) return;

        try { instance.handle.releasePointerCapture?.(event.pointerId); } catch (_error) { /* noop */ }
        instance.drag = null;
        delete instance.shell.dataset.dragging;

        if (cancelled) {
            queuePosition(instance);
            return;
        }

        if (!drag.moved) {
            processHandleTap(instance);
            queuePosition(instance);
            return;
        }

        const g = geometry(instance);
        const rect = instance.shell.getBoundingClientRect();
        const range = Math.max(1, g.maxBottomEdge - g.minBottomEdge);
        const viewportBottom = rect.bottom - g.viewport.top;

        instance.position.y = clamp((viewportBottom - g.minBottomEdge) / range, 0, 1);
        if (instance.widthMode === "half") {
            instance.position.side = rect.left + rect.width / 2 < g.viewport.left + g.viewport.width / 2
                ? "left"
                : "right";
        }

        savePosition(instance);
        queuePosition(instance);
        scheduleStateSave();
    }

    function createContext(instance) {
        return {
            dockId: instance.dockId,
            instanceId: instance.instanceKey,
            get widthMode() { return instance.widthMode; },
            get labelsVisible() { return instance.labelsVisible; },
            get shell() { return instance.shell; },
            getById,
            isDisplayed,
            currentGenerationTab,
            close: () => closeDock(instance.instanceKey),
            requestPosition: () => queuePosition(instance),
            setVisible: (visible) => {
                instance.shell.dataset.moduleVisible = visible ? "true" : "false";
            },
            onLifecycle(callback) {
                lifecycleSubscribers.add(callback);
                const cleanup = () => lifecycleSubscribers.delete(callback);
                instance.cleanups.push(cleanup);
                return cleanup;
            },
        };
    }

    function createShell(dockId, instanceKey, ordinal, widthMode, labelsVisible, definition, initialPosition = null) {
        const shell = document.createElement("div");
        shell.className = SHELL_CLASS;
        shell.dataset.dockId = dockId;
        shell.dataset.instanceId = instanceKey;
        shell.dataset.width = widthMode;
        shell.dataset.labels = labelsVisible ? "true" : "false";
        shell.dataset.moduleVisible = "true";
        shell.dataset.locked = docksLocked ? "true" : "false";
        shell.setAttribute("role", "region");
        shell.setAttribute("aria-label", definition.name || dockId);

        const handle = document.createElement("div");
        handle.className = "fdm-dock-handle";
        handle.tabIndex = 0;
        handle.setAttribute("role", "button");
        handle.setAttribute(
            "aria-label",
            "Move dock. Double tap swaps sides in half width. Triple tap closes the dock.",
        );
        handle.title = "Drag to move · double tap to swap sides · triple tap to close";

        const content = document.createElement("div");
        content.className = "fdm-dock-content";

        shell.append(handle, content);
        document.body.appendChild(shell);

        const instance = {
            dockId,
            instanceKey,
            ordinal,
            widthMode,
            labelsVisible,
            definition,
            shell,
            handle,
            content,
            position: initialPosition || readPosition(instanceKey, dockId, ordinal),
            positionQueued: false,
            drag: null,
            tapCount: 0,
            tapTimer: null,
            cleanups: [],
            context: null,
        };
        instance.context = createContext(instance);
        syncTheme(instance);
        applyDockLockToInstance(instance);

        handle.addEventListener("pointerdown", (event) => beginDrag(instance, event));
        handle.addEventListener("pointermove", (event) => moveDrag(instance, event));
        handle.addEventListener("pointerup", (event) => endDrag(instance, event));
        handle.addEventListener("pointercancel", (event) => endDrag(instance, event, true));
        handle.addEventListener("keydown", (event) => {
            if (!docksLocked && (event.key === "Enter" || event.key === " ") && instance.widthMode === "half") {
                event.preventDefault();
                instance.position.side = instance.position.side === "left" ? "right" : "left";
                savePosition(instance);
                queuePosition(instance);
                scheduleStateSave();
            }
        });

        return instance;
    }

    function instancesForDock(dockId) {
        return [...instances.values()].filter((instance) => instance.dockId === dockId);
    }

    function nextInstanceIdentity(dockId, restored = null) {
        if (!debugFlags.allowMultipleInstances) {
            return { instanceKey: dockId, ordinal: 1 };
        }

        if (restored?.instanceKey) {
            const ordinal = Math.max(1, Number.parseInt(restored.ordinal, 10) || 1);
            instanceOrdinals.set(dockId, Math.max(instanceOrdinals.get(dockId) || 0, ordinal));
            return { instanceKey: restored.instanceKey, ordinal };
        }

        const ordinal = (instanceOrdinals.get(dockId) || 0) + 1;
        instanceOrdinals.set(dockId, ordinal);
        return { instanceKey: `${dockId}#${ordinal}`, ordinal };
    }

    async function openDock(dockId, requestedWidth, options = {}) {
        if (!dockId) return;
        readRegistry();

        try {
            const manifest = registry.get(dockId);
            if (!manifest) throw new Error(`Dock '${dockId}' is not registered by Python`);

            const allowed = Array.isArray(manifest.allowed_widths) ? manifest.allowed_widths : ["half", "full"];
            const widthMode = allowed.includes(requestedWidth)
                ? requestedWidth
                : (manifest.default_width || allowed[0] || "half");
            const labelsVisible = options.labelsVisible === true;

            if (!debugFlags.allowMultipleInstances) {
                const existing = instancesForDock(dockId)[0];
                if (existing) {
                    existing.widthMode = widthMode;
                    existing.labelsVisible = labelsVisible;
                    existing.shell.dataset.width = widthMode;
                    existing.shell.dataset.labels = labelsVisible ? "true" : "false";
                    if (options.position) existing.position = { ...existing.position, ...options.position };
                    syncTheme(existing);
                    queuePosition(existing);
                    existing.definition.onOpen?.(existing.content, existing.context);
                    if (options.persist !== false) scheduleStateSave();
                    return existing;
                }
            }

            const definition = await loadDock(dockId);
            const identity = nextInstanceIdentity(dockId, options.restore ? {
                instanceKey: options.instanceKey,
                ordinal: options.ordinal,
            } : null);
            const initialPosition = options.position ? {
                side: options.position.side === "left" ? "left" : "right",
                y: Number.isFinite(options.position.y) ? clamp(options.position.y, 0, 1) : 1,
            } : null;
            const instance = createShell(
                dockId,
                identity.instanceKey,
                identity.ordinal,
                widthMode,
                labelsVisible,
                definition,
                initialPosition,
            );
            instances.set(identity.instanceKey, instance);

            try {
                definition.mount?.(instance.content, instance.context);
            } catch (error) {
                closeDock(identity.instanceKey, { persist: false });
                throw error;
            }

            queuePosition(instance);
            if (options.persist !== false) scheduleStateSave();
            return instance;
        } catch (error) {
            console.error(`[${EXT}] Unable to open dock '${dockId}'`, error);
            return null;
        }
    }

    async function restoreSavedState() {
        if (stateRestored) return;
        stateRestored = true;
        readRegistry();

        const saved = await fetchSavedState();
        setDocksLocked(saved?.locked === true, { persist: false });
        const docks = Array.isArray(saved?.docks) ? saved.docks : [];
        if (!docks.length) {
            lastSerializedState = serializeState();
            return;
        }

        restoringState = true;
        try {
            const restoredDockIds = new Set();
            for (const item of docks) {
                const dockId = String(item?.dock_id || "").trim();
                if (!dockId || !registry.has(dockId)) continue;
                if (!debugFlags.allowMultipleInstances && restoredDockIds.has(dockId)) continue;

                const width = item?.width === "full" ? "full" : "half";
                const side = item?.side === "left" ? "left" : "right";
                const y = Number.isFinite(item?.y) ? item.y : Number.parseFloat(item?.y);
                const position = { side, y: Number.isFinite(y) ? clamp(y, 0, 1) : 1 };
                const instanceId = String(item?.instance_id || dockId).trim() || dockId;
                const ordinal = Math.max(1, Number.parseInt(item?.ordinal, 10) || 1);
                const labelsVisible = item?.labels === true;

                await openDock(dockId, width, {
                    restore: true,
                    instanceKey: instanceId,
                    ordinal,
                    position,
                    labelsVisible,
                    persist: false,
                });
                restoredDockIds.add(dockId);
            }
        } finally {
            restoringState = false;
            lastSerializedState = serializeState();
        }
    }

    function snapshotDockInstance(instance) {
        return {
            dockId: instance.dockId,
            instanceKey: instance.instanceKey,
            ordinal: instance.ordinal,
            widthMode: instance.widthMode,
            labelsVisible: instance.labelsVisible === true,
            position: {
                side: instance.position?.side === "left" ? "left" : "right",
                y: Number.isFinite(instance.position?.y) ? clamp(instance.position.y, 0, 1) : 1,
            },
        };
    }

    async function fullRefreshDocks() {
        readRegistry();
        const before = new Map(registry);
        const freshPayload = await fetchFreshRegistry();
        const freshDocks = Array.isArray(freshPayload?.docks) ? freshPayload.docks : [];
        const after = new Map(freshDocks.filter(Boolean).map((dock) => [dock.id, dock]));

        const added = new Set();
        const removed = new Set();
        const changed = new Set();

        for (const [dockId, manifest] of after) {
            if (!before.has(dockId)) {
                added.add(dockId);
                continue;
            }

            const freshFingerprint = dockFingerprint(manifest);
            const registryChanged = dockFingerprint(before.get(dockId)) !== freshFingerprint;
            const loadedFingerprint = loadedModuleFingerprints.get(dockId);
            const loadedCodeChanged = modules.has(dockId)
                && loadedFingerprint
                && loadedFingerprint !== freshFingerprint;

            if (registryChanged || loadedCodeChanged) changed.add(dockId);
        }
        for (const dockId of before.keys()) {
            if (!after.has(dockId)) removed.add(dockId);
        }

        const affected = new Set([...changed, ...removed]);
        const snapshots = [...instances.values()]
            .filter((instance) => affected.has(instance.dockId))
            .map(snapshotDockInstance);

        // Tear down using the old definitions so each module gets its normal cleanup.
        for (const snapshot of snapshots) {
            closeDock(snapshot.instanceKey, { persist: false });
        }
        for (const dockId of affected) unloadDockModule(dockId);

        applyRegistryPayload(freshPayload);

        let reopened = 0;
        let failed = 0;
        for (const snapshot of snapshots) {
            if (!after.has(snapshot.dockId)) continue;
            const instance = await openDock(snapshot.dockId, snapshot.widthMode, {
                restore: true,
                instanceKey: snapshot.instanceKey,
                ordinal: snapshot.ordinal,
                position: snapshot.position,
                labelsVisible: snapshot.labelsVisible,
                persist: false,
            });
            if (instance) reopened += 1;
            else failed += 1;
        }

        scheduleStateSave(0);
        notifyLifecycle();

        return {
            added: added.size,
            changed: changed.size,
            removed: removed.size,
            reopened,
            failed,
        };
    }

    function notifyLifecycle() {
        readRegistry();
        installLockCheckboxListeners();
        for (const instance of instances.values()) {
            syncTheme(instance);
            applyDockLockToInstance(instance);
        }
        for (const callback of [...lifecycleSubscribers]) {
            try { callback(); } catch (error) {
                console.warn(`[${EXT}] Dock lifecycle callback failed`, error);
            }
        }
    }

    function installListeners() {
        if (listenersInstalled) return;
        listenersInstalled = true;

        const repositionAll = () => {
            for (const instance of instances.values()) queuePosition(instance);
        };

        window.addEventListener("resize", repositionAll, { passive: true });
        window.addEventListener("orientationchange", () => {
            setTimeout(() => {
                measureSafeArea();
                repositionAll();
            }, 100);
        });

        if (window.visualViewport) {
            window.visualViewport.addEventListener("resize", repositionAll, { passive: true });
            window.visualViewport.addEventListener("scroll", repositionAll, { passive: true });
        }

        window.addEventListener("pagehide", () => {
            if (!restoringState && serializeState() !== lastSerializedState) {
                // keepalive lets the final small JSON write survive a mobile page close/background.
                postSerializedState(serializeState()).catch(() => {});
            }
        });
    }

    function registerDock(definition) {
        if (!definition?.id) throw new Error("Dock definition requires an id");
        modules.set(definition.id, definition);
    }

    window.ForgeDockManager = {
        registerDock,
        openDock,
        closeDock,
        closeAllDocks,
        fullRefreshDocks,
        setDocksLocked,
        getById,
        currentGenerationTab,
        debug: debugFlags,
    };

    window.fdmOpenDock = (labelsVisible) => {
        const dockSelect = nativeDockSelectForCurrentTab();
        const widthSelect = nativeWidthSelectForCurrentTab();
        const dockId = dockSelect?.value || "";
        const widthMode = widthSelect?.value === "full" ? "full" : "half";
        if (!dockId) return;
        openDock(dockId, widthMode, { labelsVisible: labelsVisible === true });
    };

    window.fdmCloseAllDocks = () => {
        closeAllDocks();
    };

    function fullRefreshButtonForCurrentTab() {
        const tabName = currentGenerationTab();
        const ids = tabName
            ? [`${tabName}_fdm_full_refresh`]
            : ["txt2img_fdm_full_refresh", "img2img_fdm_full_refresh"];

        for (const id of ids) {
            const root = getById(id) || document.getElementById(id);
            if (!root) continue;
            if (root.tagName === "BUTTON") return root;
            const button = root.querySelector?.("button");
            if (button) return button;
        }
        return null;
    }

    window.fdmFullRefreshDocks = () => {
        const button = fullRefreshButtonForCurrentTab();
        const originalText = button?.textContent || "Full Dock Refresh";
        if (button) {
            button.disabled = true;
            button.textContent = "Refreshing Docks…";
        }

        fullRefreshDocks()
            .then((result) => {
                console.info(`[${EXT}] Full dock refresh complete`, result);
                if (button) {
                    const changedCount = result.added + result.changed + result.removed;
                    button.textContent = changedCount
                        ? `Refreshed: +${result.added} ~${result.changed} −${result.removed}`
                        : "Docks Already Current";
                }
            })
            .catch((error) => {
                console.error(`[${EXT}] Full dock refresh failed`, error);
                if (button) button.textContent = "Dock Refresh Failed";
            })
            .finally(() => {
                if (!button) return;
                setTimeout(() => {
                    button.disabled = false;
                    button.textContent = originalText;
                }, 1500);
            });
    };

    function initialize() {
        readRegistry();
        measureSafeArea();
        installListeners();
        notifyLifecycle();
        installLockCheckboxListeners();
        restoreSavedState().then(notifyLifecycle).catch((error) => {
            console.error(`[${EXT}] Failed to restore saved dock state`, error);
        });
    }

    if (typeof onUiLoaded === "function") {
        onUiLoaded(initialize);
        if (typeof onUiTabChange === "function") onUiTabChange(notifyLifecycle);
        if (typeof onAfterUiUpdate === "function") onAfterUiUpdate(notifyLifecycle);
    } else {
        window.addEventListener("load", initialize, { once: true });
    }
})();
