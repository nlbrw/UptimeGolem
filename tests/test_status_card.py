import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from uptimeGolem import DiscordRateLimiter, UptimeGolemBot


def make_cog(online=True, current=3, maximum=10):
    cog = object.__new__(UptimeGolemBot)
    cog.current_status = dict(online=online, current_players=current,
                              max_players=maximum, player_list=[])
    return cog


class StatusCardTests(unittest.TestCase):
    def test_online_hierarchy(self):
        embed = make_cog()._build_status_embed(['Alex', 'Steve'])
        self.assertEqual(embed.title, '🟢 ONLINE')
        self.assertIn('3 / 10', embed.fields[0].value)
        self.assertIn('▰▰▰▱▱▱▱▱▱▱', embed.fields[0].value)
        self.assertIn('+ 1 weitere', embed.fields[1].value)

    def test_empty_and_unreported_rosters_are_distinct(self):
        empty = make_cog(current=0)._build_status_embed([])
        hidden = make_cog()._build_status_embed([])
        self.assertIn('Noch niemand', empty.fields[1].value)
        self.assertIn('keine Spielernamen', hidden.fields[1].value)

    def test_asleep_and_offline_hide_player_data(self):
        asleep = make_cog(maximum=20)._build_status_embed(['Alex'])
        offline = make_cog(online=False)._build_status_embed(['Alex'])
        self.assertEqual(asleep.title, '🌙 RUHEMODUS')
        self.assertEqual(offline.title, '🔴 OFFLINE')
        self.assertEqual(asleep.fields, [])
        self.assertEqual(offline.fields, [])

    def test_long_roster_respects_discord_limits(self):
        embed = make_cog(current=500, maximum=500)._build_status_embed(
            [f'player_{i}' for i in range(500)])
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
        self.assertLess(len(embed), 6000)
        self.assertIn('weitere Spieler', embed.fields[1].value)

    def test_names_are_escaped_and_capacity_can_be_unknown(self):
        embed = make_cog(maximum=0)._build_status_embed(['a_b', '@everyone'])
        self.assertIn('a\\_b', embed.fields[1].value)
        self.assertNotIn('@everyone', embed.fields[1].value)
        self.assertNotIn('/ 0', embed.fields[0].value)


class UpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_existing_card_instead_of_sending(self):
        cog = make_cog()
        cog.client = SimpleNamespace(user=object())
        message = SimpleNamespace(author=cog.client.user,
            embeds=[cog._build_status_embed([])], edit=AsyncMock())

        async def history(**kwargs):
            yield message

        channel = SimpleNamespace(history=history, send=AsyncMock())
        await cog._update_player_list_message(channel, [])
        message.edit.assert_awaited_once()
        channel.send.assert_not_awaited()

    async def test_send_failure_propagates_for_retry(self):
        cog = make_cog()

        async def history(**kwargs):
            for item in []:
                yield item

        channel = SimpleNamespace(history=history,
            send=AsyncMock(side_effect=RuntimeError('send failed')))
        with self.assertRaises(RuntimeError):
            await cog._update_player_list_message(channel, [])

    async def test_pending_voice_rename_does_not_repeat_text_edit(self):
        cog = make_cog()
        cog.first_status_update = True
        cog.offline_detected_at = None
        cog.last_voice_name = 'old voice name'
        cog.last_player_list = []
        cog.last_online_status = True
        cog.last_text_status = None
        cog.voice_rate_limiter = SimpleNamespace(should_update=AsyncMock(return_value=False),
                                                get_time_until_next_update=lambda: 300)
        cog.text_rate_limiter = DiscordRateLimiter(0)
        cog._update_player_list_message = AsyncMock()
        guild = SimpleNamespace(get_channel=lambda channel_id: object())
        cog.client = SimpleNamespace(get_guild=lambda guild_id: guild)
        await cog.discord_update_task()
        await cog.discord_update_task()
        cog._update_player_list_message.assert_awaited_once()
        # A changed player count still refreshes the text immediately.
        cog.current_status['current_players'] = 4
        await cog.discord_update_task()
        self.assertEqual(cog._update_player_list_message.await_count, 2)


if __name__ == '__main__':
    unittest.main()
