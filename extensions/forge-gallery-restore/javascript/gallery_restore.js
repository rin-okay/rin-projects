(() => {
    "use strict";

    const TABS = ["txt2img", "img2img"];
    const EXT_KEY = (tab) => `forge_gallery_restore_${tab}_task_id`;
    const FORGE_KEY = (tab) => `${tab}_task_id`;
    const PENDING_KEY = (tab) => `forge_gallery_restore_pending_${tab}`;

    let backgroundedSinceLoad = document.visibilityState === "hidden";

    function app() {
        return typeof gradioApp === "function" ? gradioApp() : document;
    }

    function forgeGet(key) {
        try {
            if (typeof localGet === "function") return localGet(key);
        } catch (e) {
            console.debug("[Gallery Restore] localGet failed:", e);
        }

        try {
            return window.localStorage.getItem(key);
        } catch (e) {
            return null;
        }
    }

    function forgeSet(key, value) {
        try {
            if (typeof localSet === "function") {
                localSet(key, value);
                return;
            }
        } catch (e) {
            console.debug("[Gallery Restore] localSet failed:", e);
        }

        try {
            window.localStorage.setItem(key, value);
        } catch (e) {
            console.warn("[Gallery Restore] Could not write Forge task ID:", e);
        }
    }

    function forgeRemove(key) {
        try {
            if (typeof localRemove === "function") {
                localRemove(key);
                return;
            }
        } catch (e) {
            console.debug("[Gallery Restore] localRemove failed:", e);
        }

        try {
            window.localStorage.removeItem(key);
        } catch (e) {
            console.warn("[Gallery Restore] Could not remove temporary Forge task ID:", e);
        }
    }

    function extGet(tab) {
        try {
            return window.localStorage.getItem(EXT_KEY(tab));
        } catch (e) {
            return null;
        }
    }

    function extSet(tab, taskId) {
        if (!taskId) return;

        try {
            window.localStorage.setItem(EXT_KEY(tab), taskId);
        } catch (e) {
            console.warn("[Gallery Restore] Could not save recovery task ID:", e);
        }
    }

    function captureTaskId(tab) {
        const taskId = forgeGet(FORGE_KEY(tab));
        if (!taskId) return false;

        extSet(tab, taskId);
        return true;
    }

    function captureAfterGenerate(tab) {
        let attempts = 0;

        const tryCapture = () => {
            attempts += 1;
            if (captureTaskId(tab) || attempts >= 20) return;
            setTimeout(tryCapture, 25);
        };

        setTimeout(tryCapture, 0);
    }

    function bindGenerateCapture(tab) {
        const generate = app().getElementById(`${tab}_generate`);
        if (!generate || generate.dataset.galleryRestoreCaptureBound === "1") return;

        generate.dataset.galleryRestoreCaptureBound = "1";
        generate.addEventListener("click", () => captureAfterGenerate(tab), false);
    }

    function softRestore(tab, taskId = extGet(tab)) {
        if (!taskId) {
            console.warn(`[Gallery Restore] No saved ${tab} task ID to restore.`);
            return false;
        }

        const restoreButton = app().getElementById(`${tab}_restore_progress`);
        if (!restoreButton) {
            console.error(`[Gallery Restore] Forge Restore Progress button for ${tab} was not found.`);
            return false;
        }

        const forgeKey = FORGE_KEY(tab);
        const previousTaskId = forgeGet(forgeKey);

        forgeSet(forgeKey, taskId);
        restoreButton.click();

        setTimeout(() => {
            if (forgeGet(forgeKey) !== taskId) return;

            if (previousTaskId) forgeSet(forgeKey, previousTaskId);
            else forgeRemove(forgeKey);
        }, 1000);

        return true;
    }

    function hardRestore(tab, taskId) {
        try {
            window.localStorage.setItem(PENDING_KEY(tab), taskId);
        } catch (e) {
            console.warn("[Gallery Restore] Could not save pending hard-restore task:", e);
            softRestore(tab, taskId);
            return;
        }

        window.location.reload();
    }

    function restoreLastResult(tab) {
        const taskId = extGet(tab);
        if (!taskId) {
            console.warn(`[Gallery Restore] No saved ${tab} task ID to restore.`);
            return;
        }

        // If iOS/Safari has backgrounded this exact page instance, use a fresh
        // Gradio client instead of trusting the possibly-stale event connection.
        // The pending task survives the reload and is restored automatically.
        if (backgroundedSinceLoad) {
            hardRestore(tab, taskId);
            return;
        }

        softRestore(tab, taskId);
    }

    function retrySoftRestore(tab, taskId, attempts = 0) {
        if (softRestore(tab, taskId)) return;
        if (attempts >= 20) {
            console.error(`[Gallery Restore] Could not auto-restore ${tab} after page reload.`);
            return;
        }
        setTimeout(() => retrySoftRestore(tab, taskId, attempts + 1), 100);
    }

    function consumePendingRestore() {
        for (const tab of TABS) {
            let taskId = null;
            try {
                taskId = window.localStorage.getItem(PENDING_KEY(tab));
                if (taskId) window.localStorage.removeItem(PENDING_KEY(tab));
            } catch (e) {
                taskId = null;
            }

            if (!taskId) continue;

            // Give Gradio's fresh page instance a moment to finish binding the hidden
            // restore action before replaying the saved task.
            setTimeout(() => retrySoftRestore(tab, taskId), 250);
        }
    }

    function findEnhanceButton(tab) {
        const row = app().getElementById(`image_buttons_${tab}`);
        if (!row) return null;

        return Array.from(row.querySelectorAll("button")).find((button) =>
            (button.textContent || "").includes("✨")
        ) || null;
    }

    function directChildContaining(row, element) {
        let node = element;
        while (node && node.parentElement && node.parentElement !== row) {
            node = node.parentElement;
        }
        return node && node.parentElement === row ? node : element;
    }

    function stripIds(node) {
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        node.removeAttribute("id");
        node.querySelectorAll("[id]").forEach((child) => child.removeAttribute("id"));
    }

    function installRestoreButton(tab) {
        const row = app().getElementById(`image_buttons_${tab}`);
        if (!row || app().getElementById(`gallery_restore_${tab}`)) return;

        const enhanceButton = findEnhanceButton(tab);
        const enhanceRoot = enhanceButton ? directChildContaining(row, enhanceButton) : null;
        const templateRoot = enhanceRoot || row.querySelector("button");
        if (!templateRoot) return;

        const restoreRoot = templateRoot.cloneNode(enhanceRoot ? true : false);
        stripIds(restoreRoot);

        const restoreButton = restoreRoot.matches?.("button")
            ? restoreRoot
            : restoreRoot.querySelector("button");

        if (!restoreButton) return;

        restoreButton.id = `gallery_restore_${tab}`;
        restoreButton.type = "button";
        restoreButton.textContent = "🔄";
        restoreButton.title = "Restore last gallery result and parameters";
        restoreButton.setAttribute("aria-label", "Restore last gallery result and parameters");
        restoreButton.removeAttribute("disabled");
        restoreButton.classList.remove("disabled");

        restoreButton.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            restoreLastResult(tab);
        });

        if (enhanceRoot) enhanceRoot.insertAdjacentElement("beforebegin", restoreRoot);
        else row.appendChild(restoreRoot);
    }

    function install() {
        for (const tab of TABS) {
            bindGenerateCapture(tab);
            captureTaskId(tab);
            installRestoreButton(tab);
        }
    }

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") backgroundedSinceLoad = true;
    });

    if (typeof onUiLoaded === "function") onUiLoaded(() => {
        install();
        consumePendingRestore();
    });
    else window.addEventListener("load", () => {
        install();
        consumePendingRestore();
    }, { once: true });

    if (typeof onAfterUiUpdate === "function") onAfterUiUpdate(install);

    setInterval(() => {
        for (const tab of TABS) captureTaskId(tab);
    }, 250);
})();
