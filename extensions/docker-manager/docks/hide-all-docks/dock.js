(() => {
    "use strict";

    const DOCK_ID = "hide-all-docks";
    const HIDDEN_CLASS = "fdm-hidden-by-hide-all-dock";

    function allDockShells() {
        return [...document.querySelectorAll(".fdm-dock-shell")];
    }

    function mount(container, ctx) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "fdm-hide-all-docks-button tool secondary";
        button.textContent = "🙈";
        button.title = "Hide all other docks";
        button.setAttribute("aria-label", "Hide all other docks");
        container.append(button);

        let hidden = false;
        let bodyObserver = null;

        function updateButton() {
            button.dataset.mode = hidden ? "restore" : "hide";
            button.textContent = hidden ? "👁️" : "🙈";
            button.title = hidden ? "Restore all hidden docks" : "Hide all other docks";
            button.setAttribute("aria-label", button.title);
        }

        function hideOtherDock(shell) {
            if (!hidden || !shell || shell === ctx.shell) return;
            if (!shell.classList?.contains("fdm-dock-shell")) return;
            shell.classList.add(HIDDEN_CLASS);
        }

        function hideAllOthers() {
            hidden = true;
            for (const shell of allDockShells()) hideOtherDock(shell);
            updateButton();
            ctx.requestPosition();
        }

        function restoreAll() {
            hidden = false;
            for (const shell of document.querySelectorAll(`.${HIDDEN_CLASS}`)) {
                shell.classList.remove(HIDDEN_CLASS);
            }
            updateButton();
            ctx.requestPosition();
        }

        function observeNewDocks() {
            bodyObserver?.disconnect();
            bodyObserver = new MutationObserver((mutations) => {
                if (!hidden) return;
                for (const mutation of mutations) {
                    for (const node of mutation.addedNodes || []) {
                        if (!(node instanceof Element)) continue;
                        if (node.matches?.(".fdm-dock-shell")) hideOtherDock(node);
                        for (const shell of node.querySelectorAll?.(".fdm-dock-shell") || []) {
                            hideOtherDock(shell);
                        }
                    }
                }
            });
            bodyObserver.observe(document.body, { childList: true, subtree: true });
        }

        button.addEventListener("click", () => {
            if (hidden) restoreAll();
            else hideAllOthers();
        });

        observeNewDocks();
        updateButton();

        container._fdmHideAllDocksCleanup = () => {
            bodyObserver?.disconnect();
            bodyObserver = null;
            restoreAll();
        };
    }

    function unmount(container) {
        container._fdmHideAllDocksCleanup?.();
        delete container._fdmHideAllDocksCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "Hide / Restore Docks",
        mount,
        unmount,
    });
})();
