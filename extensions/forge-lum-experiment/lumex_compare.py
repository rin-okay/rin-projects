"""Explicit, queued same-seed comparisons in the user's running Forge instance."""
from contextlib import closing
import json
import random
import numpy as np
from PIL import Image
from lumex_core import remove_lumex_tags, validate_dimensions, VERSION


def image_metrics(baseline, effect):
    a = np.asarray(baseline.convert('RGB'), dtype=np.float32) / 255
    b = np.asarray(effect.convert('RGB'), dtype=np.float32) / 255
    difference = np.abs(b - a)
    return {'mean_absolute_pixel_change': float(difference.mean()),
            'baseline_mean': float(a.mean()), 'effect_mean': float(b.mean()),
            'effect_black_fraction': float((b.mean(axis=2) < .03).mean()),
            'effect_white_fraction': float((b.mean(axis=2) > .97).mean())}, Image.fromarray(np.round(np.clip(difference * 4, 0, 1) * 255).astype('uint8'))


def render_pair(script_class, prompt, negative, seed, width, height, steps, cfg, config):
    from modules import processing, scripts, shared
    if shared.state.interrupted:
        raise RuntimeError('Comparison interrupted')
    width, height = validate_dimensions(width, height)
    if width > 2048 or height > 2048 or width % 8 or height % 8:
        raise ValueError('Comparison dimensions must be multiples of 8 between 64 and 2048')
    if min(width, height) < 64 or not 1 <= int(steps) <= 60 or not 1 <= float(cfg) <= 20:
        raise ValueError('Invalid comparison dimensions, steps or CFG')
    seed = random.randrange(0, 4294967294) if int(seed) == -1 else int(seed)
    clean = remove_lumex_tags(prompt)
    prompts = [clean, clean + '\n' + config.tag()]
    results = []; details = []
    for text in prompts:
        if shared.state.interrupted or shared.state.stopping_generation:
            raise RuntimeError('Comparison interrupted')
        runner = scripts.ScriptRunner()
        hook = script_class(); hook.args_from = 0; hook.args_to = 0
        hook.filename = script_class.__module__; hook.alwayson = True
        runner.scripts = [hook]; runner.alwayson_scripts = [hook]
        with closing(processing.StableDiffusionProcessingTxt2Img(
            prompt=text, negative_prompt=remove_lumex_tags(negative), seed=seed,
            width=width, height=height, steps=int(steps), cfg_scale=float(cfg),
            sampler_name='Euler', scheduler='Automatic', batch_size=1, n_iter=1,
            enable_hr=False, do_not_save_samples=True, do_not_save_grid=True,
        )) as p:
            p.scripts = runner; p.script_args = ()
            processed = processing.process_images(p)
            if shared.state.interrupted or not processed.images:
                raise RuntimeError('Comparison interrupted or returned no image')
            if len(results) == 1 and not config.is_noop and not getattr(p, '_lumex_applied', False):
                raise RuntimeError('Lumex did not apply: ' + str(p.extra_generation_params.get('Lumex error', 'sampling hook was not called')))
            image = processed.images[processed.index_of_first_image].copy()
            results.append(image)
            details.append(dict(p.extra_generation_params))
    metrics, difference = image_metrics(*results)
    report = {'version': VERSION, 'seed': seed, 'width': width, 'height': height,
              'steps': int(steps), 'cfg': float(cfg), 'sampler': 'Euler', 'scheduler': 'Automatic',
              'tag': config.tag(), 'metrics': metrics, 'generation_details': details}
    return [(results[0], 'Baseline'), (results[1], 'Effect'), (difference, 'Absolute difference ×4')], json.dumps(report, indent=2), seed


def compare_ui(script_class, config_builder, prompt, negative, seed, width, height, steps, cfg, *controls):
    from modules import call_queue, shared
    from modules_forge import main_thread
    try:
        config = config_builder(*controls)
        # Same queue and execution thread as Forge txt2img, so encoding/generation
        # never races another render or edits global RNG state concurrently.
        with call_queue.queue_lock:
            shared.state.begin(job='Lumex comparison')
            try:
                result = main_thread.run_and_wait_result(render_pair, script_class, prompt, negative,
                                                        seed, width, height, steps, cfg, config)
                if result is None:
                    raise RuntimeError('Forge comparison failed; see the Forge console')
                return result
            finally:
                shared.state.end()
                shared.total_tqdm.clear()
    except Exception as exc:
        return [], f'Comparison failed: {type(exc).__name__}: {exc}', seed
