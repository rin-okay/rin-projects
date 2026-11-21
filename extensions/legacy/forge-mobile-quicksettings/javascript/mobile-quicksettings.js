(() => {
    "use strict";

    const QUICKSETTINGS_ID = "quicksettings";
    const TOGGLE_ID = "fmqs-quicksettings-toggle";
    const OPTIONS_ID = "fmqs-quicksettings-options";
    const HIDE_STYLES_ID = "fmqs-hide-styles";
    const STORAGE_KEY = "forge-mobile-quicksettings:hide-styles-v1";

    let mountQueued = false;

    function isPhoneLike() {
        const shortSide = Math.min(screen.width || 9999, screen.height || 9999);
        return navigator.maxTouchPoints > 0 && shortSide <= 600;
    }

    function readHideStyles() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored === null) return true;
            return stored !== "false";
        } catch (_error) {
            return true;
        }
    }

    function saveHideStyles(value) {
        try {
            localStorage.setItem(STORAGE_KEY, value ? "true" : "false");
        } catch (_error) {
            // localStorage can be unavailable in restrictive/private modes.
        }
    }

    function setCollapsed(quicksettings, toggle, collapsed) {
        quicksettings.dataset.fmqsCollapsed = collapsed ? "true" : "false";
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");

        const arrow = toggle.querySelector(".fmqs-quicksettings-arrow");
        if (arrow) arrow.textContent = collapsed ? "▶" : "▼";
    }

    function buildToggle(quicksettings) {
        const toggle = document.createElement("button");
        toggle.id = TOGGLE_ID;
        toggle.type = "button";
        toggle.className = "fmqs-quicksettings-toggle";
        toggle.setAttribute("aria-controls", QUICKSETTINGS_ID);
        toggle.setAttribute("aria-expanded", "false");

        const label = document.createElement("span");
        label.className = "fmqs-quicksettings-label";
        label.textContent = "Quick Settings";

        const arrow = document.createElement("span");
        arrow.className = "fmqs-quicksettings-arrow";
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "▶";

        toggle.append(label, arrow);
        toggle.addEventListener("click", () => {
            const collapsed = quicksettings.dataset.fmqsCollapsed !== "false";
            setCollapsed(quicksettings, toggle, !collapsed);
        });

        return toggle;
    }

    function buildOptions() {
        const row = document.createElement("div");
        row.id = OPTIONS_ID;
        row.className = "fmqs-quicksettings-options";

        const label = document.createElement("label");
        label.className = "fmqs-checkbox-label";
        label.htmlFor = HIDE_STYLES_ID;

        const checkbox = document.createElement("input");
        checkbox.id = HIDE_STYLES_ID;
        checkbox.type = "checkbox";
        checkbox.checked = readHideStyles();

        const text = document.createElement("span");
        text.textContent = "Hide Styles bar";

        label.append(checkbox, text);
        row.append(label);

        checkbox.addEventListener("change", () => {
            saveHideStyles(checkbox.checked);
            applyStylesVisibility();
        });

        return row;
    }

    function stylesRows() {
        return [
            document.getElementById("txt2img_styles_row"),
            document.getElementById("img2img_styles_row"),
        ].filter(Boolean);
    }

    function clearCompactWrapperMarker(row) {
        const parent = row?.parentElement;
        if (parent?.dataset?.fmqsStylesWrapper === "true") {
            delete parent.dataset.fmqsStylesWrapper;
        }
    }

    function markCompactWrapperIfNeeded(row, hidden) {
        if (!row?.parentElement) return;
        const parent = row.parentElement;

        // In Forge's Compact prompt layout, the Styles row is wrapped in its
        // own Gradio column. Hide that otherwise-empty column too. In Classic
        // layouts the row shares its parent with other controls, so leave it.
        const elementChildren = [...parent.children].filter((child) => child instanceof HTMLElement);
        const onlyVisibleContent = elementChildren.length === 1 && elementChildren[0] === row;
        if (hidden && onlyVisibleContent) parent.dataset.fmqsStylesWrapper = "true";
        else if (!hidden) clearCompactWrapperMarker(row);
    }

    function applyStylesVisibility() {
        const mobile = isPhoneLike();
        const checkbox = document.getElementById(HIDE_STYLES_ID);
        const hide = mobile && (checkbox ? checkbox.checked : readHideStyles());

        for (const row of stylesRows()) {
            row.dataset.fmqsStylesHidden = hide ? "true" : "false";
            markCompactWrapperIfNeeded(row, hide);
        }
    }

    function mount() {
        const quicksettings = document.getElementById(QUICKSETTINGS_ID);
        if (!quicksettings) {
            applyStylesVisibility();
            return false;
        }

        let toggle = document.getElementById(TOGGLE_ID);
        if (!toggle) toggle = buildToggle(quicksettings);
        if (toggle.parentElement !== quicksettings) {
            quicksettings.insertBefore(toggle, quicksettings.firstChild);
        }

        let options = document.getElementById(OPTIONS_ID);
        if (!options) options = buildOptions();
        if (options.parentElement !== quicksettings) {
            toggle.insertAdjacentElement("afterend", options);
        }

        const mobile = isPhoneLike();
        quicksettings.dataset.fmqsMobile = mobile ? "true" : "false";
        toggle.hidden = !mobile;
        options.hidden = !mobile;

        // Phone UI starts collapsed on each fresh page load. Lifecycle updates
        // preserve the user's current open/closed state after initial mounting.
        if (mobile && !quicksettings.hasAttribute("data-fmqs-mounted")) {
            setCollapsed(quicksettings, toggle, true);
        }

        quicksettings.dataset.fmqsMounted = "true";
        applyStylesVisibility();
        return true;
    }

    function queueMount() {
        if (mountQueued) return;
        mountQueued = true;
        requestAnimationFrame(() => {
            mountQueued = false;
            mount();
        });
    }

    function initialize() {
        if (typeof onUiLoaded === "function") onUiLoaded(mount);
        if (typeof onAfterUiUpdate === "function") onAfterUiUpdate(queueMount);
        if (typeof onUiTabChange === "function") onUiTabChange(queueMount);

        if (!mount()) {
            let attempts = 0;
            const timer = setInterval(() => {
                attempts += 1;
                if (mount() || attempts >= 40) clearInterval(timer);
            }, 250);
        }

        window.addEventListener("orientationchange", () => setTimeout(queueMount, 100), { passive: true });
        window.addEventListener("resize", queueMount, { passive: true });
    }

    initialize();
})();
