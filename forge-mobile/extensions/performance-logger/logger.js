/* Opt-in diagnostics for both workspace views served by Forge Mobile. */
(() => {
    "use strict";

    const prefix = "[Forge Mobile trace]";
    const reportLimit = 160;
    const routes = new Set([
        "/_forge_mobile/state", "/_forge_mobile/fields", "/_forge_mobile/settings",
        "/queue/join", "/api/predict", "/run/predict", "/api/predict/", "/run/predict/",
        "/internal/progress"
    ]);
    const promptId = /^(?:(?:txt2img|img2img)_(?:hr_)?(?:neg_)?prompt|hires_(?:neg_)?prompt)$/;
    const seedId = /^(?:txt2img|img2img)_(?:reuse_|random_)?(?:sub)?seed$/;
    const mobileTabId = /^mobile-tab-(?:prompt|params|panels|loras|iib)$/;
    const eventTypes = ["pointerup", "click", "beforeinput", "input", "change"];
    const round = n => Math.round(n * 10) / 10;
    const now = () => performance.now();
    const safeDuration = (end, start) => end >= start && start >= 0 ? round(end - start) : null;

    let capture;
    let recent = [];
    let pending = [];
    let flushTimer;
    let frame;
    let awaitingFrame = [];
    let lastRelease;

    function view() {
        return document.getElementById("mobile-overlay")?.hidden === false ? "mobile" : "native";
    }

    function targetName(node) {
        if (!(node instanceof Element)) return "unknown";
        for (let element = node; element; element = element.parentElement) {
            const id = element.id;
            if (promptId.test(id) || seedId.test(id) || mobileTabId.test(id) ||
                id === "settings_search" || id === "mobile-toggle-bar") return id;
        }
        if (node.closest("#settings .tab-nav button")) return "settings-tab";
        if (node.closest("#tabs > .tab-nav button")) return "native-tab";
        if (node.closest(".fm-seed-tool")) return "seed-dock-button";
        if (node.closest("[id^='generation_info_']")) return "generation-info";
        if (node.closest(".fdm-dock-shell")) return "dock-control";
        return node.closest("textarea, input, select")?.localName || "control";
    }

    function flush() {
        clearTimeout(flushTimer);
        flushTimer = undefined;
        if (!pending.length) return;
        console.info(prefix, pending);
        pending = [];
    }

    function add(kind, details) {
        const row = { kind, ...details };
        if (recent.length === reportLimit) recent.shift();
        if (pending.length === reportLimit) pending.shift();
        recent.push(row);
        pending.push(row);
        if (flushTimer === undefined) flushTimer = setTimeout(flush, 250);
    }

    function afterFrame(event, target, at) {
        if (document.hidden || awaitingFrame.length >= 32) return;
        awaitingFrame.push({ at: round(at), event, target });
        if (frame !== undefined) return;
        // The second callback follows a rendering opportunity. It is an estimate
        // of UI responsiveness on browsers without Event Timing.
        frame = requestAnimationFrame(() => {
            frame = requestAnimationFrame(() => {
                frame = undefined;
                const end = now();
                for (const item of awaitingFrame) {
                    const elapsed = safeDuration(end, item.at);
                    if (elapsed >= 48) add("frame-delay", { ...item, nextFrameMs: elapsed });
                }
                awaitingFrame = [];
            });
        });
    }

    function inputEvent(event) {
        if (document.hidden) return;
        const at = now();
        const target = targetName(event.target);
        const start = event.timeStamp;
        const details = {
            at: round(at), event: event.type, target, view: view(),
            trusted: event.isTrusted, dispatchDelayMs: safeDuration(at, start)
        };
        if (event.type === "pointerup") {
            if (event.isTrusted) lastRelease = { at, start, target };
        } else if (event.type === "click" && event.isTrusted) {
            if (target === lastRelease?.target && at - lastRelease.at < 1000) {
                details.releaseToClickMs = safeDuration(at, lastRelease.start);
            }
            lastRelease = undefined;
        }
        add("interaction", details);
        if (event.type === "click" || event.type === "input") afterFrame(event.type, target, at);
    }

    function resource(entry) {
        if (document.hidden || !["fetch", "xmlhttprequest"].includes(entry.initiatorType)) return;
        const url = new URL(entry.name, location.href);
        if (url.origin !== location.origin || !routes.has(url.pathname)) return;
        if (url.pathname === "/_forge_mobile/state" && entry.duration < 100) return;
        add("request", {
            at: round(entry.startTime), route: url.pathname, totalMs: round(entry.duration),
            firstByteMs: entry.responseStart > 0 ? safeDuration(entry.responseStart, entry.startTime) : null,
            status: entry.responseStatus || null
        });
    }

    function observe(type, handle, options) {
        if (!window.PerformanceObserver?.supportedEntryTypes?.includes(type)) return false;
        try {
            const observer = new PerformanceObserver(list => list.getEntries().forEach(handle));
            observer.observe({ type, ...options });
            capture.observers.push(observer);
            return true;
        } catch {
            return false;
        }
    }

    function queueMessage(phase, id, success) {
        if (document.hidden) return;
        if (!["process_starts", "process_completed"].includes(phase)) return;
        const at = now();
        let elapsed = null;
        if (typeof id === "string") {
            if (phase === "process_starts") {
                if (capture.jobs.size >= 32) capture.jobs.delete(capture.jobs.keys().next().value);
                capture.jobs.set(id, at);
            } else {
                if (capture.jobs.has(id)) elapsed = safeDuration(at, capture.jobs.get(id));
                capture.jobs.delete(id);
            }
        }
        add("queue", { at: round(at), phase, betweenMessagesMs: elapsed, success: success ?? null });
    }

    function stopFrames() {
        if (frame !== undefined) cancelAnimationFrame(frame);
        frame = undefined;
        awaitingFrame = [];
        lastRelease = undefined;
    }

    function start() {
        if (capture) return;
        recent = [];
        capture = { listeners: new AbortController(), observers: [], jobs: new Map() };
        const { signal } = capture.listeners;
        for (const type of eventTypes) {
            document.addEventListener(type, inputEvent, { capture: true, passive: true, signal });
        }
        document.addEventListener("visibilitychange", () => {
            stopFrames();
            capture.jobs.clear();
            if (document.hidden) flush();
        }, { signal });
        const observers = {
            resource: observe("resource", resource),
            eventTiming: observe("event", entry => {
                if (document.hidden || !["keydown", "beforeinput", "input", "pointerup", "click"].includes(entry.name)) return;
                add("event-timing", {
                    at: round(entry.startTime), event: entry.name, target: targetName(entry.target),
                    dispatchDelayMs: safeDuration(entry.processingStart, entry.startTime),
                    handlerMs: safeDuration(entry.processingEnd, entry.processingStart),
                    throughPaintMs: round(entry.duration)
                });
            }, { durationThreshold: 16 }),
            longTask: observe("longtask", entry => {
                if (!document.hidden) add("long-task", { at: round(entry.startTime), durationMs: round(entry.duration) });
            })
        };
        api.queueMessage = queueMessage;
        console.info(prefix, "Recording 7862 interactions", observers);
    }

    function stop() {
        if (!capture) return;
        delete api.queueMessage;
        capture.listeners.abort();
        for (const observer of capture.observers) observer.disconnect();
        capture = undefined;
        stopFrames();
        flush();
        console.info(prefix, "Stopped");
    }

    const api = window.ForgeMobileTrace = { start, stop, report: () => recent.map(row => ({ ...row })) };
    if (new URLSearchParams(location.search).get("forgeTrace") === "1") start();
})();
