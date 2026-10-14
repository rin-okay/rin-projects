(() => {
    "use strict";

    const DOCK_ID = "lock-docks-toggle";

    function mount(container, ctx) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "fdm-lock-docks-toggle-button tool secondary";
        container.append(button);

        let observer = null;
        let refreshQueued = false;

        function isLocked() {
            return ctx.shell?.dataset?.locked === "true";
        }

        function updateButton() {
            refreshQueued = false;
            const locked = isLocked();
            button.dataset.mode = locked ? "unlock" : "lock";
            button.textContent = locked ? "🔓" : "🔒";
            button.title = locked ? "Unlock docks" : "Lock docks";
            button.setAttribute("aria-label", button.title);
            button.disabled = typeof window.ForgeDockManager?.setDocksLocked !== "function";
        }

        function queueUpdate() {
            if (refreshQueued) return;
            refreshQueued = true;
            requestAnimationFrame(updateButton);
        }

        button.addEventListener("click", () => {
            const setter = window.ForgeDockManager?.setDocksLocked;
            if (typeof setter !== "function") return;
            setter(!isLocked());
            queueUpdate();
        });

        observer = new MutationObserver(queueUpdate);
        observer.observe(ctx.shell, {
            attributes: true,
            attributeFilter: ["data-locked"],
        });

        ctx.onLifecycle(queueUpdate);
        container._fdmLockDocksToggleCleanup = () => {
            observer?.disconnect();
            observer = null;
        };

        updateButton();
    }

    function unmount(container) {
        container._fdmLockDocksToggleCleanup?.();
        delete container._fdmLockDocksToggleCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "Lock / Unlock Docks",
        mount,
        unmount,
    });
})();
