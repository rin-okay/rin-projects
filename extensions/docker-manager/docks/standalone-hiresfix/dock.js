(() => {
    "use strict";

    const DOCK_ID = "standalone-hiresfix";
    const CLICK_FEEDBACK_MS = 720;

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
            const candidate = ctx.getById(id);
            const button = candidate?.tagName === "BUTTON" ? candidate : candidate?.querySelector?.("button");
            if (button && !button.closest(".fdm-dock-shell")) return button;
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

    function mount(container, ctx) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "fdm-standalone-hiresfix-button";
        button.textContent = "✨";
        button.title = "Run Hires Fix on the current gallery image";
        button.setAttribute("aria-label", button.title);
        container.append(button);

        let feedbackTimer = null;
        let refreshQueued = false;

        function showClickedFeedback() {
            if (feedbackTimer) clearTimeout(feedbackTimer);
            button.dataset.clicked = "true";
            button.textContent = "💫";
            feedbackTimer = setTimeout(() => {
                delete button.dataset.clicked;
                button.textContent = "✨";
                feedbackTimer = null;
                queueRefresh();
            }, CLICK_FEEDBACK_MS);
        }

        function sync() {
            refreshQueued = false;
            const tabName = ctx.currentGenerationTab();
            const native = findNativeHiresFixButton(ctx, tabName);
            const supported = tabName === "txt2img" || tabName === "img2img";
            ctx.setVisible(supported);

            if (!supported) return;

            if (!button.dataset.clicked) {
                button.disabled = !(native && !native.disabled);
                button.title = native
                    ? "Run Hires Fix on the current gallery image"
                    : "Hires Fix is unavailable on this tab";
                button.setAttribute("aria-label", button.title);
            }

            ctx.requestPosition();
        }

        function queueRefresh() {
            if (refreshQueued) return;
            refreshQueued = true;
            requestAnimationFrame(sync);
        }

        button.addEventListener("click", () => {
            const tabName = ctx.currentGenerationTab();
            const native = findNativeHiresFixButton(ctx, tabName);
            if (!native || native.disabled) return;

            showClickedFeedback();
            native.click();
            queueRefresh();
        });

        ctx.onLifecycle(queueRefresh);
        container._fdmStandaloneHiresFixCleanup = () => {
            if (feedbackTimer) clearTimeout(feedbackTimer);
        };

        sync();
    }

    function unmount(container) {
        container._fdmStandaloneHiresFixCleanup?.();
        delete container._fdmStandaloneHiresFixCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "Standalone Hires Fix",
        mount,
        unmount,
    });
})();
