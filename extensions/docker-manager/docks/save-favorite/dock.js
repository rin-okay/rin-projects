(() => {
    "use strict";

    const DOCK_ID = "save-favorite";
    const SUCCESS_MS = 1700;
    const SAVE_TIMEOUT_MS = 8000;

    function asButton(element) {
        if (!element) return null;
        if (element.tagName === "BUTTON") return element;
        return element.querySelector?.("button") || null;
    }

    function nativeSaveButton(ctx, tabName) {
        if (tabName !== "txt2img" && tabName !== "img2img") return null;
        return asButton(ctx.getById(`save_${tabName}`));
    }

    function nativeLog(ctx, tabName) {
        if (tabName !== "txt2img" && tabName !== "img2img") return null;
        return ctx.getById(`html_log_${tabName}`);
    }

    function mount(container, ctx) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "fdm-save-favorite-button";
        button.textContent = "💾";
        button.title = "Save current gallery image";
        button.setAttribute("aria-label", "Save current gallery image");
        container.append(button);

        let resultObserver = null;
        let resultTimeout = null;
        let successTimeout = null;
        let lifecycleQueued = false;
        let pending = false;

        function clearResultWatch() {
            resultObserver?.disconnect();
            resultObserver = null;
            if (resultTimeout) clearTimeout(resultTimeout);
            resultTimeout = null;
            pending = false;
            delete button.dataset.pending;
        }

        function restoreButton() {
            if (successTimeout) clearTimeout(successTimeout);
            successTimeout = null;
            delete button.dataset.success;
            delete button.dataset.pending;
            button.textContent = "💾";
            syncFromNative();
        }

        function showPending() {
            pending = true;
            button.dataset.pending = "true";
            button.textContent = "↻";
            button.disabled = true;
            button.title = "Saving…";
            button.setAttribute("aria-label", "Saving image");
        }

        function showSuccess() {
            clearResultWatch();
            if (successTimeout) clearTimeout(successTimeout);
            button.dataset.success = "true";
            button.textContent = "✓";
            button.disabled = true;
            button.title = "Saved";
            button.setAttribute("aria-label", "Image saved successfully");
            successTimeout = setTimeout(restoreButton, SUCCESS_MS);
        }

        function logShowsSuccess(log) {
            return /\bSaved\s*:/i.test(log?.textContent || "");
        }

        function copyNativeAppearance(native) {
            if (!native) return;

            // Reuse Forge/Gradio's ToolButton classes so the dock looks like the
            // real gallery Save button under whatever active theme is loaded.
            const ownClass = "fdm-save-favorite-button";
            const nativeClasses = [...native.classList].filter((name) => name !== ownClass);
            button.className = [ownClass, ...nativeClasses].join(" ");

            if (!button.dataset.success && !button.dataset.pending) {
                const nativeText = (native.textContent || "").trim();
                button.textContent = nativeText || "💾";
            }
        }

        function syncFromNative() {
            const tabName = ctx.currentGenerationTab();
            const native = nativeSaveButton(ctx, tabName);
            const available = Boolean(native);
            ctx.setVisible(available);

            if (!available) return;
            copyNativeAppearance(native);

            if (!button.dataset.success && !button.dataset.pending) {
                button.disabled = Boolean(native.disabled) || pending;
                button.title = native.title || "Save current gallery image";
                button.setAttribute("aria-label", native.getAttribute("aria-label") || button.title);
            }

            ctx.requestPosition();
        }

        function queueLifecycleSync() {
            if (lifecycleQueued) return;
            lifecycleQueued = true;
            requestAnimationFrame(() => {
                lifecycleQueued = false;
                syncFromNative();
            });
        }

        function watchForSaveResult(tabName) {
            clearResultWatch();
            showPending();
            const log = nativeLog(ctx, tabName);
            if (!log) {
                resultTimeout = setTimeout(() => {
                    clearResultWatch();
                    restoreButton();
                }, SAVE_TIMEOUT_MS);
                return;
            }

            const check = () => {
                if (logShowsSuccess(log)) showSuccess();
            };

            resultObserver = new MutationObserver(check);
            resultObserver.observe(log, {
                childList: true,
                subtree: true,
                characterData: true,
            });

            resultTimeout = setTimeout(() => {
                clearResultWatch();
                restoreButton();
            }, SAVE_TIMEOUT_MS);
        }

        button.addEventListener("click", () => {
            if (button.dataset.success || pending) return;

            const tabName = ctx.currentGenerationTab();
            const native = nativeSaveButton(ctx, tabName);
            if (!native || native.disabled) return;

            const log = nativeLog(ctx, tabName);
            const before = log?.textContent || "";
            watchForSaveResult(tabName);
            native.click();

            // Gradio can replace the log contents very quickly. Check once on
            // the next frame as well as through the MutationObserver.
            requestAnimationFrame(() => {
                const after = log?.textContent || "";
                if (after !== before && /\bSaved\s*:/i.test(after)) showSuccess();
            });
        });

        ctx.onLifecycle(queueLifecycleSync);
        container._fdmSaveFavoriteCleanup = () => {
            clearResultWatch();
            if (successTimeout) clearTimeout(successTimeout);
        };

        syncFromNative();
    }

    function unmount(container) {
        container._fdmSaveFavoriteCleanup?.();
        delete container._fdmSaveFavoriteCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "Save / Favorite",
        mount,
        unmount,
    });
})();
