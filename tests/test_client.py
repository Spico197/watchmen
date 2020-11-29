import unittest

from watchmen.client import ClientMode


class TestClientMode(unittest.TestCase):
    def test_in_mode_method(self):
        self.assertEqual(ClientMode.has_value("queue"), True)
