"""Synthesize at most one phrase ahead while the current phrase plays."""
from concurrent.futures import ThreadPoolExecutor


def play_phrases(phrases, synthesize, play):
    phrases = iter(phrases)
    first = next(phrases, None)
    if first is None:
        return
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="iara-voice") as worker:
        pending = worker.submit(synthesize, first)
        while pending is not None:
            audio = pending.result()
            following = next(phrases, None)
            pending = worker.submit(synthesize, following) if following is not None else None
            play(audio)
