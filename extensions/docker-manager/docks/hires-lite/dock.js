(() => {
    "use strict";

    const DOCK_ID = "hires-lite";

    function firstExisting(ctx, ids) {
        for (const id of ids) {
            const node = ctx.getById(id);
            if (node) return node;
        }
        return null;
    }

    function controlsFor(ctx, tabName) {
        if (tabName === "txt2img") {
            return {
                sampler: firstExisting(ctx, ["hr_sampler", "txt2img_hr_sampler"]),
                scheduler: firstExisting(ctx, ["hr_scheduler", "txt2img_hr_scheduler"]),
                denoise: firstExisting(ctx, ["txt2img_denoising_strength"]),
            };
        }

        if (tabName === "img2img") {
            // Optional compatibility path for an img2img Hires extension.
            // Deliberately do not fall back to img2img_denoising_strength,
            // because that controls the ordinary img2img pass rather than HR.
            return {
                sampler: firstExisting(ctx, [
                    "img2img_hr_sampler",
                    "img2img_hires_sampler",
                    "img2img_hr_sampler_name",
                ]),
                scheduler: firstExisting(ctx, [
                    "img2img_hr_scheduler",
                    "img2img_hires_scheduler",
                ]),
                denoise: firstExisting(ctx, [
                    "img2img_hr_denoising_strength",
                    "img2img_hires_denoising_strength",
                ]),
            };
        }

        return {};
    }

    function dropdownInput(component) {
        if (!component) return null;
        if (component.matches?.('input[role="listbox"]')) return component;
        return component.querySelector?.('input[role="listbox"], input') || null;
    }

    function sliderInputs(component) {
        if (!component) return {};
        const inputs = component.matches?.("input")
            ? [component]
            : [...(component.querySelectorAll?.("input") || [])];
        return {
            range: inputs.find((input) => input.type === "range") || null,
            number: inputs.find((input) => input.type === "number") || null,
            fallback: inputs.find((input) => input.type === "text") || inputs[0] || null,
        };
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

    function populateSelect(select, component) {
        if (!component) return;
        const elemId = component.id || "";
        let choices = configuredChoices(elemId);
        if (!choices.length) choices = renderedChoices(component);

        const input = dropdownInput(component);
        const current = input?.value || "";
        if (!choices.length && current) choices = [{ label: current, value: current }];

        const existing = [...select.options].map((option) => `${option.textContent}\u0000${option.value}`).join("\u0001");
        const incoming = choices.map((choice) => `${choice.label}\u0000${choice.value}`).join("\u0001");
        if (existing !== incoming) {
            select.replaceChildren(...choices.map((choice) => {
                const option = document.createElement("option");
                option.textContent = choice.label;
                option.value = choice.value;
                return option;
            }));
        }

        if (current) {
            const matching = [...select.options].find((option) => option.value === current || option.textContent === current);
            if (matching) select.value = matching.value;
        }
    }

    function setNativeDropdown(component, selectedValue, selectedLabel) {
        const input = dropdownInput(component);
        if (!input) return;

        const target = selectedLabel || selectedValue;
        const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
        if (descriptor?.set) descriptor.set.call(input, target);
        else input.value = target;

        input.dispatchEvent(new Event("input", { bubbles: true }));

        requestAnimationFrame(() => {
            input.dispatchEvent(new KeyboardEvent("keydown", {
                key: "Enter",
                code: "Enter",
                bubbles: true,
                cancelable: true,
            }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
        });
    }

    function setInputValue(input, value) {
        if (!input) return;
        const next = String(value);
        const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
        if (descriptor?.set) descriptor.set.call(input, next);
        else input.value = next;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function nativeSliderValue(component) {
        const inputs = sliderInputs(component);
        return inputs.number?.value ?? inputs.range?.value ?? inputs.fallback?.value ?? "";
    }

    function setNativeSlider(component, value) {
        const inputs = sliderInputs(component);
        setInputValue(inputs.range, value);
        setInputValue(inputs.number, value);
        if (!inputs.range && !inputs.number) setInputValue(inputs.fallback, value);
    }

    function applySliderLimits(component, slider, number) {
        const inputs = sliderInputs(component);
        const source = inputs.range || inputs.number || inputs.fallback;
        if (!source) return;
        for (const attr of ["min", "max", "step"]) {
            const value = source.getAttribute?.(attr);
            if (value !== null && value !== undefined && value !== "") {
                slider.setAttribute(attr, value);
                number.setAttribute(attr, value);
            }
        }
    }

    function createField(labelText, control, className) {
        const field = document.createElement("label");
        field.className = `fdm-hires-lite-field ${className}`;

        const label = document.createElement("span");
        label.className = "fdm-hires-lite-label fdm-field-label";
        label.textContent = labelText;

        field.append(label, control);
        return field;
    }

    function mount(container, ctx) {
        const layout = document.createElement("div");
        layout.className = "fdm-hires-lite-layout";

        const sampler = document.createElement("select");
        sampler.className = "fdm-hires-lite-select fdm-hires-lite-sampler";
        sampler.setAttribute("aria-label", "Hires sampler");

        const scheduler = document.createElement("select");
        scheduler.className = "fdm-hires-lite-select fdm-hires-lite-scheduler";
        scheduler.setAttribute("aria-label", "Hires scheduler");

        const denoiseWrap = document.createElement("div");
        denoiseWrap.className = "fdm-hires-lite-denoise-control";
        const denoise = document.createElement("input");
        denoise.type = "range";
        denoise.className = "fdm-hires-lite-range";
        denoise.setAttribute("aria-label", "Hires denoise strength");
        const denoiseNumber = document.createElement("input");
        denoiseNumber.type = "number";
        denoiseNumber.inputMode = "decimal";
        denoiseNumber.className = "fdm-hires-lite-number";
        denoiseNumber.setAttribute("aria-label", "Hires denoise strength value");
        denoiseWrap.append(denoise, denoiseNumber);

        const samplerField = createField("Sampler", sampler, "fdm-hires-lite-sampler-field");
        const schedulerField = createField("Scheduler", scheduler, "fdm-hires-lite-scheduler-field");
        const denoiseField = createField("Denoise", denoiseWrap, "fdm-hires-lite-denoise-field");

        layout.append(samplerField, schedulerField, denoiseField);
        container.append(layout);

        let currentControls = null;
        let bound = [];
        let refreshQueued = false;
        let syncing = false;

        function unbind() {
            for (const { node, type, handler } of bound) node.removeEventListener(type, handler);
            bound = [];
            currentControls = null;
        }

        function bindNode(node) {
            if (!node) return;
            for (const type of ["input", "change", "blur"]) {
                const handler = () => queueSync();
                node.addEventListener(type, handler);
                bound.push({ node, type, handler });
            }
        }

        function bindControls(controls) {
            if (
                currentControls?.sampler === controls.sampler &&
                currentControls?.scheduler === controls.scheduler &&
                currentControls?.denoise === controls.denoise
            ) return;

            unbind();
            currentControls = controls;
            bindNode(dropdownInput(controls.sampler));
            bindNode(dropdownInput(controls.scheduler));
            for (const node of Object.values(sliderInputs(controls.denoise))) bindNode(node);
        }

        function sync() {
            refreshQueued = false;
            const tabName = ctx.currentGenerationTab();
            const controls = controlsFor(ctx, tabName);
            const available = Boolean(controls.sampler && controls.scheduler && controls.denoise);
            ctx.setVisible(available);
            if (!available) {
                unbind();
                return;
            }

            bindControls(controls);
            populateSelect(sampler, controls.sampler);
            populateSelect(scheduler, controls.scheduler);
            applySliderLimits(controls.denoise, denoise, denoiseNumber);

            syncing = true;
            try {
                const samplerValue = dropdownInput(controls.sampler)?.value || "";
                const schedulerValue = dropdownInput(controls.scheduler)?.value || "";
                if (samplerValue) {
                    const option = [...sampler.options].find((item) => item.value === samplerValue || item.textContent === samplerValue);
                    if (option) sampler.value = option.value;
                }
                if (schedulerValue) {
                    const option = [...scheduler.options].find((item) => item.value === schedulerValue || item.textContent === schedulerValue);
                    if (option) scheduler.value = option.value;
                }

                const denoiseValue = nativeSliderValue(controls.denoise);
                if (denoiseValue !== "") {
                    denoise.value = denoiseValue;
                    denoiseNumber.value = denoiseValue;
                }
            } finally {
                syncing = false;
            }

            ctx.requestPosition();
        }

        function queueSync() {
            if (refreshQueued) return;
            refreshQueued = true;
            requestAnimationFrame(sync);
        }

        sampler.addEventListener("change", () => {
            if (syncing || !currentControls?.sampler) return;
            const option = sampler.selectedOptions[0];
            setNativeDropdown(currentControls.sampler, sampler.value, option?.textContent || sampler.value);
            queueSync();
        });

        scheduler.addEventListener("change", () => {
            if (syncing || !currentControls?.scheduler) return;
            const option = scheduler.selectedOptions[0];
            setNativeDropdown(currentControls.scheduler, scheduler.value, option?.textContent || scheduler.value);
            queueSync();
        });

        denoise.addEventListener("input", () => {
            if (syncing || !currentControls?.denoise) return;
            denoiseNumber.value = denoise.value;
            setNativeSlider(currentControls.denoise, denoise.value);
        });

        denoiseNumber.addEventListener("input", () => {
            if (syncing || !currentControls?.denoise || denoiseNumber.value === "") return;
            denoise.value = denoiseNumber.value;
            setNativeSlider(currentControls.denoise, denoiseNumber.value);
        });

        denoiseNumber.addEventListener("change", queueSync);

        ctx.onLifecycle(queueSync);
        container._fdmHiresLiteCleanup = () => unbind();
        sync();
    }

    function unmount(container) {
        container._fdmHiresLiteCleanup?.();
        delete container._fdmHiresLiteCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "Hires Fix Lite",
        mount,
        unmount,
    });
})();
