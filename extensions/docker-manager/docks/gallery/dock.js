(() => {
    "use strict";

    const DOCK_ID = "gallery";

    function galleryRoot(ctx, tabName) {
        if (tabName !== "txt2img" && tabName !== "img2img") return null;
        const root = ctx.getById(`${tabName}_gallery`);
        if (!root) return null;
        if (root.matches?.(".gradio-gallery")) return root;
        return root.querySelector?.(".gradio-gallery") || root;
    }

    function nativeGalleryItems(gallery) {
        if (!gallery) return [];

        // This is the same item list Forge uses in javascript/ui.js for
        // all_gallery_buttons()/selected_gallery_index(). One thumbnail-item
        // equals one active image in the Gradio gallery.
        let items = [...gallery.querySelectorAll?.(".thumbnails > .thumbnail-item.thumbnail-small") || []];

        // Fallback for minor Gradio markup changes while retaining one item per
        // gallery entry rather than scraping preview/hidden image copies.
        if (!items.length) {
            items = [...gallery.querySelectorAll?.(".thumbnail-item.thumbnail-small") || []];
        }

        return items.filter((item) => !item.closest?.(".fdm-dock-shell"));
    }

    function thumbnailImage(item) {
        return item?.querySelector?.("img") || null;
    }

    function thumbnailSource(item) {
        const img = thumbnailImage(item);
        return img?.currentSrc || img?.src || "";
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

        // Forge's imageviewer.js hooks these preview images for the lightbox.
        return gallery.querySelector?.(":scope > button > button > img")
            || gallery.querySelector?.("button > button > img")
            || null;
    }

    function clickNative(item) {
        if (!item) return;
        if (typeof item.click === "function") item.click();
        else item.dispatchEvent(new MouseEvent("click", {
            bubbles: true,
            cancelable: true,
            button: 0,
            view: window,
        }));
    }

    function openNativeLightbox(gallery, item) {
        if (!gallery || !item) return;

        // First select the real Gradio thumbnail. This keeps Forge's own
        // selected_gallery_index()/modal next/previous logic correct.
        clickNative(item);

        const openPreview = () => {
            const preview = selectedPreviewImage(gallery);
            if (!preview) return false;

            // Normally imageviewer.js has already attached this listener via
            // onAfterUiUpdate; set it up defensively if this gallery was just rebuilt.
            try {
                if (!preview.dataset?.modded && typeof window.setupImageForLightbox === "function") {
                    window.setupImageForLightbox(preview);
                }
            } catch (_error) {
                // no-op; the normal Forge lifecycle owns this hook
            }

            preview.dispatchEvent(new MouseEvent("click", {
                bubbles: true,
                cancelable: true,
                button: 0,
                view: window,
            }));
            return true;
        };

        // Gradio may replace/update the preview after thumbnail selection, so
        // try after layout and once more shortly after if necessary.
        requestAnimationFrame(() => {
            if (!openPreview()) setTimeout(openPreview, 40);
        });
    }

    function mount(container, ctx) {
        const strip = document.createElement("div");
        strip.className = "fdm-gallery-strip";

        const empty = document.createElement("div");
        empty.className = "fdm-gallery-empty";
        empty.textContent = "No images";

        container.append(strip, empty);

        let refreshQueued = false;
        let currentGallery = null;
        let observer = null;

        function unbindGallery() {
            observer?.disconnect();
            observer = null;
            currentGallery = null;
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
                attributeFilter: ["class", "src", "aria-selected", "data-selected"],
            });
        }

        function createThumb(gallery, item, index) {
            const src = thumbnailSource(item);
            if (!src) return null;

            const button = document.createElement("button");
            button.type = "button";
            button.className = "fdm-gallery-thumb";
            button.dataset.selected = isSelected(item) ? "true" : "false";
            button.title = `Open gallery image ${index + 1}`;
            button.setAttribute("aria-label", `Open gallery image ${index + 1} in lightbox`);

            const sourceImage = thumbnailImage(item);
            const img = document.createElement("img");
            img.className = "fdm-gallery-thumb-image";
            img.src = src;
            img.alt = sourceImage?.alt || `Gallery image ${index + 1}`;
            img.loading = "lazy";
            img.decoding = "async";

            button.append(img);
            button.addEventListener("click", () => {
                openNativeLightbox(gallery, item);
                queueRefresh();
            });
            return button;
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
                empty.hidden = false;
                return;
            }

            bindGallery(gallery);
            const items = nativeGalleryItems(gallery);
            const thumbs = items
                .map((item, index) => createThumb(gallery, item, index))
                .filter(Boolean);

            strip.replaceChildren(...thumbs);
            empty.hidden = thumbs.length > 0;
            ctx.requestPosition();
        }

        function queueRefresh() {
            if (refreshQueued) return;
            refreshQueued = true;
            requestAnimationFrame(refresh);
        }

        ctx.onLifecycle(queueRefresh);
        container._fdmGalleryCleanup = unbindGallery;
        refresh();
    }

    function unmount(container) {
        container._fdmGalleryCleanup?.();
        delete container._fdmGalleryCleanup;
    }

    window.ForgeDockManager.registerDock({
        id: DOCK_ID,
        name: "Gallery Dock",
        mount,
        unmount,
    });
})();
