/* Reuse the installed IIB frontend and its native Forge ParamBinding actions. */
(async () => {
    "use strict";
    const host = window.MobileWorkspaceHost;
    await host.extensions["mobile-workspace"].ready;
    if (!host.mobile) {
        await new Promise(resolve => document.addEventListener("forge-mobile-ready", resolve, { once: true }));
    }
    const panel = document.getElementById("mobile-iib-view");
    let frame;
    let loading;
    let handoff = Promise.resolve();
    let transferBus;

    function nativeFrame() {
        const wrapper = document.getElementById("infinite_image_browsing_container_wrapper");
        const iframe = wrapper?.querySelector("iframe");
        // IIB's own parent receiver and hidden paste controls must also be ready.
        if (!iframe || !window.IIB_container_id
            || !document.getElementById("iib_hidden_img_update_trigger")
            || !document.getElementById("iib_hidden_tab_txt2img")
            || !document.getElementById("iib_hidden_tab_img2img")) return null;
        return iframe;
    }

    function waitForNativeFrame() {
        return new Promise((resolve, reject) => {
            const current = nativeFrame();
            if (current) return resolve(current);
            const observer = new MutationObserver(check);
            const timeout = setTimeout(() => {
                observer.disconnect();
                reject(new Error("IIB is unavailable in Forge. Enable the Infinite Image Browsing extension in Forge, restart Forge, then reload this page."));
            }, 12000);
            function check() {
                const value = nativeFrame();
                if (!value) return;
                clearTimeout(timeout);
                observer.disconnect();
                resolve(value);
            }
            observer.observe(document.documentElement, { childList: true, subtree: true });
            check();
        });
    }

    async function receiveTransfer(event) {
        const data = event.data;
        if (!data || typeof data !== "object") return;
        if (typeof data.IIB_container_id === "string" && data.IIB_container_id !== window.IIB_container_id) return;
        const destination = data.event === "click_hidden_button"
            && typeof data.btnEleId === "string"
            && data.btnEleId.match(/^iib_hidden_tab_(txt2img|img2img|inpaint|extras)$/);
        if (!destination || !host.mobile.isOpen()) return;

        // The installed IIB listener clicks the paste button once. This observer
        // only restores the native layout so the resulting paste is visible.
        handoff = handoff.then(async () => {
            if (!host.mobile.isOpen()) return;
            host.mobile.showTab("prompt");
            await host.mobile.close();
            host.notify("Sent to " + destination[1] + ". Open mobile workspace to continue there.");
        }).catch(error => host.notify(error.message));
        await handoff;
    }

    function listenForTransfers() {
        if (transferBus) return;
        transferBus = new BroadcastChannel("iib-image-transfer-bus");
        transferBus.addEventListener("message", receiveTransfer);
    }

    host.openIIB = () => {
        if (frame) return Promise.resolve(frame);
        if (loading) return loading;
        panel.replaceChildren();
        const status = document.createElement("p");
        status.className = "mobile-iib-status";
        status.setAttribute("role", "status");
        status.textContent = "Loading Infinite Image Browsing…";
        panel.append(status);

        loading = (async () => {
            try {
                const source = await waitForNativeFrame();
                listenForTransfers();
                const iframe = document.createElement("iframe");
                iframe.id = "mobile-iib-frame";
                iframe.title = "Infinite Image Browsing";
                iframe.setAttribute("allow", source.getAttribute("allow") || "clipboard-read; clipboard-write");
                // srcdoc retains the installed build's asset and API paths. The
                // new frame shares this 7862 parent and IIB's transfer receiver.
                if (source.srcdoc) {
                    iframe.srcdoc = source.srcdoc;
                } else {
                    const url = new URL(source.getAttribute("src") || "", location.href);
                    if (url.origin !== location.origin || !source.getAttribute("src")) {
                        throw new Error("The installed IIB frame must be served through this Forge client.");
                    }
                    iframe.src = url.href;
                }
                iframe.addEventListener("load", () => { status.remove(); }, { once: true });
                panel.append(iframe);
                frame = iframe;
                return iframe;
            } catch (error) {
                status.textContent = error.message;
                const retry = document.createElement("button");
                retry.type = "button";
                retry.className = "gradio-button mobile-iib-retry";
                retry.textContent = "Retry";
                retry.addEventListener("click", () => host.openIIB().catch(console.warn));
                panel.append(retry);
                throw error;
            } finally {
                loading = undefined;
            }
        })();
        return loading;
    };

    if (host.mobile.isOpen() && document.getElementById("mobile-overlay").dataset.activeTab === "iib") {
        host.openIIB().catch(console.warn);
    }

    host.extensions["iib-bridge"] = {
        ready: Promise.resolve(),
        getFrame: () => frame,
        dispose() {
            transferBus?.close();
            transferBus = undefined;
        }
    };

})().catch(error => {
    console.error("IIB mobile bridge could not load", error);
    window.MobileWorkspaceHost?.notify(error.message);
});
