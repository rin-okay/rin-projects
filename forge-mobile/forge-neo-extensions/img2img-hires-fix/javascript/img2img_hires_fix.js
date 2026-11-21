(function () {
    function appRoot() {
        return typeof gradioApp === "function" ? gradioApp() : document;
    }

    function moveButton() {
        const root = appRoot();
        const row = root.querySelector("#image_buttons_img2img");
        if (!row) return;

        const hiresButton = root.querySelector("#img2img_hires_fix_manual_button");
        if (hiresButton && hiresButton.parentElement !== row) {
            row.appendChild(hiresButton);
            hiresButton.style.display = "flex";
        }


    }

    function setButtonBusy(busy) {
        const component = appRoot().querySelector("#img2img_hires_fix_manual_button");
        if (!component) return;
        const button = component.matches("button")
            ? component
            : component.querySelector("button");
        if (button) {
            button.disabled = busy;
            button.setAttribute("aria-busy", busy ? "true" : "false");
        }
        component.setAttribute("aria-busy", busy ? "true" : "false");
    }

    function selectedImg2ImgIndex() {
        // Scope selection to this gallery. The global helper can return an
        // index from another visible gallery supplied by an extension.
        if (typeof selected_gallery_index_id === "function") {
            return selected_gallery_index_id("img2img_gallery_container");
        }
        if (typeof selected_gallery_index === "function") {
            return selected_gallery_index();
        }
        return -1;
    }

    function finishHiresTask() {
        setButtonBusy(false);
        if (typeof showSubmitButtons === "function") {
            showSubmitButtons("img2img", true);
        }
        if (typeof localRemove === "function") {
            localRemove("img2img_task_id");
        }
        if (typeof showRestoreProgressButton === "function") {
            showRestoreProgressButton("img2img", false);
        }
    }

    window.i2iHiresFinish = function () {
        finishHiresTask();
        return Array.from(arguments);
    };

    window.i2iHiresPrepare = function () {
        const res = typeof create_submit_args === "function"
            ? create_submit_args(arguments)
            : Array.from(arguments);

        const id = typeof randomId === "function"
            ? randomId()
            : `task(${Date.now()}-${Math.random().toString(16).slice(2)})`;

        // Match Forge's native submit_img2img task lifecycle. This is what
        // makes the progress bar and live preview poll correctly on mobile.
        if (typeof showSubmitButtons === "function") {
            showSubmitButtons("img2img", false);
        }
        if (typeof localSet === "function") {
            localSet("img2img_task_id", id);
        }
        setButtonBusy(true);

        const progressContainer = appRoot().getElementById("img2img_gallery_container");
        const gallery = appRoot().getElementById("img2img_gallery");
        if (typeof requestProgress === "function" && progressContainer) {
            try {
                requestProgress(id, progressContainer, gallery, finishHiresTask);
            } catch (error) {
                console.error("Unable to start img2img Hires progress polling", error);
                // Submission still proceeds. Only the Gradio completion hook
                // may release busy state when polling cannot observe the job.
            }
        } else {
            // Older/forked UIs still submit correctly, but cannot expose the
            // native progress poller. The Gradio completion hook restores the
            // button when the backend call actually finishes.
        }

        // Input layout: task id, gallery, selected-index placeholder,
        // generation info, followed by the hires controls.
        res[0] = id;
        res[2] = selectedImg2ImgIndex();

        return res;
    };


    if (typeof onUiLoaded === "function") {
        onUiLoaded(moveButton);
    }
    if (typeof onAfterUiUpdate === "function") {
        onAfterUiUpdate(moveButton);
    } else {
        const observer = new MutationObserver(moveButton);
        observer.observe(document.documentElement, { childList: true, subtree: true });
    }
})();
