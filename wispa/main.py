"""wispa — local Wispr Flow. Hold the hotkey, talk, release, text appears."""

import concurrent.futures
import sys
import time

from . import appcontext, config, injector
from .cleaner import Cleaner
from .hotkey import PushToTalkListener
from .recorder import SAMPLE_RATE, Recorder
from .transcriber import Transcriber


class App:
    def __init__(self, cfg: config.Config):
        self.cfg = cfg
        self.recorder = Recorder()
        self.transcriber = Transcriber(cfg.asr.model)
        self.cleaner = (
            Cleaner(
                cfg.cleanup.model,
                cfg.cleanup.timeout,
                dictionary=cfg.dictionary.terms,
                skip_when_clean=cfg.cleanup.skip_when_clean,
            )
            if cfg.cleanup.enabled
            else None
        )
        self.overlay = None  # created on the main thread in run()
        self.listener = None
        # Serial queues: mic start/stop stay ordered and OFF the tap callback;
        # dictations insert one at a time so overlapping streams can't interleave
        self._record_exec = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._insert_exec = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def warm_up(self):
        # Persistent mic stream: avoids the 70-150ms open cost on key-press
        # that was cutting off the first syllables (mic indicator stays on)
        self.recorder.open()
        print("Loading ASR model (downloads ~600MB on first run)...", flush=True)
        seconds = self.transcriber.load()
        print(f"ASR ready in {seconds:.1f}s.")
        if self.cleaner:
            # Load the LLM now (and keep it loaded, see _keep_warm) so the
            # first dictation never pays the ~5s cold-start
            self._insert_exec.submit(self.cleaner.warm)
            print(f"Cleanup: {self.cfg.cleanup.model} via Ollama (falls back to raw transcript if unavailable).")
        else:
            print("Cleanup: disabled.")

    def _keep_warm(self):
        from PyObjCTools import AppHelper

        if self.cleaner:
            self._insert_exec.submit(self.cleaner.warm)
        AppHelper.callLater(3600, self._keep_warm)  # re-ping within keep_alive=2h

    # Hotkey callbacks arrive on the main thread inside the event tap callback.
    # They must ONLY enqueue work: anything slow here gets the tap disabled by
    # macOS, which loses events — including the Fn release ("won't stop listening").

    def on_press(self):
        # Capture the target app now — focus can change while we process
        self._app_name = appcontext.frontmost_app_name()
        self._record_exec.submit(self._start_recording, self._app_name)

    def on_release(self):
        self._record_exec.submit(self._stop_and_queue, self._app_name)

    def _start_recording(self, app_name):
        from PyObjCTools import AppHelper

        self.recorder.start()
        AppHelper.callAfter(self.overlay.show_recording)
        AppHelper.callAfter(self._watchdog)
        print(f"\n● recording (into {app_name})...", flush=True)

    def _stop_and_queue(self, app_name):
        from PyObjCTools import AppHelper

        audio = self.recorder.stop()
        duration = len(audio) / SAMPLE_RATE
        if duration < self.cfg.min_duration:
            AppHelper.callAfter(self._maybe_hide_overlay)
            print("  (too short, ignored)")
            return
        AppHelper.callAfter(self.overlay.show_processing)
        self._insert_exec.submit(self._process, audio, duration, app_name)

    def _watchdog(self, ups: int = 0):
        """Safety net for a lost release event: while recording, poll the real
        keyboard state and force the stop if the key is actually up. Requires
        two consecutive key-up reads so one glitchy poll can't cut a dictation."""
        from PyObjCTools import AppHelper

        if not self.recorder.is_recording:
            return
        if not self.listener.hotkey_currently_down():
            if ups + 1 >= 2:
                print("  (release event was lost — stopping via watchdog)")
                self.listener.resync()  # fires on_release if state disagrees
                return
            AppHelper.callLater(0.4, self._watchdog, ups + 1)
            return
        AppHelper.callLater(0.4, self._watchdog, 0)

    def _maybe_hide_overlay(self):
        # Don't hide if the user is already recording the next dictation
        if not self.recorder.is_recording:
            self.overlay.hide()

    def _process(self, audio, duration, app_name):
        from PyObjCTools import AppHelper

        try:
            t0 = time.perf_counter()
            transcript = self.transcriber.transcribe(audio)
            asr_ms = (time.perf_counter() - t0) * 1000
            if not transcript:
                print("  (heard nothing)")
                return

            inserter = injector.StreamInserter(
                self.cfg.injection.method, self.cfg.injection.restore_clipboard
            )
            text, was_cleaned = (transcript, False)
            llm_ms = 0.0
            if self.cleaner:
                t1 = time.perf_counter()
                text, was_cleaned = self.cleaner.clean_stream(
                    transcript, app_name, on_text=inserter.feed
                )
                llm_ms = (time.perf_counter() - t1) * 1000
            if not inserter.received:
                # Cleanup disabled, skip-gate hit, or total failure: insert whole
                inserter.feed(text)
            path = inserter.finish()

            print(f"  {text}")
            print(
                f"  [{duration:.1f}s audio | asr {asr_ms:.0f}ms | "
                f"llm {llm_ms:.0f}ms{'' if was_cleaned else ' (raw)'} | inserted via {path}]"
            )
        finally:
            # UI work must happen on the main thread
            AppHelper.callAfter(self._maybe_hide_overlay)

    def run(self):
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        from PyObjCTools import AppHelper

        from .overlay import Overlay

        self.warm_up()

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self.overlay = Overlay(level_source=lambda: self.recorder.levels)

        self.listener = PushToTalkListener(self.cfg.hotkey, self.on_press, self.on_release)
        self.listener.install()

        pretty = {"fn": "Fn", "right_option": "Right Option", "ctrl_option": "Ctrl+Option"}[self.cfg.hotkey]
        print(f"\nHold {pretty} and speak. Release to insert. Ctrl+C here to quit.")
        AppHelper.callLater(3600, self._keep_warm)
        AppHelper.runEventLoop(installInterrupt=True)


def run():
    # Line-buffer stdout even when redirected, so status lines appear live
    sys.stdout.reconfigure(line_buffering=True)
    cfg = config.load()
    try:
        App(cfg).run()
    except PermissionError as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
