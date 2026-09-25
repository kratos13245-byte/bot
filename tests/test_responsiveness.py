import os
import threading
import unittest
from unittest.mock import Mock, patch

import ai
import tts
from speech_pipeline import play_phrases


class ResponsivenessTests(unittest.TestCase):
    def test_first_phrase_plays_before_second_finishes(self):
        first_played = threading.Event()
        played = []

        def synthesize(phrase):
            if phrase == "second":
                if not first_played.wait(timeout=2):
                    raise AssertionError("Playback waited for the whole response")
            return phrase

        def play(audio):
            played.append(audio)
            first_played.set()

        play_phrases(["first", "second", "third"], synthesize, play)
        self.assertEqual(played, ["first", "second", "third"])

    def test_failed_phrase_does_not_repeat_already_spoken_audio(self):
        played = []
        def synthesize(phrase):
            if phrase == "second":
                raise RuntimeError("voice offline")
            return phrase
        with self.assertRaises(RuntimeError):
            play_phrases(["first", "second", "third"], synthesize, played.append)
        self.assertEqual(played, ["first"])

    def test_empty_response_does_not_call_synthesizer(self):
        synthesize = Mock()
        play_phrases([], synthesize, Mock())
        synthesize.assert_not_called()

    def test_remote_speech_keeps_order_and_emotion(self):
        session = Mock()
        session.post.side_effect = lambda url, json, timeout: Mock(content=json["text"].encode())
        with patch("tts._resolver_remote_tts_url", return_value="http://voice/tts"), \
             patch("tts.requests.Session") as session_class, \
             patch("tts._wav_bytes_to_audio_array", side_effect=lambda data: (data.decode(), 24000)), \
             patch("tts._play_audio_array") as play, \
             patch.dict(os.environ, {"TTS_PHRASE_PIPELINE": "1"}):
            session_class.return_value.__enter__.return_value = session
            tts._falar_remoto("Porra, consegui! Agora vem comigo.", emocao="animada")
        self.assertEqual([call.args[0] for call in play.call_args_list], ["Porra, consegui!", "Agora vem comigo."])
        self.assertTrue(all(call.kwargs["json"]["emotion"] == "animada" for call in session.post.call_args_list))

    def test_emotion_does_not_insert_canned_denials(self):
        self.assertEqual(tts.aplicar_emocao("Pode deixar comigo.", "negar"), "Pode deixar comigo.")
        self.assertEqual(tts.aplicar_emocao("De novo isso.", "irritada"), "De novo isso.")

    def test_profanity_remains_configurable(self):
        with patch.dict(os.environ, {"AI_ALLOW_PROFANITY": "1", "AI_PROFANITY_LEVEL": "alto"}):
            self.assertIn("liberados", ai._instrucao_palavroes())
        with patch.dict(os.environ, {"AI_ALLOW_PROFANITY": "0"}):
            self.assertIn("Evite", ai._instrucao_palavroes())
