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
            gallery: ctx.getById(`${tabName}_gallery_container`) || ctx.getById(`${tabName}_gallery`),
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
            "✨",
            "Run Hires Fix on the current gallery image",
        );

        const nav = document.createElement("div");
        nav.className = "fdm-generate-nav";
        const top = createButton("fdm-generate-nav-button", "↑", "Jump to top of page");
        const gallery = createButton("fdm-generate-nav-button", "↓", "Jump to output gallery");

        main.append(generate, secondary);
        nav.append(top, gallery);
        container.append(main, nav);

        let observer = null;
        let observedControls = [];
        let refreshQueued = false;

        function bindObserver(tabName) {
            const controls = controlsFor(ctx, tabName);
            const next = [controls.interrupt, controls.interrupting].filter(Boolean);
            const same = next.length === observedControls.length && next.every((el, i) => el === observedControls[i]);
            if (same) return;

            observer?.disconnect();
            observedControls = next;
            if (!next.length) return;

            observer = new MutationObserver(queueRefresh);
            for (const element of next) {
                observer.observe(element, {
                    attributes: true,
                    attributeFilter: ["style", "class"],
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

            if (state === "running") {
                generate.textContent = "Stop";
                generate.title = controls.interrupt ? "Interrupt the current generation" : "Interrupt is unavailable";
                generate.disabled = !controls.interrupt;

                secondary.textContent = "Skip";
                secondary.title = controls.skip ? "Skip the current generation" : "Skip is unavailable";
                secondary.disabled = !controls.skip;
            } else if (state === "stopping") {
                generate.textContent = "Stop";
                generate.title = "Forge is interrupting the current generation";
                generate.disabled = true;

                secondary.textContent = "Skip";
                secondary.title = "Forge is interrupting the current generation";
                secondary.disabled = true;
            } else {
                generate.textContent = "Generate";
                generate.title = "Generate using the current Forge tab";
                generate.disabled = !controls.generate;

                secondary.textContent = "✨";
                secondary.title = hires
                    ? "Run Hires Fix on the current gallery image"
                    : "Hires Fix is unavailable on this tab";
                secondary.disabled = !(hires && !hires.disabled);
            }

            top.disabled = false;
            gallery.disabled = !controls.gallery;
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

        secondary.addEventListener("click", () => {
            const tabName = ctx.currentGenerationTab();
            const controls = controlsFor(ctx, tabName);
            const state = generationState(ctx, tabName);

            if (state === "running") {
                controls.skip?.click();
            } else if (state === "idle") {
                const hires = findNativeHiresFixButton(ctx, tabName);
                if (hires && !hires.disabled) hires.click();
            }
            queueRefresh();
        });

        top.addEventListener("click", () => {
            window.scrollTo({ top: 0, left: 0, behavior: "smooth" });
        });

        gallery.addEventListener("click", () => {
            const controls = controlsFor(ctx, ctx.currentGenerationTab());
            controls.gallery?.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
        });

        ctx.onLifecycle(queueRefresh);
        container._fdmGenerateCleanup = () => observer?.disconnect();
        update();
    }

    function unmount(container) {
        container._fdmGenerateCleanup?.();
        delete container._fdmGenerateCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "Generate Dock",
        mount,
        unmount,
    });
})();
