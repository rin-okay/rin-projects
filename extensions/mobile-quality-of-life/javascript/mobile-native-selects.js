(() => {
    "use strict";

    const EXT = "rin-tools/native-selects";
    const MOBILE_MAX_WIDTH = 900;

    const SPECS = [
        { key: "txt2img-sampler", elemIds: ["txt2img_sampling"], fallbackLabel: "Sampling Method" },
        { key: "img2img-sampler", elemIds: ["img2img_sampling"], fallbackLabel: "Sampling Method" },
        { key: "txt2img-scheduler", elemIds: ["txt2img_scheduler"], fallbackLabel: "Schedule Type" },
        { key: "img2img-scheduler", elemIds: ["img2img_scheduler"], fallbackLabel: "Schedule Type" },
        { key: "txt2img-hr-sampler", elemIds: ["hr_sampler", "txt2img_hr_sampler"], fallbackLabel: "Hires sampling method" },
        { key: "txt2img-hr-scheduler", elemIds: ["hr_scheduler", "txt2img_hr_scheduler"], fallbackLabel: "Hires schedule type" },
        { key: "txt2img-hr-upscaler", elemIds: ["txt2img_hr_upscaler", "hr_upscaler"], fallbackLabel: "Upscaler" },
        { key: "img2img-hr-sampler", elemIds: ["img2img_hr_sampler", "img2img_hires_sampler", "img2img_hr_sampler_name"], fallbackLabel: "Hires sampling method" },
        { key: "img2img-hr-scheduler", elemIds: ["img2img_hr_scheduler", "img2img_hires_scheduler"], fallbackLabel: "Hires schedule type" },
        { key: "img2img-hr-upscaler", elemIds: ["img2img_hr_upscaler", "img2img_hires_upscaler"], fallbackLabel: "Upscaler" },
    ];

    let listenersInstalled = false;
    let syncQueued = false;

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

    function isMobileViewport() {
        const width = window.visualViewport?.width || window.innerWidth || document.documentElement.clientWidth || 0;
        const mobileUA = /iPhone|iPad|iPod|Android|Mobile/i.test(navigator.userAgent || "");
        return width <= MOBILE_MAX_WIDTH || mobileUA;
    }

    function inputsInside(component) {
        if (!component) return [];
        if (component.matches?.("input")) return [component];
        return [...(component.querySelectorAll?.("input") || [])];
    }

    function dropdownInput(component) {
        if (!component) return null;
        if (component.matches?.('input[role="listbox"], input')) return component;
        return component.querySelector?.('input[role="listbox"], input') || null;
    }

    function directChildContaining(root, node) {
        if (!root || !node) return null;
        let current = node;
        while (current && current.parentElement && current.parentElement !== root) {
            current = current.parentElement;
        }
        return current && current.parentElement === root ? current : null;
    }

    function configObjects() {
        const objects = [];
        if (window.gradio_config) objects.push(window.gradio_config);
        if (window.__gradio_config__) objects.push(window.__gradio_config__);
        try {
            const app = typeof gradioApp === "function" ? gradioApp() : null;
            if (app?.config) objects.push(app.config);
        } catch (_error) {
            // no-op
        }
        return objects;
    }

    function configuredChoices(elemId) {
        for (const config of configObjects()) {
            const components = Array.isArray(config?.components) ? config.components : [];
            const found = components.find((component) => component?.props?.elem_id === elemId);
            const choices = found?.props?.choices;
            if (!Array.isArray(choices)) continue;

            return choices.map((choice) => {
                if (Array.isArray(choice)) {
                    return { label: String(choice[0]), value: String(choice[1]) };
                }
                return { label: String(choice), value: String(choice) };
            });
        }
        return [];
    }

    function renderedChoices(component) {
        if (!component) return [];
        return [...(component.querySelectorAll?.('ul.options li.item, li[data-testid="dropdown-option"]') || [])]
            .map((item) => {
                const label = item.getAttribute("aria-label") || item.textContent?.replace("✓", "").trim();
                return label ? { label, value: label } : null;
            })
            .filter(Boolean);
    }

    function readLabelText(component, fallbackLabel) {
        if (!component) return fallbackLabel || "";

        const fromLabel = component.querySelector?.("label span, label");
        const labelText = fromLabel?.textContent?.trim();
        if (labelText) return labelText;

        const input = dropdownInput(component);
        const aria = input?.getAttribute?.("aria-label")?.trim();
        if (aria) return aria;

        return fallbackLabel || component.id || "";
    }

    function populateSelect(select, component) {
        if (!component || !select) return;

        let choices = configuredChoices(component.id || "");
        if (!choices.length) choices = renderedChoices(component);

        const input = dropdownInput(component);
        const current = input?.value || "";
        if (!choices.length && current) choices = [{ label: current, value: current }];

        const existingSignature = [...select.options].map((option) => `${option.textContent}\u0000${option.value}`).join("\u0001");
        const nextSignature = choices.map((choice) => `${choice.label}\u0000${choice.value}`).join("\u0001");

        if (existingSignature !== nextSignature) {
            select.replaceChildren(...choices.map((choice) => {
                const option = document.createElement("option");
                option.textContent = choice.label;
                option.value = choice.value;
                return option;
            }));
        }

        if (current) {
            const match = [...select.options].find((option) => option.value === current || option.textContent === current);
            if (match) select.value = match.value;
        } else if (select.options.length) {
            select.selectedIndex = 0;
        }

        select.disabled = Boolean(input?.disabled) || select.options.length === 0;
    }

    function setInputValue(input, value) {
        if (!input) return;
        const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
        if (descriptor?.set) descriptor.set.call(input, value);
        else input.value = value;
    }

    function setNativeDropdown(component, selectedValue, selectedLabel) {
        const input = dropdownInput(component);
        if (!input) return;

        const target = selectedLabel || selectedValue;
        setInputValue(input, target);
        input.dispatchEvent(new Event("input", { bubbles: true }));

        requestAnimationFrame(() => {
            input.dispatchEvent(new KeyboardEvent("keydown", {
                key: "Enter",
                code: "Enter",
                bubbles: true,
                cancelable: true,
            }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
            input.dispatchEvent(new Event("blur", { bubbles: true }));
        });
    }

    function queueSync() {
        if (syncQueued) return;
        syncQueued = true;
        requestAnimationFrame(() => {
            syncQueued = false;
            syncAll();
        });
    }

    function cleanupComponent(component) {
        if (!component?._fmnsProxy) return;

        const proxy = component._fmnsProxy;
        for (const { node, type, handler } of proxy.bound || []) {
            node.removeEventListener(type, handler);
        }

        proxy.host?.remove();
        proxy.controlWrapper?.classList.remove("fmns-source-hidden");
        component.classList.remove("fmns-native-replaced");
        delete component._fmnsProxy;
    }

    function cleanupAll() {
        for (const spec of SPECS) {
            for (const id of spec.elemIds) {
                const component = getById(id);
                cleanupComponent(component);
            }
        }

        for (const orphan of document.querySelectorAll(".fmns-native-select-host")) {
            orphan.remove();
        }
        for (const hidden of document.querySelectorAll(".fmns-source-hidden")) {
            hidden.classList.remove("fmns-source-hidden");
        }
        for (const root of document.querySelectorAll(".fmns-native-replaced")) {
            root.classList.remove("fmns-native-replaced");
        }
    }

    function ensureProxy(spec) {
        const component = spec.elemIds.map((id) => getById(id)).find(Boolean);
        if (!component) return;

        const input = dropdownInput(component);
        const controlWrapper = directChildContaining(component, input);
        if (!input || !controlWrapper) return;

        if (component._fmnsProxy && component._fmnsProxy.input !== input) {
            cleanupComponent(component);
        }

        if (!component._fmnsProxy) {
            const host = document.createElement("div");
            host.className = "fmns-native-select-host";

            const select = document.createElement("select");
            select.className = "fmns-native-select";
            select.dataset.fmnsKey = spec.key;
            select.setAttribute("aria-label", readLabelText(component, spec.fallbackLabel));

            host.appendChild(select);
            controlWrapper.insertAdjacentElement("afterend", host);
            controlWrapper.classList.add("fmns-source-hidden");
            component.classList.add("fmns-native-replaced");

            const bound = [];
            const bind = (node, type, handler) => {
                node.addEventListener(type, handler);
                bound.push({ node, type, handler });
            };

            const schedule = () => queueSync();
            bind(input, "input", schedule);
            bind(input, "change", schedule);
            bind(input, "blur", schedule);

            bind(select, "change", () => {
                const option = select.selectedOptions?.[0] || null;
                setNativeDropdown(component, option?.value || select.value, option?.textContent || select.value);
            });

            component._fmnsProxy = { host, select, input, controlWrapper, bound };
        }

        populateSelect(component._fmnsProxy.select, component);
    }

    function syncAll() {
        if (!isMobileViewport()) {
            cleanupAll();
            return;
        }

        for (const spec of SPECS) {
            try {
                ensureProxy(spec);
            } catch (error) {
                console.error(`[${EXT}] Failed to replace dropdown for ${spec.key}`, error);
            }
        }
    }

    function installListeners() {
        if (listenersInstalled) return;
        listenersInstalled = true;

        const mobileResize = () => queueSync();
        window.addEventListener("resize", mobileResize, { passive: true });
        window.visualViewport?.addEventListener?.("resize", mobileResize, { passive: true });
        window.visualViewport?.addEventListener?.("scroll", mobileResize, { passive: true });

        if (typeof onUiLoaded === "function") onUiLoaded(queueSync);
        if (typeof onAfterUiUpdate === "function") onAfterUiUpdate(queueSync);
        if (typeof onUiTabChange === "function") onUiTabChange(queueSync);

        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "visible") queueSync();
        });
    }

    function initialize() {
        installListeners();
        queueSync();
    }

    initialize();
})();
