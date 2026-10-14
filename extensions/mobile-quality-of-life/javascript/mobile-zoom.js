(() => {
    "use strict";

    const EXT = "mobile-quality-of-life/mobile-zoom";
    const CONTROL_ID = "forge-mobile-zoom-control";

    // Keep the existing viewport-mode storage keys so the user's saved zoom
    // carries over from the previous version.
    const STORAGE_SCALE = "forge-mobile-zoom-scale-v2";
    const STORAGE_ENABLED = "forge-mobile-zoom-enabled-v2";

    const DEFAULT_SCALE = 0.75;
    const MIN_SCALE = 0.50;
    const MAX_SCALE = 1.00;
    const STEP = 0.05;

    let control = null;
    let minusButton = null;
    let scaleButton = null;
    let plusButton = null;

    let viewportMeta = null;
    let hadOriginalViewportMeta = false;
    let originalViewportContent = null;

    let applyQueued = false;
    let applying = false;
    let mountQueued = false;

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function roundScale(value) {
        return Math.round(value * 100) / 100;
    }

    function readScale() {
        const raw = Number.parseFloat(localStorage.getItem(STORAGE_SCALE));
        if (!Number.isFinite(raw)) return DEFAULT_SCALE;
        return clamp(roundScale(raw), MIN_SCALE, MAX_SCALE);
    }

    function writeScale(value) {
        localStorage.setItem(STORAGE_SCALE, String(roundScale(value)));
    }

    function readEnabled() {
        const raw = localStorage.getItem(STORAGE_ENABLED);
        return raw === null ? true : raw !== "false";
    }

    function writeEnabled(enabled) {
        localStorage.setItem(STORAGE_ENABLED, enabled ? "true" : "false");
    }

    function isPhoneLike() {
        const shortSide = Math.min(screen.width || 9999, screen.height || 9999);
        return navigator.maxTouchPoints > 0 && shortSide <= 600;
    }

    function ensureViewportMeta() {
        if (viewportMeta && viewportMeta.isConnected) return viewportMeta;

        viewportMeta = document.querySelector('meta[name="viewport"]');

        if (originalViewportContent === null) {
            hadOriginalViewportMeta = !!viewportMeta;
            originalViewportContent = viewportMeta?.getAttribute("content") ?? null;
        }

        if (!viewportMeta) {
            viewportMeta = document.createElement("meta");
            viewportMeta.name = "viewport";
            document.head.appendChild(viewportMeta);
        }

        return viewportMeta;
    }

    function parseViewport(content) {
        const result = [];
        for (const rawPart of String(content || "").split(",")) {
            const part = rawPart.trim();
            if (!part) continue;
            const eq = part.indexOf("=");
            if (eq === -1) {
                result.push([part.toLowerCase(), null, part]);
            } else {
                result.push([
                    part.slice(0, eq).trim().toLowerCase(),
                    part.slice(eq + 1).trim(),
                    part,
                ]);
            }
        }
        return result;
    }

    function makeViewportContent(layoutWidth) {
        const preserved = [];

        for (const [key, _value, raw] of parseViewport(originalViewportContent)) {
            if (["width", "initial-scale", "minimum-scale", "maximum-scale"].includes(key)) {
                continue;
            }
            preserved.push(raw);
        }

        return [`width=${Math.round(layoutWidth)}`, ...preserved].join(", ");
    }

    function nativeViewportWidth() {
        const vv = window.visualViewport;
        if (
            vv &&
            Number.isFinite(vv.width) &&
            Number.isFinite(vv.scale) &&
            vv.scale > 0
        ) {
            const width = vv.width * vv.scale;
            if (width > 200 && width < 2000) return width;
        }

        if (window.innerWidth > 200 && window.innerWidth < 2000) {
            return window.innerWidth;
        }

        return screen.width || 390;
    }

    function restoreNativeViewport() {
        if (!viewportMeta && originalViewportContent === null) return;

        const meta = ensureViewportMeta();

        if (hadOriginalViewportMeta) {
            if (originalViewportContent === null) meta.removeAttribute("content");
            else meta.setAttribute("content", originalViewportContent);
        } else {
            meta.remove();
            viewportMeta = null;
        }

        document.documentElement.removeAttribute("data-forge-mobile-viewport-zoom");
        document.documentElement.style.removeProperty("--forge-mobile-viewport-scale");
        document.documentElement.style.removeProperty("--forge-mobile-viewport-inverse");
    }

    function applyViewportZoom() {
        applyQueued = false;
        if (applying) return;
        applying = true;

        try {
            mountControl();

            const phone = isPhoneLike();
            const enabled = readEnabled();
            const scale = readScale();

            if (control) {
                control.dataset.mobile = phone ? "true" : "false";
                control.dataset.enabled = enabled ? "true" : "false";
            }

            if (!phone || !enabled || scale >= 0.999) {
                restoreNativeViewport();
                updateControl();
                return;
            }

            const meta = ensureViewportMeta();
            const layoutWidth = nativeViewportWidth() / scale;
            meta.setAttribute("content", makeViewportContent(layoutWidth));

            // Only floating helper UI needs inverse compensation. The zoom
            // control now lives in Quicksettings and should scale with Forge.
            document.documentElement.dataset.forgeMobileViewportZoom = "true";
            document.documentElement.style.setProperty(
                "--forge-mobile-viewport-scale",
                String(scale),
            );
            document.documentElement.style.setProperty(
                "--forge-mobile-viewport-inverse",
                String(1 / scale),
            );

            updateControl();
        } catch (error) {
            console.warn(`[${EXT}] Unable to apply mobile viewport scaling`, error);
        } finally {
            applying = false;
        }
    }

    function queueApply(delay = 0) {
        if (applyQueued) return;
        applyQueued = true;

        const run = () => requestAnimationFrame(applyViewportZoom);
        if (delay > 0) setTimeout(run, delay);
        else run();
    }

    function setScale(value) {
        writeScale(clamp(roundScale(value), MIN_SCALE, MAX_SCALE));
        writeEnabled(true);
        applyViewportZoom();
    }

    function createButton(className, text, title) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `${className} forge-mobile-zoom-button`;
        button.textContent = text;
        button.title = title;
        button.setAttribute("aria-label", title);
        return button;
    }

    function buildControl() {
        control = document.createElement("div");
        control.id = CONTROL_ID;
        control.className = "forge-mobile-zoom-inline";
        control.setAttribute("role", "group");
        control.setAttribute("aria-label", "Mobile zoom");

        const label = document.createElement("div");
        label.className = "forge-mobile-zoom-label";
        label.textContent = "Zoom";

        const buttonRow = document.createElement("div");
        buttonRow.className = "forge-mobile-zoom-buttons";

        minusButton = createButton(
            "forge-mobile-zoom-minus",
            "−",
            "Show more Forge UI",
        );
        scaleButton = createButton(
            "forge-mobile-zoom-value",
            "75%",
            "Toggle mobile viewport scaling",
        );
        plusButton = createButton(
            "forge-mobile-zoom-plus",
            "+",
            "Show Forge UI larger",
        );

        minusButton.addEventListener("click", () => setScale(readScale() - STEP));
        plusButton.addEventListener("click", () => setScale(readScale() + STEP));
        scaleButton.addEventListener("click", () => {
            writeEnabled(!readEnabled());
            applyViewportZoom();
        });

        buttonRow.append(minusButton, scaleButton, plusButton);
        control.append(label, buttonRow);
    }

    function mountControl() {
        const quicksettings = document.getElementById("quicksettings");
        const checkpoint = document.getElementById("setting_sd_model_checkpoint");
        const vae = document.getElementById("setting_sd_modules");

        if (!quicksettings || !checkpoint) return false;

        const existing = document.getElementById(CONTROL_ID);
        if (existing) {
            control = existing;
            minusButton ||= control.querySelector(".forge-mobile-zoom-minus");
            scaleButton ||= control.querySelector(".forge-mobile-zoom-value");
            plusButton ||= control.querySelector(".forge-mobile-zoom-plus");
        } else {
            buildControl();
        }

        // Neo creates the model controls in this order:
        // UI Preset -> Checkpoint -> VAE / Text Encoder -> refresh -> dtype.
        // Insert before VAE, which places us immediately after Checkpoint and
        // lets #quicksettings' native flex wrapping choose the available gap.
        if (vae && vae.parentElement === quicksettings) {
            if (control.parentElement !== quicksettings || control.nextElementSibling !== vae) {
                quicksettings.insertBefore(control, vae);
            }
        } else if (checkpoint.parentElement === quicksettings) {
            checkpoint.insertAdjacentElement("afterend", control);
        } else if (!control.isConnected) {
            quicksettings.appendChild(control);
        }

        control.dataset.mobile = isPhoneLike() ? "true" : "false";
        updateControl();
        return true;
    }

    function queueMount() {
        if (mountQueued) return;
        mountQueued = true;
        requestAnimationFrame(() => {
            mountQueued = false;
            mountControl();
        });
    }

    function updateControl() {
        if (!control || !scaleButton || !minusButton || !plusButton) return;

        const scale = readScale();
        const enabled = readEnabled();
        const percent = Math.round(scale * 100);

        scaleButton.textContent = enabled ? `${percent}%` : "100%";
        scaleButton.dataset.bypassed = enabled ? "false" : "true";
        scaleButton.title = enabled
            ? `Forge mobile viewport is ${percent}%. Tap for native 100%.`
            : `Native 100% viewport. Tap to restore ${percent}%.`;

        minusButton.disabled = scale <= MIN_SCALE + 0.001;
        plusButton.disabled = scale >= MAX_SCALE - 0.001;
    }

    function initialize() {
        ensureViewportMeta();

        // Forge exposes lifecycle callbacks for UI insertion. Use those when
        // available, with a small retry fallback for unusually slow mobile load.
        if (typeof onUiLoaded === "function") {
            onUiLoaded(() => {
                mountControl();
                applyViewportZoom();
            });
        }

        if (typeof onAfterUiUpdate === "function") {
            onAfterUiUpdate(() => {
                if (!control?.isConnected) queueMount();
            });
        }

        if (!mountControl()) {
            let attempts = 0;
            const timer = setInterval(() => {
                attempts += 1;
                if (mountControl() || attempts >= 40) clearInterval(timer);
            }, 250);
        }

        applyViewportZoom();

        window.addEventListener("orientationchange", () => queueApply(250), {
            passive: true,
        });
        window.addEventListener("resize", () => queueApply(100), {
            passive: true,
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
