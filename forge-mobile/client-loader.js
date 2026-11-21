/* The companion adds assets only to the client served on its own port. */
(async () => {
    "use strict";
    const prefix = "/_forge_mobile";
    const response = await fetch(prefix + "/bootstrap", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not load the mobile workspace");
    const bootstrap = await response.json();
    const request = window.fetch.bind(window);
    let settings = bootstrap.settings;
    let pending = {};
    let saving = Promise.resolve();
    let timer;
    const assetVersions = new Map(bootstrap.extensions.map(extension => [extension.id, extension.asset_version]));

    function assetUrl(extension, file) {
        const version = assetVersions.get(extension);
        return prefix + "/extensions/" + encodeURIComponent(extension) + "/" + file + "?v=" + version;
    }

    function flush() {
        clearTimeout(timer);
        const patch = pending;
        pending = {};
        if (!Object.keys(patch).length) return saving;
        saving = saving.catch(() => {}).then(async () => {
            try {
                const result = await request(prefix + "/settings", {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(patch), keepalive: true
                });
                if (!result.ok) throw new Error("Mobile settings could not be saved");
            } catch (error) {
                pending = { ...patch, ...pending };
                timer = setTimeout(flush, 1500);
                console.warn(error);
            }
        });
        return saving;
    }

    const host = window.MobileWorkspaceHost = {
        prefix, assetUrl, defaults: structuredClone(settings), registry: bootstrap.registry,
        settingsKeys: Object.keys(settings),
        storage: {
            get: (key, fallback = null) => settings[key] ?? fallback,
            set(key, value) {
                settings[key] = structuredClone(value);
                pending[key] = structuredClone(value);
                clearTimeout(timer);
                timer = setTimeout(flush, 120);
                return true;
            },
            remove(key) {
                delete settings[key];
            }
        },
        flush,
        notify(message) {
            let status = document.getElementById("mobile-client-status");
            if (!status) {
                status = document.createElement("div");
                status.id = "mobile-client-status";
                status.setAttribute("role", "status");
                status.style.cssText = "position:fixed;bottom:40px;left:12px;right:12px;z-index:12000;padding:10px;background:#211823;color:#f4eaf2;pointer-events:none";
                document.body.append(status);
            }
            status.textContent = message;
            status.hidden = false;
            clearTimeout(host.statusTimer);
            host.statusTimer = setTimeout(() => { status.hidden = true; }, 5000);
        }
    };
    window.addEventListener("pagehide", flush);
    window.addEventListener("online", flush);

    // Gradio builds the native components before mobile extensions attach to them.
    await new Promise(resolve => {
        const ready = () => {
            if (document.getElementById("txt2img_generate") && document.getElementById("img2img_generate")) {
                resolve();
                return true;
            }
        };
        if (ready()) return;
        const observer = new MutationObserver(() => { if (ready()) observer.disconnect(); });
        observer.observe(document.documentElement, { subtree: true, childList: true });
    });
    await document.fonts?.ready;
    for (const extension of bootstrap.extensions) {
        for (const file of extension.styles || []) {
            await new Promise((resolve, reject) => {
                const link = document.createElement("link");
                link.rel = "stylesheet";
                link.href = assetUrl(extension.id, file);
                link.onload = resolve;
                link.onerror = reject;
                document.head.append(link);
            });
        }
        for (const file of extension.scripts || []) {
            await new Promise((resolve, reject) => {
                const script = document.createElement("script");
                script.src = assetUrl(extension.id, file);
                script.onload = resolve;
                script.onerror = reject;
                document.head.append(script);
            });
        }
        await host.extensions?.[extension.id]?.ready;
    }
})().catch(error => {
    console.error("Mobile client initialization failed", error);
    window.MobileWorkspaceHost?.notify("Mobile workspace could not load. Check the companion console and reload.");
});
