import unittest

from cloudflare_tunnel import (
    CloudflareQuickTunnel,
    build_quick_tunnel_command,
    extract_quick_tunnel_url,
)


class CloudflareTunnelTests(unittest.TestCase):
    def test_extracts_only_a_quick_tunnel_hostname(self):
        line = "INF | https://violet-sky-123.trycloudflare.com | ready"
        self.assertEqual(
            extract_quick_tunnel_url(line),
            "https://violet-sky-123.trycloudflare.com",
        )
        self.assertEqual(extract_quick_tunnel_url("https://example.com"), "")

    def test_builds_loopback_target_command(self):
        self.assertEqual(
            build_quick_tunnel_command("cloudflared.exe", 8765),
            ["cloudflared.exe", "tunnel", "--url", "http://127.0.0.1:8765"],
        )
        with self.assertRaises(ValueError):
            build_quick_tunnel_command("cloudflared.exe", 0)

    def test_missing_binary_is_reported_without_starting_a_process(self):
        tunnel = CloudflareQuickTunnel(8765, executable="does-not-exist-cloudflared")
        self.assertFalse(tunnel.start())
        self.assertIn("未找到", tunnel.error)
        self.assertFalse(tunnel.running)


if __name__ == "__main__":
    unittest.main()
