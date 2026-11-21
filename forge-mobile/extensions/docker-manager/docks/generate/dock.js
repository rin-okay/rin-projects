(() => {
    "use strict";

    const DOCK_ID = "generate";

    function controlsFor(ctx, tabName) {
        if (!tabName) return {};
        return {
            generate: ctx.getById(`${tabName}_generate`),
            interrupt: ctx.getById(`${tabName}_interrupt`),
            interrupting: ctx.getById(`${tabName}_interrupting`),
            skip: ctx.getById(`${tabName}_skip`),
        };
    }

    function normalizeControlText(element) {
        if (!element) return "";
        return [
            element.id,
            element.className,
            element.getAttribute?.("title"),
            element.getAttribute?.("aria-label"),
            element.getAttribute?.("data-action"),
            element.textContent,
        ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();
    }

    function findNativeHiresFixButton(ctx, tabName) {
        if (!tabName) return null;

        const scopes = [
            ctx.getById(`image_buttons_${tabName}`),
            ctx.getById(`${tabName}_gallery_container`),
            ctx.getById(`${tabName}_gallery`),
            ctx.getById(`tab_${tabName}`),
        ].filter(Boolean);

        const explicitIds = [
            ...(tabName === "img2img" ? ["img2img_hires_fix_manual_button"] : []),
            `${tabName}_hiresfix`,
            `${tabName}_hires_fix`,
            `${tabName}_hiresfix_enhance`,
            `${tabName}_hires_fix_enhance`,
            `${tabName}_hires_enhance`,
            `${tabName}_enhance`,
        ];

        for (const id of explicitIds) {
            const button = ctx.getById(id);
            if (button && button.tagName === "BUTTON" && !button.closest(".fdm-dock-shell")) return button;
        }

        let best = null;
        let bestScore = -1;
        const seen = new Set();

        for (const scope of scopes) {
            for (const button of scope.querySelectorAll?.("button") || []) {
                if (seen.has(button) || button.closest(".fdm-dock-shell")) continue;
                seen.add(button);

                const text = normalizeControlText(button);
                let score = 0;

                if (/hires[ _-]?fix|hiresfix|hrfix/.test(text)) score += 100;
                if (/enhance/.test(text)) score += 70;
                if (/high[ _-]?res|hires/.test(text)) score += 35;
                if (/[★☆⭐✦✧✨]/.test(text)) score += 25;
                if (scope.id === `image_buttons_${tabName}`) score += 30;
                else if (scope.id === `${tabName}_gallery_container`) score += 15;

                if (/save|folder|open|png|palette|send|refresh|restore|delete|copy/.test(text)) score -= 20;

                if (score > bestScore) {
                    best = button;
                    bestScore = score;
                }
            }
        }

        return bestScore >= 50 ? best : null;
    }

    function generationState(ctx, tabName) {
        const controls = controlsFor(ctx, tabName);
        if (ctx.isDisplayed(controls.interrupting)) return "stopping";
        if (ctx.isDisplayed(controls.interrupt)) return "running";
        return "idle";
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

    function mount(container, ctx) {
        const main = document.createElement("div");
        main.className = "fdm-generate-main";

        const generate = createButton(
            "fdm-generate-primary",
            "Generate",
            "Generate using the current Forge tab",
        );
        const secondary = createButton(
            "fdm-generate-secondary",
            "✨️",
            "Run Hires Fix on the current gallery image",
        );

        const skip = createButton("fdm-generate-secondary fdm-generate-skip", "Skip", "Skip the current generation");
        main.append(generate, skip, secondary);
        container.append(main);

        let observer = null;
        let observedControls = [];
        let refreshQueued = false;

        function bindObserver(tabName) {
            const controls = controlsFor(ctx, tabName);
            const next = [controls.interrupt, controls.interrupting, findNativeHiresFixButton(ctx, tabName)].filter(Boolean);
            const same = next.length === observedControls.length && next.every((el, i) => el === observedControls[i]);
            if (same) return;

            observer?.disconnect();
            observedControls = next;
            if (!next.length) return;

            observer = new MutationObserver(queueRefresh);
            for (const element of next) {
                observer.observe(element, {
                    attributes: true,
                    attributeFilter: ["style", "class", "hidden", "disabled"],
                });
            }
        }

        function update() {
            refreshQueued = false;
            const tabName = ctx.currentGenerationTab();
            const supported = tabName === "txt2img" || tabName === "img2img";
            ctx.setVisible(supported);
            if (!supported) {
                observer?.disconnect();
                observedControls = [];
                return;
            }

            bindObserver(tabName);
            const controls = controlsFor(ctx, tabName);
            const state = generationState(ctx, tabName);
            const hires = findNativeHiresFixButton(ctx, tabName);
            ctx.shell.dataset.state = state;

            generate.textContent = state === "idle" ? "Generate" : "Stop";
            generate.title = state === "idle" ? "Generate using the current Forge tab" : "Interrupt the current generation";
            generate.disabled = state === "stopping" || !(state === "idle" ? controls.generate : controls.interrupt);
            skip.hidden = state === "idle";
            skip.disabled = state !== "running" || !controls.skip;

            const icon = hires?.textContent?.match(/[★☆⭐✦✧✨][\uFE0E\uFE0F]?/u)?.[0];
            secondary.textContent = icon === "✨" || !icon ? "✨️" : icon;
            secondary.title = hires
                ? "Run Hires Fix on the current gallery image"
                : "Hires Fix is unavailable on this tab";
            secondary.disabled = !(hires && !hires.disabled);

            ctx.requestPosition();
        }

        function queueRefresh() {
            if (refreshQueued) return;
            refreshQueued = true;
            requestAnimationFrame(update);
        }

        generate.addEventListener("click", () => {
            const tabName = ctx.currentGenerationTab();
            const controls = controlsFor(ctx, tabName);
            const state = generationState(ctx, tabName);

            if (state === "idle" && controls.generate) controls.generate.click();
            else if (state === "running" && controls.interrupt) controls.interrupt.click();
            queueRefresh();
        });

        skip.addEventListener("click", () => {
            controlsFor(ctx, ctx.currentGenerationTab()).skip?.click();
            queueRefresh();
        });

        secondary.addEventListener("click", () => {
            const hires = findNativeHiresFixButton(ctx, ctx.currentGenerationTab());
            if (hires && !hires.disabled) hires.click();
            queueRefresh();
        });

        ctx.onLifecycle(queueRefresh);
        container._fdmGenerateCleanup = () => observer?.disconnect();
        update();
    }

    function unmount(container) {
        container._fdmGenerateCleanup?.();
        delete container._fdmGenerateCleanup;
    }

    window.ForgeMobileDockManager.registerDock({
        id: DOCK_ID,
        name: "Generate Dock",
        mount,
        unmount,
    });
})();
