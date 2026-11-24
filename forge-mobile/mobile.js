/* Loaded only through the companion. Forge's usual frontend still owns the controls. */
(() => {
    const prefix = "/_forge_mobile";
    const request = window.fetch.bind(window);
    const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    // Installed before Gradio initializes, and only in the 7862 response.
    // Informational alerts must never pause queue/reconnect or resize handlers.
    let noticeTimer;
    function nonblockingNotice(message) {
        console.warn("Forge notice:", message);
        if (window.MobileWorkspaceHost) {
            window.MobileWorkspaceHost.notify(String(message ?? ""));
            return;
        }
        if (!document.body) {
            document.addEventListener("DOMContentLoaded", () => nonblockingNotice(message), { once: true });
            return;
        }
        let status = document.getElementById("mobile-warning-status");
        if (!status) {
            status = document.createElement("div");
            status.id = "mobile-warning-status";
            status.setAttribute("role", "status");
            status.style.cssText = "position:fixed;bottom:40px;left:12px;right:12px;z-index:12000;" +
                "padding:10px;background:#211823;color:#f4eaf2;pointer-events:none";
            document.body.append(status);
        }
        status.textContent = String(message ?? "");
        status.hidden = false;
        clearTimeout(noticeTimer);
        noticeTimer = setTimeout(() => { status.hidden = true; }, 5000);
    }
    window.alert = nonblockingNotice;
    const nativeConfirm = window.confirm.bind(window);
    window.confirm = message => {
        const warning = String(message ?? "");
        // A compatibility warning is not a delete/overwrite decision. Allow
        // the requested navigation to proceed without opening a modal dialog.
        if (/mobile/i.test(warning) && /break|chang|switch|window|resiz|screen|reload|leave|navigat/i.test(warning)) {
            nonblockingNotice(warning);
            return true;
        }
        return nativeConfirm(message);
    };
    // Forge's confirm_leave is a browser-level warning, separate from alerts.
    // pagehide still flushes settings/fields; generation remains owned by PC.
    window.addEventListener("beforeunload", event => event.stopImmediatePropagation(), { capture: true });

    window.forgeMobilePrepareImg2imgHires = data => {
        const overlay = document.getElementById("mobile-overlay");
        if (!overlay || overlay.hidden) return;
        const prompts = ["img2img_prompt", "img2img_neg_prompt"].map(id =>
            document.getElementById(id)?.querySelector("textarea")?.value ?? "");
        data.push({ forge_mobile_img2img_prompts: prompts });
        const button = document.getElementById("img2img_hires_fix_manual_button");
        if (button?.getAttribute("aria-busy") === "true") {
            button.disabled = false;
            button.removeAttribute("aria-busy");
        }
    };

    const pendingFields = new Map();
    let fieldTimer;
    let fieldSave = Promise.resolve();
    let fieldFingerprint;

    function flushFields() {
        clearTimeout(fieldTimer);
        const updates = Object.fromEntries(pendingFields);
        pendingFields.clear();
        if (!Object.keys(updates).length) return fieldSave;
        fieldSave = fieldSave.catch(() => {}).then(async () => {
            try {
                const response = await request(prefix + "/fields", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ fingerprint: fieldFingerprint, updates }),
                    keepalive: true
                });
                if (!response.ok) throw new Error("Could not save Forge controls");
            } catch (error) {
                for (const [key, value] of Object.entries(updates)) {
                    if (!pendingFields.has(key)) pendingFields.set(key, value);
                }
                fieldTimer = setTimeout(() => flushFields().catch(console.warn), 1500);
                throw error;
            }
        });
        return fieldSave;
    }

    window.forgeMobileSaveField = (component, fingerprint, value) => {
        fieldFingerprint = fingerprint;
        pendingFields.set(String(component), value);
        clearTimeout(fieldTimer);
        fieldTimer = setTimeout(() => flushFields().catch(console.warn), 180);
        return [];
    };
    window.addEventListener("pagehide", () => flushFields().catch(console.warn));
    window.addEventListener("online", () => flushFields().catch(console.warn));
    window.forgeMobileFlushFields = flushFields;

    // Keep one readable stream alive for Gradio through a temporary phone disconnect.
    // Gradio 4.40 can otherwise resubmit a generation on its mobile error path.
    window.fetch = async (input, options) => {
        const url = new URL(input instanceof Request ? input.url : input, location.href);
        if (url.origin !== location.origin) return request(input, options);
        if (url.pathname === "/queue/join" && typeof options?.body === "string") {
            await flushFields().catch(console.warn);
            let task;
            try { task = JSON.parse(options.body).data?.[0]; } catch { /* ordinary request */ }
            if (typeof task === "string" && /^task\([\w-]+\)$/.test(task)) {
                try {
                    return await request(input, options);
                } catch (error) {
                    if (options.signal?.aborted) throw error;
                    await pause(500);
                    return request(input, options);
                }
            }
        }
        if (url.pathname !== "/queue/data" || !url.searchParams.has("session_hash")) {
            return request(input, options);
        }

        const abort = new AbortController();
        if (options?.signal?.aborted) abort.abort();
        else options?.signal?.addEventListener("abort", () => abort.abort(), { once: true });
        const encoder = new TextEncoder();
        const stream = new ReadableStream({
            async start(controller) {
                let cursor = "";
                while (!abort.signal.aborted) {
                    if (cursor) url.searchParams.set("__fm_after", cursor);
                    let reader;
                    try {
                        const response = await request(url, { ...options, signal: abort.signal });
                        if (!response.ok) {
                            if (response.status === 401 || response.status === 403) {
                                controller.error(new Error("Forge Mobile could not open the queue stream"));
                                return;
                            }
                            throw new Error("Queue stream unavailable");
                        }
                        reader = response.body.getReader();
                        const decoder = new TextDecoder();
                        let pending = "";
                        while (!abort.signal.aborted) {
                            const { done, value } = await reader.read();
                            if (done) break;
                            pending += decoder.decode(value, { stream: true });
                            let end;
                            while ((end = pending.indexOf("\n\n")) !== -1) {
                                const frame = pending.slice(0, end);
                                pending = pending.slice(end + 2);
                                const id = frame.match(/^id: (\d+)/)?.[1];
                                const data = frame.split("\n").find((line) => line.startsWith("data: "));
                                if (!data) continue;
                                if (id) cursor = id;
                                controller.enqueue(encoder.encode(data + "\n\n"));
                                if (JSON.parse(data.slice(6)).msg === "close_stream") {
                                    controller.close();
                                    return;
                                }
                            }
                        }
                    } catch {
                        // The PC still owns the job. Wait for the phone's network to return.
                    } finally {
                        if (reader) {
                            reader.cancel().catch(() => {});
                            reader.releaseLock();
                        }
                    }
                    if (!abort.signal.aborted) await pause(750);
                }
                try { controller.close(); } catch { /* caller already cancelled */ }
            },
            cancel() {
                abort.abort();
            }
        });
        return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
    };

    let revision = window.forgeMobileRevision;
    let busy = false;
    let status;
    let lastError = null;
    let savedResults = {};
    let initialized = false;
    let progressTask = null;
    let progressRequest = null;

    function showStatus(message, generating = false) {
        if (!status) {
            status = document.createElement("div");
            status.id = "forge-mobile-status";
            status.setAttribute("role", "status");
            status.style.cssText = "position:fixed;bottom:12px;left:12px;right:12px;z-index:10000;" +
                "margin:auto;width:max-content;max-width:calc(100vw - 24px);padding:8px 13px;" +
                "background:#272331;color:#fff;border-radius:9px;font:13px system-ui;pointer-events:none";
            document.body.append(status);
        }
        status.toggleAttribute("data-generation", generating);
        status.textContent = message;
        status.hidden = !message;
    }

    function updateGenerationProgress(job) {
        const bar = document.getElementById("mobile-generation-progress");
        const task = job?.status === "running" ? job.task_id : null;
        const changed = task !== progressTask;
        if (changed) {
            progressRequest?.abort();
            progressRequest = null;
            progressTask = task;
        }
        if (!bar) return;
        bar.hidden = !task;
        if (changed || !task) bar.removeAttribute("value");
        if (!task || progressRequest) return;

        const controller = new AbortController();
        progressRequest = controller;
        const timeout = setTimeout(() => controller.abort(), 3500);
        request("/internal/progress", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id_task: task, live_preview: false }),
            cache: "no-store",
            signal: controller.signal
        }).then(async response => {
            if (!response.ok) return;
            const progress = await response.json();
            if (progressRequest !== controller) return;
            if (progress.active && Number.isFinite(progress.progress)) {
                bar.value = Math.max(0, Math.min(1, progress.progress));
            }
            else bar.removeAttribute("value");
        }).catch(() => {}).finally(() => {
            clearTimeout(timeout);
            if (progressRequest === controller) progressRequest = null;
        });
    }

    // Called by an ordinary frontend-only Gradio event. Gradio applies these values
    // to its own Gallery, generation-info textbox and other native outputs.
    window.forgeMobilePull = async (root, outputs) => {
        if (!initialized) {
            initialized = true;
            const trigger = () => {
                if (document.hidden || busy) return;
                const target = document.querySelector("gradio-app .gradio-container") ||
                    document.querySelector("gradio-app")?.shadowRoot?.querySelector(".gradio-container");
                target?.dispatchEvent(new CustomEvent("gradio", {
                    detail: { id: root, event: "forge_mobile_pull" }
                }));
            };
            window.addEventListener("pageshow", trigger);
            document.addEventListener("visibilitychange", trigger);
            window.addEventListener("online", trigger);
            setInterval(trigger, 1800);
        }
        if (busy) return [];
        busy = true;
        try {
            const response = await request(prefix + "/state", { cache: "no-store" });
            if (!response.ok) throw new Error("Could not pull workspace");
            const state = await response.json();
            const jobs = state.jobs.slice().reverse();
            const job = jobs.find((item) => item.status === "running") || jobs.find((item) => item.status === "queued");
            const latest = state.jobs.at(-1);
            updateGenerationProgress(job);
            if (job) {
                showStatus(job.status === "running" ? "Generating on the PC…" : "Queued on the PC…", job.status === "running");
            } else if (latest?.status === "failed" && lastError !== latest.task_id) {
                lastError = latest.task_id;
                showStatus("Forge did not complete the last job");
                setTimeout(() => { if (!busy && status?.textContent === "Forge did not complete the last job") showStatus(""); }, 5000);
            } else if (latest?.status !== "failed") {
                showStatus("");
            }
            const previous = savedResults;
            savedResults = state.results;
            if (state.revision === revision) return [];
            revision = state.revision;
            return outputs.map((id) => {
                const props = state.results[id];
                return props && JSON.stringify(props) !== JSON.stringify(previous[id])
                    ? { ...props, __type__: "update" }
                    : { __type__: "update" };
            });
        } catch {
            updateGenerationProgress(null);
            showStatus("Reconnecting to the PC…");
            return [];
        } finally {
            busy = false;
        }
    };
})();
