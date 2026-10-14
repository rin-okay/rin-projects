(() => {
    "use strict";

    const DOCK_ID = "seed";
    const FALLBACK_RANDOM = "🎲";
    const FALLBACK_REUSE = "♻";

    function nativeIds(tabName) {
        // Forge Neo's Seed UI is ScriptBuiltinUI. Its elem_id() is simply
        // <tab>_<item>, e.g. txt2img_seed / img2img_subseed_strength.
        const base = `${tabName}_`;
        return {
            seed: `${base}seed`,
            randomSeed: `${base}random_seed`,
            reuseSeed: `${base}reuse_seed`,
            extra: `${base}subseed_show`,
            extras: `${base}seed_extras`,
            subseed: `${base}subseed`,
            randomSubseed: `${base}random_subseed`,
            reuseSubseed: `${base}reuse_subseed`,
            strength: `${base}subseed_strength`,
        };
    }

    function nativeControls(ctx, tabName) {
        if (!tabName) return {};
        const ids = nativeIds(tabName);
        return Object.fromEntries(
            Object.entries(ids).map(([key, id]) => [key, ctx.getById(id)]),
        );
    }

    function inputsInside(component) {
        if (!component) return [];
        if (component.matches?.("input, textarea")) return [component];
        return [...component.querySelectorAll?.("input, textarea") || []];
    }

    function valueInput(component) {
        const inputs = inputsInside(component);
        return inputs.find((input) => ["number", "text"].includes(input.type))
            || inputs.find((input) => input.type === "range")
            || inputs[0]
            || null;
    }

    function checkboxInput(component) {
        if (!component) return null;
        if (component.matches?.('input[type="checkbox"]')) return component;
        return component.querySelector?.('input[type="checkbox"]') || null;
    }

    function readValue(component, fallback = "") {
        const input = valueInput(component);
        return input ? input.value : fallback;
    }

    function readCheckbox(component) {
        return Boolean(checkboxInput(component)?.checked);
    }

    function dispatchValueEvent(input, type) {
        input.dispatchEvent(new Event(type, { bubbles: true }));
    }

    function setNativeValue(component, value) {
        if (!component) return false;
        const inputs = inputsInside(component).filter((input) => input.type !== "checkbox");
        if (!inputs.length) return false;

        // Gradio Slider renders both range and numeric inputs in some builds.
        // Update each visible representation, then dispatch the normal events so
        // Gradio's own component state remains authoritative.
        let changed = false;
        for (const input of inputs) {
            if (!["number", "text", "range"].includes(input.type)) continue;
            const next = String(value);
            if (input.value !== next) {
                input.value = next;
                dispatchValueEvent(input, "input");
                dispatchValueEvent(input, "change");
                changed = true;
            }
        }
        return changed;
    }

    function setNativeCheckbox(component, checked) {
        const input = checkboxInput(component);
        if (!input) return false;
        const next = Boolean(checked);
        if (input.checked === next) return false;
        // Use the native checkbox click path so Gradio's own change callback
        // updates the Seed extras group and its internal component value.
        input.click();
        return true;
    }

    function symbolFrom(button, fallback) {
        const text = button?.textContent?.trim();
        return text || fallback;
    }

    function createButton(className, text, title) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = className;
        button.textContent = text;
        button.title = title;
        button.setAttribute("aria-label", title);
        return button;
    }

    function createField(labelText, className, options = {}) {
        const field = document.createElement("label");
        field.className = `fdm-seed-field ${className}`;

        const label = document.createElement("span");
        label.className = "fdm-seed-label fdm-field-label";
        label.textContent = labelText;

        const input = document.createElement("input");
        input.className = "fdm-seed-input";
        input.type = options.type || "number";
        if (options.step !== undefined) input.step = String(options.step);
        if (options.min !== undefined) input.min = String(options.min);
        if (options.max !== undefined) input.max = String(options.max);
        input.inputMode = options.inputMode || "numeric";

        field.append(label, input);
        return { field, input };
    }

    function mount(container, ctx) {
        const seedField = createField("Seed", "fdm-seed-main-field", { inputMode: "numeric" });

        const toolsRow = document.createElement("div");
        toolsRow.className = "fdm-seed-tools-row";
        const randomSeed = createButton("fdm-seed-tool", FALLBACK_RANDOM, "Random seed");
        const reuseSeed = createButton("fdm-seed-tool", FALLBACK_REUSE, "Reuse seed from selected/last generation");

        const extraLabel = document.createElement("label");
        extraLabel.className = "fdm-seed-extra-toggle";
        const extraCheckbox = document.createElement("input");
        extraCheckbox.type = "checkbox";
        extraCheckbox.className = "fdm-seed-extra-checkbox";
        const extraText = document.createElement("span");
        extraText.textContent = "Extra";
        extraLabel.append(extraCheckbox, extraText);
        toolsRow.append(randomSeed, reuseSeed, extraLabel);

        const variationRow = document.createElement("div");
        variationRow.className = "fdm-seed-variation-row fdm-seed-optional";
        const variationField = createField("Variation seed", "fdm-seed-variation-field", { inputMode: "numeric" });
        const randomVariation = createButton("fdm-seed-tool", FALLBACK_RANDOM, "Random variation seed");
        const reuseVariation = createButton("fdm-seed-tool", FALLBACK_REUSE, "Reuse variation seed from selected/last generation");
        variationRow.append(variationField.field, randomVariation, reuseVariation);

        const strengthRow = document.createElement("div");
        strengthRow.className = "fdm-seed-strength-row fdm-seed-optional";
        const strengthLabel = document.createElement("span");
        strengthLabel.className = "fdm-seed-label fdm-field-label";
        strengthLabel.textContent = "Variation strength";
        const strengthRange = document.createElement("input");
        strengthRange.className = "fdm-seed-strength-range";
        strengthRange.type = "range";
        strengthRange.min = "0";
        strengthRange.max = "1";
        strengthRange.step = "0.01";
        const strengthNumber = document.createElement("input");
        strengthNumber.className = "fdm-seed-strength-number";
        strengthNumber.type = "number";
        strengthNumber.inputMode = "decimal";
        strengthNumber.min = "0";
        strengthNumber.max = "1";
        strengthNumber.step = "0.01";
        strengthRow.append(strengthLabel, strengthRange, strengthNumber);

        const baseLayout = document.createElement("div");
        baseLayout.className = "fdm-seed-base-layout";
        baseLayout.append(seedField.field, toolsRow);

        const extrasLayout = document.createElement("div");
        extrasLayout.className = "fdm-seed-extras-layout";
        extrasLayout.append(variationRow, strengthRow);

        container.append(baseLayout, extrasLayout);

        let boundNodes = [];
        let refreshQueued = false;
        let syncingLocal = false;

        function currentTab() {
            const tab = ctx.currentGenerationTab();
            return tab === "txt2img" || tab === "img2img" ? tab : null;
        }

        function controls() {
            return nativeControls(ctx, currentTab());
        }

        function setOptionalVisible(visible) {
            variationRow.hidden = !visible;
            strengthRow.hidden = !visible;
        }

        function updateSymbols(native) {
            randomSeed.textContent = symbolFrom(native.randomSeed, FALLBACK_RANDOM);
            reuseSeed.textContent = symbolFrom(native.reuseSeed, FALLBACK_REUSE);
            randomVariation.textContent = symbolFrom(native.randomSubseed, FALLBACK_RANDOM);
            reuseVariation.textContent = symbolFrom(native.reuseSubseed, FALLBACK_REUSE);
        }

        function syncFromNative() {
            refreshQueued = false;
            const tabName = currentTab();
            const supported = Boolean(tabName);
            ctx.setVisible(supported);
            if (!supported) return;

            const native = nativeControls(ctx, tabName);
            const available = Boolean(native.seed && native.extra && native.subseed && native.strength);
            ctx.setVisible(available);
            if (!available) return;

            syncingLocal = true;
            try {
                seedField.input.value = readValue(native.seed, "-1");
                variationField.input.value = readValue(native.subseed, "-1");

                const strengthRaw = Number.parseFloat(readValue(native.strength, "0"));
                const strength = Number.isFinite(strengthRaw) ? Math.min(1, Math.max(0, strengthRaw)) : 0;
                strengthRange.value = String(strength);
                strengthNumber.value = String(strength);

                const extra = readCheckbox(native.extra);
                extraCheckbox.checked = extra;
                setOptionalVisible(extra);
                updateSymbols(native);

                randomSeed.disabled = !native.randomSeed;
                reuseSeed.disabled = !native.reuseSeed;
                randomVariation.disabled = !native.randomSubseed;
                reuseVariation.disabled = !native.reuseSubseed;
            } finally {
                syncingLocal = false;
            }

            bindNativeListeners(native);
            ctx.requestPosition();
        }

        function queueSync(delay = 0) {
            if (refreshQueued) return;
            refreshQueued = true;
            if (delay > 0) {
                setTimeout(() => requestAnimationFrame(syncFromNative), delay);
            } else {
                requestAnimationFrame(syncFromNative);
            }
        }

        function clearNativeListeners() {
            for (const { node, type, handler } of boundNodes) {
                node.removeEventListener(type, handler);
            }
            boundNodes = [];
        }

        function bind(node, type, handler) {
            if (!node) return;
            node.addEventListener(type, handler);
            boundNodes.push({ node, type, handler });
        }

        function bindNativeListeners(native) {
            const nodes = [
                ...inputsInside(native.seed),
                ...inputsInside(native.extra),
                ...inputsInside(native.subseed),
                ...inputsInside(native.strength),
            ];

            const currentNodes = boundNodes.map((item) => item.node);
            const same = nodes.length === currentNodes.length && nodes.every((node, index) => node === currentNodes[index]);
            if (same) return;

            clearNativeListeners();
            for (const node of nodes) {
                bind(node, "input", () => queueSync());
                bind(node, "change", () => queueSync());
            }
        }

        function syncLaterAfterNativeAction() {
            queueSync(30);
            setTimeout(() => queueSync(), 220);
            setTimeout(() => queueSync(), 650);
        }

        seedField.input.addEventListener("change", () => {
            if (syncingLocal) return;
            setNativeValue(controls().seed, seedField.input.value || "-1");
            queueSync();
        });

        variationField.input.addEventListener("change", () => {
            if (syncingLocal) return;
            setNativeValue(controls().subseed, variationField.input.value || "-1");
            queueSync();
        });

        extraCheckbox.addEventListener("change", () => {
            if (syncingLocal) return;
            const checked = extraCheckbox.checked;
            setOptionalVisible(checked);
            setNativeCheckbox(controls().extra, checked);
            ctx.requestPosition();
            syncLaterAfterNativeAction();
        });

        function setStrength(value) {
            if (syncingLocal) return;
            let number = Number.parseFloat(value);
            if (!Number.isFinite(number)) number = 0;
            number = Math.min(1, Math.max(0, number));
            const normalized = String(Math.round(number * 100) / 100);
            strengthRange.value = normalized;
            strengthNumber.value = normalized;
            setNativeValue(controls().strength, normalized);
            queueSync();
        }

        strengthRange.addEventListener("input", () => setStrength(strengthRange.value));
        strengthNumber.addEventListener("change", () => setStrength(strengthNumber.value));

        randomSeed.addEventListener("click", () => {
            controls().randomSeed?.click();
            syncLaterAfterNativeAction();
        });
        reuseSeed.addEventListener("click", () => {
            controls().reuseSeed?.click();
            syncLaterAfterNativeAction();
        });
        randomVariation.addEventListener("click", () => {
            controls().randomSubseed?.click();
            syncLaterAfterNativeAction();
        });
        reuseVariation.addEventListener("click", () => {
            controls().reuseSubseed?.click();
            syncLaterAfterNativeAction();
        });

        ctx.onLifecycle(queueSync);
        container._fdmSeedCleanup = () => clearNativeListeners();
        syncFromNative();
    }

    function unmount(container) {
        container._fdmSeedCleanup?.();
        delete container._fdmSeedCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "Seed Dock",
        mount,
        unmount,
    });
})();
