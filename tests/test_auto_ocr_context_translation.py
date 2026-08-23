import unittest

from ui.services.ocr_engine import assign_contextual_translations


class AssignContextualTranslationsTests(unittest.TestCase):
    def test_reorders_context_translation_by_input_lines(self):
        lines = [
            '今日はいい天気です',
            '明日も晴れます',
            'それで会議をします',
        ]
        translated = '今天天氣很好\n明天也會是晴天\n所以我們會開會'
        result = assign_contextual_translations(lines, translated)
        self.assertEqual(result, [
            '今天天氣很好',
            '明天也會是晴天',
            '所以我們會開會',
        ])

    def test_keeps_fallback_when_translation_has_extra_non_line_text(self):
        lines = ['A', 'B']
        translated = '總結：\n中文A\n中文B\n額外說明'
        result = assign_contextual_translations(lines, translated)
        self.assertEqual(result, ['中文A', '中文B'])


if __name__ == '__main__':
    unittest.main()
