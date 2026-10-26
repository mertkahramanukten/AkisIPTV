"""StreamGuard durum makinesi testleri (mpv/Qt gerekmez)."""
import unittest

from akis.guard import BUFFER_LEVELS, GState, GuardConfig, StreamGuard


def kinds(actions):
    return [a.kind for a in actions]


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.g = StreamGuard(GuardConfig(), buffer_level=1)
        self.t = 1000.0

    def play(self, live=True, formats=("ts", "m3u8"), start=0.0):
        acts = self.g.start(self.t, live, list(formats), start)
        self.g.mark_loading(self.t)
        self.g.on_idle(self.t + 0.1, False)
        return acts

    def test_start_requests_reload(self):
        acts = self.play()
        self.assertEqual(kinds(acts), ["reload"])
        self.assertEqual(acts[0].fmt, "ts")
        self.assertEqual(self.g.state, GState.OPENING)

    def test_open_timeout_triggers_retry_with_backoff(self):
        self.play()
        self.assertEqual(self.g.tick(self.t + 5), [])
        acts = self.g.tick(self.t + 16)
        self.assertIn("stop", kinds(acts))
        self.assertEqual(self.g.state, GState.WAITING)
        # bekleme süresi dolmadan yeniden yükleme yok
        self.assertEqual(self.g.tick(self.t + 16.3), [])
        acts = self.g.tick(self.t + 17)
        self.assertEqual(kinds(acts), ["reload"])

    def test_progress_moves_to_playing_and_stall_detected(self):
        self.play()
        self.g.on_progress(self.t + 1, 0.0)
        self.assertEqual(self.g.state, GState.PLAYING)
        for i in range(2, 6):
            self.g.on_progress(self.t + i, float(i))
        self.assertEqual(self.g.tick(self.t + 10), [])
        acts = self.g.tick(self.t + 14.5)  # 5'ten beri ilerleme yok > 8 sn
        self.assertIn("stop", kinds(acts))
        self.assertIn("dondu", acts[-1].message)

    def test_cache_pause_is_not_a_freeze_until_buffering_timeout(self):
        self.play()
        self.g.on_progress(self.t + 1, 1.0)
        self.g.on_cache_pause(self.t + 2, True)
        self.assertEqual(self.g.tick(self.t + 11), [])   # buffer doluyor, sabret
        acts = self.g.tick(self.t + 13)
        self.assertIn("stop", kinds(acts))
        self.assertIn("Veri gelmiyor", acts[-1].message)

    def test_user_pause_never_counts_as_freeze(self):
        self.play()
        self.g.on_progress(self.t + 1, 1.0)
        self.g.on_user_pause(self.t + 2, True)
        self.assertEqual(self.g.tick(self.t + 300), [])

    def test_live_end_reconnects(self):
        self.play()
        self.g.on_progress(self.t + 1, 1.0)
        acts = self.g.on_idle(self.t + 30, True)
        self.assertIn("stop", kinds(acts))
        self.assertEqual(self.g.state, GState.WAITING)

    def test_stale_idle_event_before_active_is_ignored(self):
        self.g.start(self.t, True, ["ts"])
        self.g.mark_loading(self.t)
        self.assertEqual(self.g.on_idle(self.t + 0.05, True), [])
        self.assertEqual(self.g.state, GState.OPENING)

    def test_format_switch_after_two_failures(self):
        self.play()
        self.g.tick(self.t + 16)            # hata 1 (ts)
        acts = self.g.tick(self.t + 17)     # reload ts
        self.assertEqual(acts[0].fmt, "ts")
        self.g.mark_loading(self.t + 17)
        fail2 = self.g.tick(self.t + 33)    # hata 2 → m3u8'e geç
        self.assertIn("HLS", fail2[-1].message)
        acts = self.g.tick(self.t + 40)
        self.assertEqual(acts[0].kind, "reload")
        self.assertEqual(acts[0].fmt, "m3u8")
        # HLS stabil oynarsa: m3u8 iyi, ts kötü olarak raporlanır
        self.g.mark_loading(self.t + 40)
        self.g.on_idle(self.t + 40.1, False)
        for i in range(30):
            self.g.on_progress(self.t + 41 + i, float(i))
        acts = self.g.tick(self.t + 71)
        self.assertEqual([(a.kind, a.fmt) for a in acts], [("format_ok", "m3u8"), ("format_bad", "ts")])

    def test_vod_resumes_from_last_position(self):
        self.play(live=False, formats=("mp4",), start=0)
        self.g.on_duration(3600)
        self.g.on_progress(self.t + 1, 0.0)
        self.g.on_progress(self.t + 2, 1200.0)
        self.g.on_idle(self.t + 3, True)    # bağlantı koptu
        acts = self.g.tick(self.t + 10)
        self.assertEqual(acts[0].kind, "reload")
        self.assertAlmostEqual(acts[0].start, 1197.0)

    def test_vod_real_end_is_finished(self):
        self.play(live=False, formats=("mp4",))
        self.g.on_duration(100)
        self.g.on_progress(self.t + 1, 0.0)
        self.g.on_progress(self.t + 2, 95.0)
        acts = self.g.on_idle(self.t + 3, True)
        self.assertEqual(kinds(acts), ["finished"])
        self.assertEqual(self.g.state, GState.FINISHED)

    def test_adaptive_buffer_raises_on_repeated_underruns(self):
        self.play()
        self.g.on_progress(self.t + 1, 0.0)
        self.g.on_cache_pause(self.t + 10, True)
        self.g.on_cache_pause(self.t + 12, False)
        acts = self.g.on_cache_pause(self.t + 30, True)
        self.assertEqual(kinds(acts), ["raise_buffer"])
        self.assertEqual(self.g.buffer_level, 2)
        self.assertEqual(BUFFER_LEVELS[acts[0].level], BUFFER_LEVELS[2])

    def test_seek_does_not_count_as_underrun(self):
        self.play(live=False, formats=("mp4",))
        self.g.on_progress(self.t + 1, 0.0)
        for k in range(5):
            now = self.t + 10 + k * 10
            self.g.on_seek(now)
            self.assertEqual(self.g.on_cache_pause(now + 0.5, True), [])
            self.g.on_cache_pause(now + 1, False)
        self.assertEqual(self.g.buffer_level, 1)

    def test_404_gives_up_quickly(self):
        self.play(formats=("ts", "m3u8"))
        self.g.on_http_error(404)
        self.g.on_idle(self.t + 1, True)
        acts = self.g.tick(self.t + 5)
        self.assertEqual(acts[0].fmt, "m3u8")      # önce HLS denenir
        self.assertIsNone(self.g.switched_from)    # 404 formatın suçu değil
        self.g.mark_loading(self.t + 5)
        self.g.on_idle(self.t + 5.1, False)
        self.g.on_http_error(404)
        acts = self.g.on_idle(self.t + 6, True)
        self.assertIn("give_up", kinds(acts))
        self.assertEqual(self.g.state, GState.FAILED)

    def test_connection_limit_waits_longer(self):
        self.play(formats=("ts",))
        self.g.on_http_error(403)
        self.g.on_idle(self.t + 1, True)
        self.assertGreaterEqual(self.g.reconnect_at - (self.t + 1), 3.0)

    def test_gives_up_after_max_retries(self):
        cfg = GuardConfig(max_retries=3, backoff=(0.1,))
        g = StreamGuard(cfg)
        now = self.t
        g.start(now, True, ["ts"])
        g.mark_loading(now)
        gave_up = False
        for _ in range(10):
            now += 20
            acts = g.tick(now)       # açılış zaman aşımı
            if "give_up" in kinds(acts):
                gave_up = True
                break
            now += 1
            for a in g.tick(now):
                if a.kind == "reload":
                    g.mark_loading(now)
        self.assertTrue(gave_up)

    def test_stable_playback_resets_retry_counter(self):
        self.play()
        self.g.tick(self.t + 16)
        self.g.tick(self.t + 17)
        self.g.mark_loading(self.t + 17)
        self.g.on_idle(self.t + 17.1, False)
        self.assertEqual(self.g.retries, 1)
        for i in range(0, 30):
            self.g.on_progress(self.t + 18 + i, float(i))
        acts = self.g.tick(self.t + 47)
        self.assertEqual(kinds(acts), ["format_ok"])
        self.assertEqual(self.g.retries, 0)

    def test_live_data_stall_detected_faster_than_vod(self):
        self.play()
        self.g.on_progress(self.t + 1, 1.0)
        self.g.on_cache_pause(self.t + 2, True)
        acts = self.g.tick(self.t + 13)
        self.assertIn("Veri gelmiyor", acts[-1].message)


    def test_401_rotates_user_agent_and_learns_working_one(self):
        acts = self.g.start(self.t, True, ["ts", "m3u8"], ua_count=4)
        self.g.mark_loading(self.t)
        self.g.on_idle(self.t + 0.1, False)
        self.g.on_http_error(401)
        acts = self.g.on_error(self.t + 0.2, "Yayın açılamadı")
        self.assertIn("switch_ua", kinds(acts))
        self.assertEqual(self.g.ua_index, 1)
        self.assertEqual(self.g.retries, 0)            # kimlik denemesi hak yemez
        acts = self.g.tick(self.t + 1)
        self.assertEqual(acts[0].kind, "reload")
        self.assertEqual(acts[0].fmt, "ts")            # format değişmez, sadece kimlik
        self.g.mark_loading(self.t + 1)
        self.g.on_idle(self.t + 1.1, False)
        acts = self.g.on_progress(self.t + 2, 0.0)
        self.assertIn("ua_ok", kinds(acts))
        self.assertEqual([a.level for a in acts if a.kind == "ua_ok"], [1])

    def test_401_with_all_user_agents_failing_gives_up(self):
        self.g.start(self.t, True, ["ts", "m3u8"], ua_count=3)
        now = self.t
        gave_up = None
        for _ in range(12):
            self.g.mark_loading(now)
            self.g.on_idle(now + 0.1, False)
            self.g.on_http_error(401)
            acts = self.g.on_error(now + 0.2, "Yayın açılamadı")
            if "give_up" in kinds(acts):
                gave_up = acts[-1].message
                break
            now += 5
            self.g.tick(now)
        self.assertIsNotNone(gave_up)
        self.assertIn("401", gave_up)
        self.assertEqual(self.g.ua_index, 2)

    def test_single_403_waits_instead_of_rotating(self):
        self.g.start(self.t, True, ["ts"], ua_count=3)
        self.g.mark_loading(self.t)
        self.g.on_idle(self.t + 0.1, False)
        self.g.on_http_error(403)
        acts = self.g.on_error(self.t + 0.2, "Yayın açılamadı")
        self.assertNotIn("switch_ua", kinds(acts))     # önce bağlantı limiti varsayılır
        self.assertGreaterEqual(self.g.reconnect_at - (self.t + 0.2), 3.0)


if __name__ == "__main__":
    unittest.main()
