/* Bind mobile layout helpers to Forge's own elements and event handlers. */
(() => {
    "use strict";
    const H = window.MobileWorkspaceHost;
    const get = id => document.getElementById(id);
    const el = (tag, props = {}, text) => {
        const node = document.createElement(tag);
        for (const [key, value] of Object.entries(props)) node.setAttribute(key, value);
        if (text) node.textContent = text;
        return node;
    };
    H.extensions ||= {};
    H.extensions["mobile-workspace"] = {
        ready: (async () => {
            const response = await fetch(H.assetUrl("mobile-workspace", "workspace.html"));
            if (!response.ok) throw new Error("Mobile workspace template unavailable");
            const template = document.createElement("template");
            template.innerHTML = await response.text();
            const root = typeof gradioApp === "function" ? gradioApp() : document;
            const container = root.querySelector(".gradio-container");
            container.append(template.content);
        })()
    };
    H.selectTab = tab => {
        if (tab === "txt2img") window.switch_to_txt2img();
        else if (tab === "img2img") {
            // Preserve the selected img2img mode when switching generation tabs.
            const tabs = get("tabs").querySelector(":scope > .tab-nav");
            tabs?.querySelectorAll("button")[1]?.click();
        }
    };
    H.emit = () => window.dispatchEvent(new Event("forge-mobile-update"));
    H.get = get;
    H.setValue = (id, value) => {
        const node = get(id);
        const input = node?.matches("input,textarea") ? node : node?.querySelector("textarea,input:not([type=range])");
        if (!input) return false;
        const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const property = input.type === "checkbox" ? "checked" : "value";
        Object.getOwnPropertyDescriptor(prototype, property).set.call(input, value);
        window.updateInput(input);
        input.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
    };

    H.createDockPanel = () => {
        const panel = el("div", { id: "mobile-docker-panel", class: "mobile-options fdm-manager-accordion" });
        const select = el("select", { class: "fdm-native-dock-select", "aria-label": "Dock" });
        const width = el("select", { class: "fdm-native-width-select", "aria-label": "Width" });
        width.append(new Option("Half", "half"), new Option("Full", "full"));
        const button = (title, click) => {
            const node = el("button", { type: "button", class: "gradio-button" }, title);
            node.addEventListener("click", click);
            return node;
        };
        const row = el("div", { class: "mobile-settings-file" });
        row.append(button("Open Dock", () => window.ForgeMobileDockManager.openDock(select.value, width.value)));
        const toggle = (title, callback) => {
            const label = el("label", { class: "checkbox" });
            const input = el("input", { type: "checkbox" });
            input.addEventListener("change", () => callback(input.checked));
            label.append(input, document.createTextNode(title));
            return { label, input };
        };
        const labels = toggle("Show labels", value => window.ForgeMobileDockManager.setDockLabelsVisible(value));
        const lock = toggle("Lock docks", value => window.ForgeMobileDockManager.setDocksLocked(value));
        let timer, deadline = 0;
        const clear = button("Close all docks", () => {
            if (performance.now() < deadline) {
                window.ForgeMobileDockManager.closeAllDocks();
                reset();
                return;
            }
            deadline = performance.now() + 2000;
            clear.textContent = "Are you sure?";
            clear.dataset.confirming = "";
            timer = setTimeout(reset, 2000);
        });
        function reset() {
            clearTimeout(timer);
            deadline = 0;
            clear.textContent = "Close all docks";
            delete clear.dataset.confirming;
        }
        const reload = button("Reload docks", async () => {
            reload.disabled = true;
            try {
                await window.ForgeMobileDockManager.fullRefreshDocks();
            } catch (error) {
                H.notify(error.message);
            } finally {
                reload.disabled = false;
            }
        });
        H.syncDockerPanel = tab => {
            select.id = tab + "_fm_fdm_dock_native";
            width.id = tab + "_fm_fdm_width_native";
            labels.input.id = tab + "_fm_fdm_labels";
            lock.input.id = tab + "_fm_fdm_lock_docks";
            reload.id = tab + "_fm_fdm_full_refresh";
            const state = window.ForgeMobileDockManager.getLayoutSnapshot();
            labels.input.checked = state.labels;
            lock.input.checked = state.locked;
        };
        H.fillDockChoices = () => {
            const choice = select.value;
            select.replaceChildren(...H.registry.docks.map(dock => new Option(dock.name, dock.id)));
            if (H.registry.docks.some(dock => dock.id === choice)) select.value = choice;
        };
        H.fillDockChoices();
        panel.append(select, width, row, labels.label, lock.label, clear, reload);
        return panel;
    };

    const catalog = new Map();
    const pattern = /<lora:([^:<>]+):([+-]?(?:\d+(?:\.\d*)?|\.\d+))>/g;
    function scanCards() {
        for (const tab of ["txt2img", "img2img"]) {
            for (const card of get(tab + "_lora")?.querySelectorAll(".card") || []) {
                const action = card.getAttribute("onclick") || "";
                const tag = action.match(/<lora:([^:<>]+):([^<>]+)>/);
                const name = tag?.[1] || card.dataset.name;
                if (!name) continue;
                catalog.set(name, {
                    label: card.querySelector(".name")?.textContent?.trim() || name,
                    image: card.querySelector("img")?.src || ""
                });
            }
        }
    }
    H.loras = {
        catalog,
        read(tab) {
            scanCards();
            const value = get(tab + "_prompt")?.querySelector("textarea")?.value || "";
            const enabled = new Map([...value.matchAll(pattern)].map(match => [match[1], Number(match[2])]));
            for (const name of enabled.keys()) if (!catalog.has(name)) catalog.set(name, { label: name, image: "" });
            return enabled;
        },
        write(tab, enabled) {
            const input = get(tab + "_prompt")?.querySelector("textarea");
            if (!input) return;
            const text = input.value.replace(pattern, "").trimEnd();
            const tags = [...enabled].map(([name, weight]) => `<lora:${name}:${weight}>`).join(" ");
            H.setValue(tab + "_prompt", text + (text && tags ? " " : "") + tags);
            get("mobile-lora-browser")?.dispatchEvent(new Event("loraschange"));
        },
        preview: name => catalog.get(name)?.image || ""
    };
})();
