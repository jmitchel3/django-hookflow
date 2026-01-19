from __future__ import annotations

import unittest

from django_hookflow.retry import DEFAULT_RETRY_CONFIG
from django_hookflow.retry import RetryConfig
from django_hookflow.retry import get_retry_delay
from django_hookflow.retry import should_retry


class TestRetryConfig(unittest.TestCase):
    def test_default_config_values(self):
        config = RetryConfig()
        self.assertEqual(config.max_retries, 3)
        self.assertEqual(config.initial_delay_seconds, 1)
        self.assertEqual(config.max_delay_seconds, 300)
        self.assertEqual(config.exponential_base, 2.0)

    def test_custom_config_values(self):
        config = RetryConfig(
            max_retries=5,
            initial_delay_seconds=2,
            max_delay_seconds=600,
            exponential_base=3.0,
        )
        self.assertEqual(config.max_retries, 5)
        self.assertEqual(config.initial_delay_seconds, 2)
        self.assertEqual(config.max_delay_seconds, 600)
        self.assertEqual(config.exponential_base, 3.0)


class TestExponentialBackoff(unittest.TestCase):
    def test_delay_for_attempt_zero(self):
        config = RetryConfig(initial_delay_seconds=1, exponential_base=2.0)
        # 1 * 2^0 = 1
        self.assertEqual(config.get_delay_for_attempt(0), 1)

    def test_delay_for_attempt_one(self):
        config = RetryConfig(initial_delay_seconds=1, exponential_base=2.0)
        # 1 * 2^1 = 2
        self.assertEqual(config.get_delay_for_attempt(1), 2)

    def test_delay_for_attempt_two(self):
        config = RetryConfig(initial_delay_seconds=1, exponential_base=2.0)
        # 1 * 2^2 = 4
        self.assertEqual(config.get_delay_for_attempt(2), 4)

    def test_delay_for_attempt_three(self):
        config = RetryConfig(initial_delay_seconds=1, exponential_base=2.0)
        # 1 * 2^3 = 8
        self.assertEqual(config.get_delay_for_attempt(3), 8)

    def test_delay_with_different_initial_delay(self):
        config = RetryConfig(initial_delay_seconds=5, exponential_base=2.0)
        # 5 * 2^2 = 20
        self.assertEqual(config.get_delay_for_attempt(2), 20)

    def test_delay_with_different_base(self):
        config = RetryConfig(initial_delay_seconds=1, exponential_base=3.0)
        # 1 * 3^2 = 9
        self.assertEqual(config.get_delay_for_attempt(2), 9)

    def test_max_delay_cap(self):
        config = RetryConfig(
            initial_delay_seconds=100,
            max_delay_seconds=300,
            exponential_base=2.0,
        )
        # 100 * 2^5 = 3200, but should be capped at 300
        self.assertEqual(config.get_delay_for_attempt(5), 300)

    def test_delay_just_under_max(self):
        config = RetryConfig(
            initial_delay_seconds=1,
            max_delay_seconds=300,
            exponential_base=2.0,
        )
        # 1 * 2^8 = 256, under cap
        self.assertEqual(config.get_delay_for_attempt(8), 256)

    def test_delay_at_max(self):
        config = RetryConfig(
            initial_delay_seconds=1,
            max_delay_seconds=300,
            exponential_base=2.0,
        )
        # 1 * 2^9 = 512, should be capped at 300
        self.assertEqual(config.get_delay_for_attempt(9), 300)


class TestShouldRetry(unittest.TestCase):
    def test_should_retry_at_attempt_zero(self):
        self.assertTrue(should_retry(0))

    def test_should_retry_at_attempt_one(self):
        self.assertTrue(should_retry(1))

    def test_should_retry_at_attempt_two(self):
        self.assertTrue(should_retry(2))

    def test_should_not_retry_at_max_retries(self):
        # Default max_retries is 3, so attempt 3 should not retry
        self.assertFalse(should_retry(3))

    def test_should_not_retry_beyond_max_retries(self):
        self.assertFalse(should_retry(4))

    def test_should_retry_with_custom_config(self):
        config = RetryConfig(max_retries=5)
        self.assertTrue(should_retry(4, config))
        self.assertFalse(should_retry(5, config))

    def test_should_retry_with_zero_max_retries(self):
        config = RetryConfig(max_retries=0)
        self.assertFalse(should_retry(0, config))

    def test_uses_default_config(self):
        # Verify it uses DEFAULT_RETRY_CONFIG
        self.assertEqual(DEFAULT_RETRY_CONFIG.max_retries, 3)
        self.assertTrue(should_retry(2))
        self.assertFalse(should_retry(3))


class TestGetRetryDelay(unittest.TestCase):
    def test_get_retry_delay_uses_config(self):
        self.assertEqual(get_retry_delay(0), 1)
        self.assertEqual(get_retry_delay(1), 2)
        self.assertEqual(get_retry_delay(2), 4)

    def test_get_retry_delay_with_custom_config(self):
        config = RetryConfig(initial_delay_seconds=10, exponential_base=2.0)
        self.assertEqual(get_retry_delay(0, config), 10)
        self.assertEqual(get_retry_delay(1, config), 20)
        self.assertEqual(get_retry_delay(2, config), 40)

    def test_get_retry_delay_respects_max(self):
        config = RetryConfig(
            initial_delay_seconds=100,
            max_delay_seconds=150,
            exponential_base=2.0,
        )
        # 100 * 2^0 = 100
        self.assertEqual(get_retry_delay(0, config), 100)
        # 100 * 2^1 = 200, capped at 150
        self.assertEqual(get_retry_delay(1, config), 150)


if __name__ == "__main__":
    unittest.main()
