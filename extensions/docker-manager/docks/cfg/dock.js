(() => {
    "use strict";

    const DOCK_ID = "cfg";

    function nativeControl(ctx, tabName) {
        if (tabName !== "txt2img" && tabName !== "img2img") return null;
        return ctx.getById(`${tabName}_cfg_scale`);
    }

    function inputsInside(component) {
        if (!component) return [];
        if (component.matches?.("input")) return [component];
        return [...(component.querySelectorAll?.("input") || [])];
    }

    function nativeInputs(component) {
        const inputs = inputsInside(component);
        return {
            range: inputs.find((input) => input.type === "range") || null,
            number: inputs.find((input) => input.type === "number") || null,
            fallback: inputs.find((input) => input.type === "text") || inputs[0] || null,
        };
    }

    function nativeValue(component) {
        const inputs = nativeInputs(component);
        return inputs.number?.value ?? inputs.range?.value ?? inputs.fallback?.value ?? "";
    }

    function applyNativeLimits(component, slider, number) {
        const native = nativeInputs(component);
        const source = native.range || native.number || native.fallback;
        if (!source) return;

        for (const attr of ["min", "max", "step"]) {
            const value = source.getAttribute?.(attr);
            if (value !== null && value !== undefined && value !== "") {
                slider.setAttribute(attr, value);
                number.setAttribute(attr, value);
            }
        }
    }

    function setInputValue(input, value) {
        if (!input) return;
        const next = String(value);
        if (input.value === next) return;

        const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
        if (descriptor?.set) descriptor.set.call(input, next);
        else input.value = next;

        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function setNativeValue(component, value) {
        if (!component) return;
        const inputs = nativeInputs(component);

        // Keep both faces of Gradio's Slider synchronized when present.
        setInputValue(inputs.range, value);
        setInputValue(inputs.number, value);
        if (!inputs.range && !inputs.number) setInputValue(inputs.fallback, value);
    }

    function mount(container, ctx) {
        const row = document.createElement("div");
        row.className = "fdm-simple-row fdm-cfg-row";

        const label = document.createElement("span");
        label.className = "fdm-simple-label fdm-field-label";
        label.textContent = "CFG";

        const slider = document.createElement("input");
        slider.type = "range";
        slider.className = "fdm-simple-slider fdm-cfg-slider";
        slider.setAttribute("aria-label", "CFG Scale");

        const number = document.createElement("input");
        number.type = "number";
        number.inputMode = "decimal";
        number.className = "fdm-simple-number fdm-cfg-number";
        number.setAttribute("aria-label", "CFG Scale value");

        row.append(label, slider, number);
        container.append(row);

        let bound = [];
        let refreshQueued = false;
        let syncing = false;
        let currentNative = null;

        function unbindNative() {
            for (const { node, type, handler } of bound) {
                node.removeEventListener(type, handler);
            }
            bound = [];
            currentNative = null;
        }

        function bindNative(component) {
            if (component === currentNative) return;
            unbindNative();
            currentNative = component;

            for (const node of inputsInside(component)) {
                const handler = () => queueSync();
                node.addEventListener("input", handler);
                node.addEventListener("change", handler);
                bound.push({ node, type: "input", handler });
                bound.push({ node, type: "change", handler });
            }
        }

        function syncFromNative() {
            refreshQueued = false;
            const tabName = ctx.currentGenerationTab();
            const native = nativeControl(ctx, tabName);
            const available = Boolean(native);
            ctx.setVisible(available);

            if (!available) {
                unbindNative();
                return;
            }

            bindNative(native);
            applyNativeLimits(native, slider, number);

            syncing = true;
            try {
                const value = nativeValue(native);
                if (value !== "") {
                    slider.value = value;
                    number.value = value;
                }
            } finally {
                syncing = false;
            }

            ctx.requestPosition();
        }

        function queueSync() {
            if (refreshQueued) return;
            refreshQueued = true;
            requestAnimationFrame(syncFromNative);
        }

        function pushValue(value) {
            if (syncing) return;
            const tabName = ctx.currentGenerationTab();
            const native = nativeControl(ctx, tabName);
            if (!native) return;
            setNativeValue(native, value);
            queueSync();
        }

        slider.addEventListener("input", () => {
            number.value = slider.value;
            pushValue(slider.value);
        });

        number.addEventListener("input", () => {
            if (number.value === "") return;
            slider.value = number.value;
            pushValue(number.value);
        });

        number.addEventListener("change", () => {
            if (number.value !== "") pushValue(number.value);
        });

        ctx.onLifecycle(queueSync);
        container._fdmCfgCleanup = () => unbindNative();
        syncFromNative();
    }

    function unmount(container) {
        container._fdmCfgCleanup?.();
        delete container._fdmCfgCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "CFG Dock",
        mount,
        unmount,
    });
})();
