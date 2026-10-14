(() => {
    "use strict";

    const DOCK_ID = "full-gallery-preview";
    const RETRY_DELAYS = [0, 60, 180, 450];

    function galleryRoot(ctx, tabName) {
        if (tabName !== "txt2img" && tabName !== "img2img") return null;
        const root = ctx.getById(`${tabName}_gallery`);
        if (!root) return null;
        if (root.matches?.(".gradio-gallery")) return root;
        return root.querySelector?.(".gradio-gallery") || root;
    }

    function nativeGalleryItems(gallery) {
        if (!gallery) return [];

        // Gradio 4.40 always renders the main gallery grid while gallery data
        // exists, even when selected_index is null. The small thumbnail strip
        // lives inside the preview overlay and disappears when nothing is
        // selected, so it must not be our source of truth.
        let items = [...gallery.querySelectorAll?.(".grid-container > .thumbnail-item.thumbnail-lg") || []];
        if (!items.length) {
            items = [...gallery.querySelectorAll?.(".thumbnail-item.thumbnail-lg") || []];
        }

        // Compatibility fallback for minor Gradio markup changes.
        if (!items.length) {
            items = [...gallery.querySelectorAll?.(".thumbnails > .thumbnail-item.thumbnail-small") || []];
        }

        return items.filter((item) => !item.closest?.(".fdm-dock-shell"));
    }

    function thumbnailImage(item) {
        return item?.querySelector?.("img") || null;
    }

    function looksLikePlaceholder(src) {
        if (!src) return true;
        const value = String(src).trim().toLowerCase();
        if (!value) return true;
        if (value === "about:blank") return true;
        if (value.startsWith("data:image/svg+xml")) return true;
        if (value.includes("transparent") && value.startsWith("data:image")) return true;
        return false;
    }

    function srcsetFirst(srcset) {
        if (!srcset) return "";
        const first = String(srcset).split(",")[0]?.trim() || "";
        return first.split(/\s+/)[0] || "";
    }

    function imageSource(img) {
        if (!img) return "";

        // Lazy-rendered Gradio images can retain the real URL outside `src`
        // while the gallery is offscreen. Prefer those explicit lazy sources.
        const candidates = [
            img.dataset?.src,
            img.dataset?.original,
            img.dataset?.lazySrc,
            img.getAttribute?.("data-src"),
            img.getAttribute?.("data-original"),
            img.getAttribute?.("data-lazy-src"),
            img.currentSrc,
            img.getAttribute?.("src"),
            img.src,
            srcsetFirst(img.getAttribute?.("srcset")),
        ];

        return candidates.find((src) => src && !looksLikePlaceholder(src)) || "";
    }

    function thumbnailSource(item) {
        return imageSource(thumbnailImage(item));
    }

    function isSelected(item) {
        return Boolean(
            item?.classList?.contains("selected")
            || item?.getAttribute?.("aria-selected") === "true"
            || item?.dataset?.selected === "true"
        );
    }

    function selectedPreviewImage(gallery) {
        if (!gallery) return null;
        return gallery.querySelector?.(":scope > button > button > img")
            || gallery.querySelector?.("button > button > img")
            || null;
    }

    function selectedItem(gallery) {
        const items = nativeGalleryItems(gallery);
        if (!items.length) return null;

        const selected = items.find(isSelected);
        if (selected) return selected;

        const previewSrc = imageSource(selectedPreviewImage(gallery));
        if (previewSrc) {
            const match = items.find((item) => thumbnailSource(item) === previewSrc);
            if (match) return match;
        }

        return items[0];
    }

    function clickNative(node) {
        if (!node) return;
        if (typeof node.click === "function") node.click();
        else node.dispatchEvent(new MouseEvent("click", {
            bubbles: true,
            cancelable: true,
            button: 0,
            view: window,
        }));
    }

    function hydrateNativeGallery(gallery) {
        if (!gallery) return;

        for (const item of nativeGalleryItems(gallery)) {
            const img = thumbnailImage(item);
            if (!img) continue;

            // Tell Safari/Gradio there is no reason to defer the thumbnail just
            // because the original gallery is currently offscreen.
            img.loading = "eager";

            const lazySrc = [
                img.dataset?.src,
                img.dataset?.original,
                img.dataset?.lazySrc,
                img.getAttribute?.("data-src"),
                img.getAttribute?.("data-original"),
                img.getAttribute?.("data-lazy-src"),
            ].find((src) => src && !looksLikePlaceholder(src));

            const current = imageSource(img);
            if (lazySrc && (!current || looksLikePlaceholder(img.getAttribute?.("src")))) {
                try { img.src = lazySrc; } catch (_error) { /* best effort */ }
            }
        }
    }

    function rematerializeSelectedPreview(gallery) {
        if (!gallery) return;
        const item = selectedItem(gallery) || nativeGalleryItems(gallery)[0] || null;
        if (!item) return;

        // Clicking the already-active thumbnail is enough to make Gradio rebuild
        // its selected preview, but does not open the lightbox or scroll the page.
        clickNative(item);
    }

    function openCurrentLightbox(gallery) {
        if (!gallery) return;
        const item = selectedItem(gallery) || nativeGalleryItems(gallery)[0] || null;
        if (!item) return;

        clickNative(item);

        const openPreview = () => {
            const preview = selectedPreviewImage(gallery);
            if (!preview) return false;
            try {
                if (!preview.dataset?.modded && typeof window.setupImageForLightbox === "function") {
                    window.setupImageForLightbox(preview);
                }
            } catch (_error) {
                // normal Forge lifecycle owns this; best effort only
            }
            preview.dispatchEvent(new MouseEvent("click", {
                bubbles: true,
                cancelable: true,
                button: 0,
                view: window,
            }));
            return true;
        };

        requestAnimationFrame(() => {
            if (!openPreview()) setTimeout(openPreview, 40);
        });
    }

    function selectGalleryItem(item) {
        clickNative(item);
    }

    function mount(container, ctx) {
        const root = document.createElement("div");
        root.className = "fdm-full-gallery-preview-root";

        const previewButton = document.createElement("button");
        previewButton.type = "button";
        previewButton.className = "fdm-full-gallery-preview-main";
        previewButton.title = "Open current gallery image";
        previewButton.setAttribute("aria-label", "Open current gallery image in lightbox");

        const previewImg = document.createElement("img");
        previewImg.className = "fdm-full-gallery-preview-image";
        previewImg.alt = "Current gallery image";
        previewImg.decoding = "async";
        previewImg.loading = "eager";

        const previewEmpty = document.createElement("div");
        previewEmpty.className = "fdm-full-gallery-preview-empty";
        previewEmpty.textContent = "No images";

        previewButton.append(previewImg, previewEmpty);

        const strip = document.createElement("div");
        strip.className = "fdm-full-gallery-preview-strip";

        const grabButton = document.createElement("button");
        grabButton.type = "button";
        grabButton.className = "fdm-full-gallery-preview-grab";
        grabButton.textContent = "↻";
        grabButton.title = "Refresh gallery preview";
        grabButton.setAttribute("aria-label", "Refresh gallery preview from Forge gallery");

        root.append(previewButton, strip, grabButton);
        container.append(root);

        let refreshQueued = false;
        let currentGallery = null;
        let observer = null;
        let selfHealPending = false;
        const retryTimers = new Set();

        function clearRetries() {
            for (const timer of retryTimers) clearTimeout(timer);
            retryTimers.clear();
        }

        function unbindGallery() {
            observer?.disconnect();
            observer = null;
            currentGallery = null;
            selfHealPending = false;
            clearRetries();
        }

        function bindGallery(gallery) {
            if (gallery === currentGallery) return;
            unbindGallery();
            currentGallery = gallery;
            if (!gallery) return;

            observer = new MutationObserver(queueRefresh);
            observer.observe(gallery, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: [
                    "class", "src", "srcset", "data-src", "data-original",
                    "data-lazy-src", "aria-selected", "data-selected",
                ],
            });
        }

        function createThumb(item, index, selected) {
            const src = thumbnailSource(item);
            if (!src) return null;

            const button = document.createElement("button");
            button.type = "button";
            button.className = "fdm-full-gallery-preview-thumb";
            button.dataset.selected = selected ? "true" : "false";
            button.title = `Select gallery image ${index + 1}`;
            button.setAttribute("aria-label", `Select gallery image ${index + 1}`);

            const sourceImage = thumbnailImage(item);
            const img = document.createElement("img");
            img.className = "fdm-full-gallery-preview-thumb-image";
            img.src = src;
            img.alt = sourceImage?.alt || `Gallery image ${index + 1}`;
            img.loading = "eager";
            img.decoding = "async";

            button.append(img);
            button.addEventListener("click", () => {
                selectGalleryItem(item);
                queueRefresh();
                const timer = setTimeout(() => {
                    retryTimers.delete(timer);
                    queueRefresh();
                }, 50);
                retryTimers.add(timer);
            });
            return button;
        }

        function updatePreview(gallery) {
            const item = selectedItem(gallery);
            // Prefer the selected thumbnail's real source. The main Gradio
            // preview is the node most likely to be blank while offscreen.
            const thumbSrc = thumbnailSource(item);
            const previewSrc = imageSource(selectedPreviewImage(gallery));
            const src = thumbSrc || previewSrc || "";

            previewButton.hidden = false;
            previewEmpty.hidden = Boolean(src);
            if (src) {
                if (previewImg.src !== src) previewImg.src = src;
                previewImg.alt = thumbnailImage(item)?.alt || "Current gallery image";
            } else {
                previewImg.removeAttribute("src");
            }
            return Boolean(src);
        }

        function forceGrabGallery() {
            const tabName = ctx.currentGenerationTab();
            const gallery = galleryRoot(ctx, tabName);
            if (!gallery) return;

            grabButton.dataset.refreshing = "true";

            // Rebind in case Gradio replaced the Gallery subtree. Then ensure
            // there is an actual selected_index by clicking the selected main
            // grid item, or the first item when Gradio left selection null.
            unbindGallery();
            bindGallery(gallery);
            hydrateNativeGallery(gallery);

            const items = nativeGalleryItems(gallery);
            const active = items.find(isSelected) || items[0] || null;
            if (active) clickNative(active);

            queueRefresh();

            clearRetries();
            for (const delay of [40, 120, 280]) {
                const timer = setTimeout(() => {
                    retryTimers.delete(timer);
                    hydrateNativeGallery(gallery);
                    queueRefresh();
                }, delay);
                retryTimers.add(timer);
            }

            const doneTimer = setTimeout(() => {
                retryTimers.delete(doneTimer);
                delete grabButton.dataset.refreshing;
            }, 420);
            retryTimers.add(doneTimer);
        }

        function refresh() {
            refreshQueued = false;
            const tabName = ctx.currentGenerationTab();
            const gallery = galleryRoot(ctx, tabName);
            const supported = (tabName === "txt2img" || tabName === "img2img") && Boolean(gallery);
            ctx.setVisible(supported);

            if (!supported) {
                unbindGallery();
                strip.replaceChildren();
                previewButton.hidden = false;
                previewImg.removeAttribute("src");
                previewEmpty.hidden = false;
                return;
            }

            bindGallery(gallery);
            hydrateNativeGallery(gallery);

            const items = nativeGalleryItems(gallery);
            const activeItem = selectedItem(gallery);
            const thumbs = items
                .map((item, index) => createThumb(item, index, item === activeItem))
                .filter(Boolean);

            strip.replaceChildren(...thumbs);
            const hasPreview = updatePreview(gallery);

            // Gradio can update gallery data while leaving selected_index null.
            // The main grid still has every image in that state, so select the
            // first real grid item once to materialize Gradio's preview again.
            const hasNativeSelection = items.some(isSelected);
            if (items.length && (!hasNativeSelection || !hasPreview) && !selfHealPending) {
                selfHealPending = true;
                hydrateNativeGallery(gallery);
                clickNative(items.find(isSelected) || items[0]);
                const timer = setTimeout(() => {
                    retryTimers.delete(timer);
                    selfHealPending = false;
                    queueRefresh();
                }, 80);
                retryTimers.add(timer);
            } else if (hasNativeSelection && hasPreview) {
                selfHealPending = false;
            }

            ctx.requestPosition();
        }

        function queueRefresh() {
            if (refreshQueued) return;
            refreshQueued = true;
            requestAnimationFrame(refresh);
        }

        previewButton.addEventListener("click", () => {
            const tabName = ctx.currentGenerationTab();
            openCurrentLightbox(galleryRoot(ctx, tabName));
        });

        grabButton.addEventListener("click", (event) => {
            event.stopPropagation();
            forceGrabGallery();
        });

        ctx.onLifecycle(queueRefresh);
        container._fdmFullGalleryPreviewCleanup = () => {
            unbindGallery();
            clearRetries();
        };
        refresh();
    }

    function unmount(container) {
        container._fdmFullGalleryPreviewCleanup?.();
        delete container._fdmFullGalleryPreviewCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "Full Gallery Preview",
        mount,
        unmount,
    });
})();
